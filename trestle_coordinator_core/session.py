"""High-level session manager for Trestle device communication.

This module provides the canonical API for ecosystem adapters to communicate
with Trestle devices. It handles:
- Connection management and authentication
- Protocol state machine
- Batching and coalescing
- Delta sequence tracking
- Keepalive/reconnect logic
- Message routing

Ecosystem adapters (trestle-ha, trestle-knx, etc.) MUST use this API and
MUST NOT talk directly to devices.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from . import protobuf_util

from .errors import (
    TrestleClientError,
    TrestleConnectionError,
    TrestleHandshakeError,
    TrestleTimeout,
)
from .protocol import (
    build_auth_confirmed,
    build_envelope,
    build_time_body,
    parse_auth_ok,
)
from .ws_client import TrestleWsClient, TrestleWsMessageType

# Protocol Buffer support - import at module level for type checking
try:
    from . import protobuf_util

    protobuf_available = True
except ImportError:
    protobuf_util = None  # type: ignore[assignment]
    protobuf_available = False

_LOGGER = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS: tuple[int, ...] = (1,)


@dataclass(slots=True)
class _PendingDeltaAck:
    """Track outstanding delta acknowledgements."""

    seq: int
    sent_at: float


MAX_PENDING_DELTA_ACKS = 32


class TrestleSession:
    """High-level session manager for Trestle device communication.

    Usage:
        session = TrestleSession(device_id="abc123", host="192.168.1.10", port=80, token="secret")
        await session.connect()
        session.on_input_event(my_input_handler)
        session.on_connection_state_changed(my_state_handler)
        session.schedule_state_update("binding_1", "on")
        await session.send_layout(layout_package)
        await session.close()
    """

    def __init__(
        self,
        device_id: str,
        host: str,
        port: int,
        token: str,
        *,
        batch_interval: float = 0.5,
        ping_interval: int = 30,
        ping_timeout: int = 10,
        retry_base_delay: int = 5,
        retry_max_delay: int = 60,
    ):
        """Initialize session.

        Args:
            device_id: Device identifier
            host: Device hostname or IP
            port: Device port
            token: Authentication token
            batch_interval: State update batching window (seconds)
            ping_interval: Keepalive ping interval (seconds)
            ping_timeout: Ping timeout (seconds)
            retry_base_delay: Base retry delay (seconds)
            retry_max_delay: Maximum retry delay (seconds)
        """
        self.device_id = device_id
        self.host = host
        self.port = port
        self.token = token

        self._batch_interval = batch_interval
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay

        # Connection state
        self._ws: TrestleWsClient | None = None
        self._connection_state: str = "disconnected"
        self._listen_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._retry_attempts = 0
        self._shutdown_requested = False

        # Protocol state
        self._protocol_version: int | None = None
        self._device_protocol_versions: tuple[int, ...] | None = None
        self._capabilities: dict[str, Any] = {}

        # Delta tracking
        self._delta_seq = 0
        self._pending_delta_acks: dict[str, _PendingDeltaAck] = {}

        # Keepalive
        self._ping_task: asyncio.Task[None] | None = None
        self._last_pong_time: float | None = None
        self._missed_pong_windows = 0
        self._ping_id = 0
        self._pending_pings: dict[int, float] = {}

        # Batching
        self._pending_batch: dict[str, Any] = {}
        self._batch_timer: asyncio.TimerHandle | None = None

        # Layout state
        self._layout_applied = False
        self._current_layout_id: str | None = None
        self._snapshot_sent = False
        self._last_snapshot_states: list[dict[str, Any]] = []

        # Callbacks
        self._input_event_callback: Callable[[dict[str, Any]], None] | None = None
        self._state_request_callback: Callable[[str], Any] | None = None
        self._connection_state_callback: Callable[[str], None] | None = None
        self._auth_failed_callback: Callable[[], Awaitable[None] | None] | None = None
        self._device_state_callback: Callable[[dict[str, Any]], None] | None = None

        # Event loop reference (set on connect)
        self._loop: asyncio.AbstractEventLoop | None = None

    # -------------------------------------------------------------------------
    # Public API: Connection Management
    # -------------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect and authenticate to device.

        Returns:
            True if connection successful, False otherwise
        """
        if self._shutdown_requested:
            _LOGGER.debug("[%s] Connection aborted: shutdown requested", self.device_id)
            return False

        self._loop = asyncio.get_event_loop()
        self._set_state("connecting")

        try:
            _LOGGER.info(
                "[%s] Connecting to ws://%s:%s (attempt #%d)",
                self.device_id,
                self.host,
                self.port,
                self._retry_attempts + 1,
            )

            # Clean up existing connection
            if self._ws:
                try:
                    await asyncio.wait_for(self._ws.close(), timeout=2.0)
                except TimeoutError:
                    _LOGGER.warning(
                        "[%s] Previous WebSocket close timed out", self.device_id
                    )
                self._ws = None

            # Connect
            ws_client = TrestleWsClient()
            await ws_client.connect(self.host, self.port)
            self._ws = ws_client

            _LOGGER.info("[%s] WebSocket connected, starting listener", self.device_id)

            # Start listener task
            self._listen_task = asyncio.create_task(self._listen())
            self._retry_attempts = 0
            return True

        except TrestleTimeout:
            _LOGGER.warning(
                "[%s] Connection timeout - device unreachable", self.device_id
            )
            self._set_state("failed")
            self._handle_connection_failure()
            return False
        except TrestleConnectionError as err:
            _LOGGER.warning("[%s] Connection failed: %s", self.device_id, err)
            self._set_state("failed")
            self._handle_connection_failure()
            return False
        except TrestleHandshakeError as err:
            _LOGGER.error("[%s] WebSocket handshake failed: %s", self.device_id, err)
            self._set_state("failed")
            self._handle_connection_failure()
            return False

    async def close(self) -> None:
        """Gracefully close session."""
        _LOGGER.info("[%s] Closing session", self.device_id)
        self._shutdown_requested = True

        # Cancel tasks
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except Exception:  # Task cancellation can raise various exceptions
                pass

        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except Exception:  # Task cancellation can raise various exceptions
                pass

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except Exception:  # Task cancellation can raise various exceptions
                pass

        # Cancel batch timer
        if self._batch_timer:
            self._batch_timer.cancel()
            self._batch_timer = None

        # Close WebSocket
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=2.0)
            except TimeoutError:
                _LOGGER.warning("[%s] WebSocket close timed out", self.device_id)
            self._ws = None

        self._set_state("disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if session is connected and authenticated."""
        return self._connection_state == "authenticated"

    @property
    def connection_state(self) -> str:
        """Get current connection state."""
        return self._connection_state

    # -------------------------------------------------------------------------
    # Public API: Callbacks
    # -------------------------------------------------------------------------

    def on_input_event(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register callback for device input events.

        Callback receives: {
            "target_widget_binding": "binding_id",
            "action": "toggle",
            "value": ...
        }
        """
        self._input_event_callback = callback

    def on_state_request(self, callback: Callable[[str], Any]) -> None:
        """Register callback for device state requests.

        Callback receives binding_id, returns current value.
        """
        self._state_request_callback = callback

    def on_connection_state_changed(self, callback: Callable[[str], None]) -> None:
        """Register callback for connection state changes.

        Callback receives state: "connecting", "authenticating", "authenticated", "failed", "disconnected"
        """
        self._connection_state_callback = callback

    def on_auth_failed(self, callback: Callable[[], Awaitable[None] | None]) -> None:
        """Register callback for authentication failures (trigger reauth flow)."""
        self._auth_failed_callback = callback

    def on_device_state_update(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Register callback for device state updates (telemetry, component states)."""
        self._device_state_callback = callback

    # -------------------------------------------------------------------------
    # Public API: State Updates
    # -------------------------------------------------------------------------

    def schedule_state_update(self, binding_id: str, value: Any) -> None:
        """Schedule state update for batching.

        Updates are coalesced and sent as snapshot or delta based on connection state.

        Args:
            binding_id: Binding identifier
            value: Canonical value (ecosystem-agnostic)
        """
        self._pending_batch[binding_id] = value

        if self._batch_timer is not None:
            self._batch_timer.cancel()

        if self._loop:
            self._batch_timer = self._loop.call_later(
                self._batch_interval,
                lambda: asyncio.create_task(self._flush_pending_batch()),
            )

    async def send_immediate_update(self, binding_id: str, value: Any) -> bool:
        """Send immediate state update without batching.

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_connected or not self._layout_applied:
            return False

        if self._current_layout_id is None:
            return False

        changes = [{"binding_id": binding_id, "state": value}]

        if self._snapshot_sent:
            return await self._send_delta(changes)
        else:
            # First update after layout - send snapshot
            return await self._send_snapshot(self._get_all_states())

    # -------------------------------------------------------------------------
    # Public API: Layout Management
    # -------------------------------------------------------------------------

    async def send_layout(self, layout_package: dict[str, Any]) -> bool:
        """Send layout to device.

        Args:
            layout_package: Layout package with layout_id and layout object

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_connected:
            _LOGGER.error("[%s] Cannot send layout: not authenticated", self.device_id)
            return False

        layout_id = layout_package.get("layout_id")
        if not layout_id or not layout_id.startswith("sha256:"):
            _LOGGER.error("[%s] Invalid layout_id: %s", self.device_id, layout_id)
            return False

        if self._ws is None:
            return False

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="layout",
            body=layout_package,
        )

        try:
            await self._ws.send_json(frame)
            self._current_layout_id = layout_id
            _LOGGER.info("[%s] Layout sent: %s", self.device_id, layout_id[:20])
            return True
        except TrestleClientError as err:
            _LOGGER.error("[%s] Failed to send layout: %s", self.device_id, err)
            return False

    async def send_capabilities(self, capabilities: dict[str, Any]) -> bool:
        """Send capabilities to device.

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_connected or self._ws is None:
            return False

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="capabilities",
            body=capabilities,
        )

        try:
            await self._ws.send_json(frame)
            _LOGGER.debug("[%s] Capabilities sent", self.device_id)
            return True
        except TrestleClientError as err:
            _LOGGER.error("[%s] Failed to send capabilities: %s", self.device_id, err)
            return False

    async def send_time(self) -> bool:
        """Send time update to device.

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_connected or self._ws is None:
            return False

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="time",
            body=build_time_body(now=datetime.now(tz=UTC)),
        )

        try:
            await self._ws.send_json(frame)
            _LOGGER.debug("[%s] Time sent", self.device_id)
            return True
        except TrestleClientError as err:
            _LOGGER.error("[%s] Failed to send time: %s", self.device_id, err)
            return False

    # -------------------------------------------------------------------------
    # Internal: Connection State Machine
    # -------------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        """Update connection state and notify callback."""
        if self._connection_state != state:
            _LOGGER.debug(
                "[%s] State: %s → %s", self.device_id, self._connection_state, state
            )
            self._connection_state = state
            if self._connection_state_callback:
                self._connection_state_callback(state)

    def _handle_connection_failure(self) -> None:
        """Schedule reconnection attempt with exponential backoff."""
        if self._shutdown_requested or self._reconnect_task:
            return

        delay = min(
            self._retry_base_delay * (2**self._retry_attempts),
            self._retry_max_delay,
        )
        self._retry_attempts += 1

        _LOGGER.info(
            "[%s] Reconnecting in %ds (attempt %d)",
            self.device_id,
            delay,
            self._retry_attempts,
        )

        self._reconnect_task = asyncio.create_task(self._reconnect_after_delay(delay))

    async def _reconnect_after_delay(self, delay: float) -> None:
        """Reconnect after delay."""
        try:
            await asyncio.sleep(delay)
            await self.connect()
        except asyncio.CancelledError:
            _LOGGER.debug("[%s] Reconnect cancelled", self.device_id)
        finally:
            self._reconnect_task = None

    # -------------------------------------------------------------------------
    # Internal: Message Listener
    # -------------------------------------------------------------------------

    async def _listen(self) -> None:
        """Listen for messages from device."""
        if self._ws is None:
            return

        message_count = 0
        reconnect_required = False

        # Send auth immediately after connection
        await self._send_auth()

        try:
            async for msg in self._ws:
                message_count += 1

                if msg.type == TrestleWsMessageType.TEXT:
                    try:
                        data = msg.data if isinstance(msg.data, dict) else {}
                        msg_type = data.get("type")

                        if msg_type == "auth_ok":
                            await self._handle_auth_ok(data)
                        elif msg_type == "auth_invalid":
                            _LOGGER.error(
                                "[%s] Authentication rejected", self.device_id
                            )
                            self._set_state("failed")
                            if self._auth_failed_callback:
                                result = self._auth_failed_callback()
                                if inspect.iscoroutine(result):
                                    await result
                            return
                        elif msg_type == "layout_applied":
                            await self._handle_layout_applied(data)
                        elif msg_type == "input_event":
                            await self._handle_input_event(data)
                        elif msg_type == "delta_ack":
                            self._handle_delta_ack(data)
                        elif msg_type == "state_request":
                            await self._handle_state_request(data)
                        elif msg_type == "pong":
                            self._handle_pong(data)
                        elif msg_type == "state_update":
                            self._handle_device_state_update(data)
                        else:
                            _LOGGER.debug(
                                "[%s] Unknown message type: %s",
                                self.device_id,
                                msg_type,
                            )

                    except (ValueError, KeyError) as err:
                        _LOGGER.warning("[%s] Invalid message: %s", self.device_id, err)

                elif msg.type == TrestleWsMessageType.CLOSED:
                    _LOGGER.info("[%s] WebSocket closed by device", self.device_id)
                    reconnect_required = True
                    break

                elif msg.type == TrestleWsMessageType.ERROR:
                    _LOGGER.error("[%s] WebSocket error", self.device_id)
                    reconnect_required = True
                    break

        except asyncio.CancelledError:
            _LOGGER.debug(
                "[%s] Listener cancelled (%d messages)", self.device_id, message_count
            )
            raise
        except TrestleClientError as err:
            _LOGGER.warning("[%s] Client error: %s", self.device_id, err)
            reconnect_required = True
        except Exception as err:
            _LOGGER.exception("[%s] Unexpected error: %s", self.device_id, err)
            reconnect_required = True
        finally:
            if reconnect_required and not self._shutdown_requested:
                self._set_state("failed")
                self._handle_connection_failure()

    # -------------------------------------------------------------------------
    # Internal: Protocol Handlers
    # -------------------------------------------------------------------------

    async def _send_auth(self) -> None:
        """Send authentication message."""
        if self._ws is None:
            return

        self._set_state("authenticating")

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="auth",
            body={
                "secret": self.token,
                "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
            },
        )

        await self._ws.send_json(frame)
        _LOGGER.debug("[%s] Auth sent", self.device_id)

    async def _handle_auth_ok(self, data: dict[str, Any]) -> None:
        """Handle auth_ok response."""
        auth_data = parse_auth_ok(data)
        self._device_protocol_versions = auth_data
        self._capabilities = data.get("capabilities", {})

        self._protocol_version = 1  # Use v1 for now

        # Send auth_confirmed
        frame = build_auth_confirmed(
            device_id=self.device_id,
        )
        await self._ws.send_json(frame) if self._ws else None

        self._set_state("authenticated")
        _LOGGER.info(
            "[%s] Authenticated (protocol v%d)", self.device_id, self._protocol_version
        )

        # Start keepalive
        if self._ping_task is None:
            self._ping_task = asyncio.create_task(self._keepalive_loop())

    async def _handle_layout_applied(self, data: dict[str, Any]) -> None:
        """Handle layout_applied acknowledgement."""
        layout_id = data.get("body", {}).get("layout_id")
        if layout_id == self._current_layout_id:
            self._layout_applied = True
            self._snapshot_sent = False
            _LOGGER.info("[%s] Layout applied: %s", self.device_id, layout_id[:20])

    async def _handle_input_event(self, data: dict[str, Any]) -> None:
        """Handle input event from device."""
        if self._input_event_callback:
            try:
                self._input_event_callback(data.get("body", {}))
            except Exception as err:
                _LOGGER.exception(
                    "[%s] Input event callback error: %s", self.device_id, err
                )

    async def _handle_state_request(self, data: dict[str, Any]) -> None:
        """Handle state request from device."""
        binding_ids = data.get("body", {}).get("binding_ids", [])

        if not self._state_request_callback:
            _LOGGER.warning("[%s] No state request callback registered", self.device_id)
            return

        # Build state response
        states: list[dict[str, Any]] = []
        for binding_id in binding_ids:
            try:
                value = self._state_request_callback(binding_id)
                states.append({"binding_id": binding_id, "state": value})
            except Exception as err:
                _LOGGER.error(
                    "[%s] State request callback error for %s: %s",
                    self.device_id,
                    binding_id,
                    err,
                )

        # Send snapshot with requested states
        if states:
            await self._send_snapshot(states)

    def _handle_delta_ack(self, data: dict[str, Any]) -> None:
        """Handle delta acknowledgement."""
        msg_id = data.get("body", {}).get("msg_id")
        if msg_id and msg_id in self._pending_delta_acks:
            ack = self._pending_delta_acks.pop(msg_id)
            latency = time.time() - ack.sent_at
            _LOGGER.debug(
                "[%s] Delta ack seq=%d (%.2fs)", self.device_id, ack.seq, latency
            )

    def _handle_pong(self, data: dict[str, Any]) -> None:
        """Handle pong response."""
        ping_id = data.get("body", {}).get("id")
        if ping_id and ping_id in self._pending_pings:
            sent_at = self._pending_pings.pop(ping_id)
            latency = time.time() - sent_at
            self._last_pong_time = time.time()
            self._missed_pong_windows = 0
            _LOGGER.debug("[%s] Pong id=%d (%.2fs)", self.device_id, ping_id, latency)

    def _handle_device_state_update(self, data: dict[str, Any]) -> None:
        """Handle device state update (telemetry)."""
        if self._device_state_callback:
            try:
                self._device_state_callback(data.get("body", {}))
            except Exception as err:
                _LOGGER.exception(
                    "[%s] Device state callback error: %s", self.device_id, err
                )

    # -------------------------------------------------------------------------
    # Internal: Batching
    # -------------------------------------------------------------------------

    async def _flush_pending_batch(self) -> None:
        """Flush pending batch as snapshot or delta."""
        if not self._pending_batch:
            return

        if self._batch_timer:
            self._batch_timer.cancel()
            self._batch_timer = None

        if not self.is_connected or not self._layout_applied:
            _LOGGER.debug("[%s] Batch skipped: not ready", self.device_id)
            return

        changes = [
            {"binding_id": k, "state": v} for k, v in self._pending_batch.items()
        ]
        self._pending_batch.clear()

        if self._snapshot_sent:
            await self._send_delta(changes)
        else:
            await self._send_snapshot(self._get_all_states())

    def _get_all_states(self) -> list[dict[str, Any]]:
        """Get all current states for snapshot.

        Note: This requires state_request_callback to be registered.
        """
        if not self._state_request_callback:
            return []

        # Get states from pending batch (most recent)
        states = [{"binding_id": k, "state": v} for k, v in self._pending_batch.items()]

        return states

    async def _send_snapshot(self, states: list[dict[str, Any]]) -> bool:
        """Send snapshot message."""
        if not self._current_layout_id or not self._ws:
            return False

        self._last_snapshot_states = states

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="snapshot",
            body={"layout_id": self._current_layout_id, "states": states},
        )

        try:
            await self._ws.send_json(frame)
            self._snapshot_sent = True
            _LOGGER.debug("[%s] Snapshot: %d states", self.device_id, len(states))
            return True
        except TrestleClientError as err:
            _LOGGER.error("[%s] Failed to send snapshot: %s", self.device_id, err)
            return False

    async def _send_delta(self, changes: list[dict[str, Any]]) -> bool:
        """Send delta message with sequence tracking."""
        if not self._current_layout_id or not self._ws:
            return False

        if len(self._pending_delta_acks) >= MAX_PENDING_DELTA_ACKS:
            _LOGGER.warning(
                "[%s] Delta blocked: %d pending acks",
                self.device_id,
                len(self._pending_delta_acks),
            )
            return False

        self._delta_seq += 1
        seq = self._delta_seq
        msg_id = str(uuid4())

        self._pending_delta_acks[msg_id] = _PendingDeltaAck(
            seq=seq, sent_at=time.time()
        )

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="delta",
            body={
                "layout_id": self._current_layout_id,
                "seq": seq,
                "msg_id": msg_id,
                "changes": changes,
            },
        )

        try:
            await self._ws.send_json(frame)
            _LOGGER.debug(
                "[%s] Delta seq=%d: %d changes", self.device_id, seq, len(changes)
            )
            return True
        except TrestleClientError as err:
            _LOGGER.error("[%s] Failed to send delta: %s", self.device_id, err)
            return False

    # -------------------------------------------------------------------------
    # Internal: Keepalive
    # -------------------------------------------------------------------------

    async def _keepalive_loop(self) -> None:
        """Keepalive loop - send periodic pings."""
        try:
            while not self._shutdown_requested:
                await asyncio.sleep(self._ping_interval)
                await self._send_ping()

                # Check for missed pongs
                if self._last_pong_time is not None:
                    since_pong = time.time() - self._last_pong_time
                    if since_pong > self._ping_interval + self._ping_timeout:
                        self._missed_pong_windows += 1
                        _LOGGER.warning(
                            "[%s] Missed pong (%.1fs since last, %d windows)",
                            self.device_id,
                            since_pong,
                            self._missed_pong_windows,
                        )

                        if self._missed_pong_windows >= 3:
                            _LOGGER.error(
                                "[%s] Connection dead (3 missed pongs)", self.device_id
                            )
                            if self._ws:
                                await self._ws.close()
                            break

        except asyncio.CancelledError:
            _LOGGER.debug("[%s] Keepalive cancelled", self.device_id)
        except Exception as err:
            _LOGGER.exception("[%s] Keepalive error: %s", self.device_id, err)

    async def _send_ping(self) -> bool:
        """Send ping message."""
        if self._ws is None:
            return False

        self._ping_id += 1
        ping_id = self._ping_id
        self._pending_pings[ping_id] = time.time()

        frame = build_envelope(
            device_id=self.device_id,
            msg_type="ping",
            body={"id": ping_id},
        )

        try:
            await self._ws.send_json(frame)
            return True
        except TrestleClientError:
            return False

    # -------------------------------------------------------------------------
    # Protocol Buffer Support (NEW)
    # -------------------------------------------------------------------------

    async def send_protobuf_message(self, message: Any) -> bool:
        """Send protobuf message as binary WebSocket frame.

        Args:
            message: Protobuf Message object

        Returns:
            True if sent successfully

        Note: Requires PROTOBUF_AVAILABLE to be True
        """
        if not protobuf_available:
            _LOGGER.error("Protobuf not available, cannot send protobuf message")
            return False

        if not self._ws or not self.is_connected:
            _LOGGER.warning("[%s] Cannot send protobuf: not connected", self.device_id)
            return False

        try:
            # Import available at runtime, checked by protobuf_available guard
            if not protobuf_util:
                _LOGGER.error("Protobuf module not available")
                return False
            # Serialize message to bytes
            data = protobuf_util.serialize_message(message)

            # Send as binary WebSocket frame
            await self._ws.send_bytes(data)

            msg_type = protobuf_util.get_message_type(message)
            _LOGGER.debug(
                "[%s] Sent protobuf message: %s (%d bytes)",
                self.device_id,
                msg_type,
                len(data),
            )
            return True

        except Exception as err:
            _LOGGER.error(
                "[%s] Failed to send protobuf message: %s",
                self.device_id,
                err,
            )
            return False

    async def send_protobuf_snapshot(
        self,
        profile_id: str,
        profile_version: str,
        fused_facts: dict[str, list[dict[str, Any]]],
        binding_states: list[dict[str, Any]],
    ) -> bool:
        """Send snapshot using protobuf format.

        Args:
            profile_id: Active profile identifier
            profile_version: Profile version
            fused_facts: Map of domain -> facts list
            binding_states: List of binding states

        Returns:
            True if sent successfully
        """
        if not protobuf_available or not protobuf_util:
            return False

        self._delta_seq += 1

        message = protobuf_util.build_snapshot_message(
            profile_id=profile_id,
            profile_version=profile_version,
            fused_facts=fused_facts,
            binding_states=binding_states,
            sequence_number=self._delta_seq,
        )

        result = await self.send_protobuf_message(message)
        if result:
            self._snapshot_sent = True

        return result
