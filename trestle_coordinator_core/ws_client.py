"""WebSocket client wrapper for RockBridge Trestle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from .errors import TrestleClientError, TrestleConnectionError
from .ws import connect_websocket

try:  # pragma: no cover - optional dependency for normalization
    from aiohttp import WSMsgType
except ImportError:  # pragma: no cover
    WSMsgType = None

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class TrestleWsMessageType(Enum):
    """Normalized WebSocket message types."""

    TEXT = "text"
    CLOSED = "closed"
    ERROR = "error"


@dataclass(frozen=True)
class TrestleWsMessage:
    """Normalized WebSocket message payload."""

    type: TrestleWsMessageType
    data: str | dict[str, Any] | None = None


class TrestleWsClient:
    """Wrapper around websockets library for RockBridge Trestle."""

    def __init__(self) -> None:
        self._ws: ClientConnection | None = None

    async def connect(
        self,
        host: str,
        port: int,
        *,
        ping_interval: int = 20,
        timeout: float = 15.0,
    ) -> None:
        """Connect to the device websocket."""
        self._ws = await connect_websocket(
            host,
            port,
            ping_interval=ping_interval,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the websocket connection."""
        if self._ws is not None:
            await self._ws.close()

    async def send_json(self, payload: dict[str, Any]) -> None:
        """Send a JSON payload to the websocket."""
        if self._ws is None:
            raise TrestleConnectionError("WebSocket is not connected")
        await self._ws.send(json.dumps(payload))

    async def send_bytes(self, data: bytes) -> None:
        """Send binary data to the websocket.

        Args:
            data: Binary data to send

        Raises:
            TrestleConnectionError: If not connected
        """
        if self._ws is None:
            raise TrestleConnectionError("WebSocket is not connected")
        await self._ws.send(data)

    def __aiter__(self) -> AsyncIterator[TrestleWsMessage]:
        if self._ws is None:
            raise TrestleConnectionError("WebSocket is not connected")
        return self._iter_messages()

    async def _iter_messages(self) -> AsyncIterator[TrestleWsMessage]:
        if self._ws is None:
            raise TrestleConnectionError("WebSocket is not connected")

        try:
            async for msg in self._ws:
                normalized: TrestleWsMessage | None = self._normalize_message(msg)
                if normalized is None:
                    continue
                yield normalized
        except ConnectionClosed:
            yield TrestleWsMessage(type=TrestleWsMessageType.CLOSED)
        except Exception:
            yield TrestleWsMessage(type=TrestleWsMessageType.ERROR)
        else:
            # Normal iteration completion means the peer closed gracefully.
            yield TrestleWsMessage(type=TrestleWsMessageType.CLOSED)

    @staticmethod
    def _normalize_message(msg: Any) -> TrestleWsMessage | None:
        """Normalize backend-specific frames into TrestleWsMessage."""
        if isinstance(msg, bytes):
            return None
        if isinstance(msg, str):
            return TrestleWsMessage(TrestleWsMessageType.TEXT, msg)

        msg_type = getattr(msg, "type", None)
        data = getattr(msg, "data", None)

        if WSMsgType is not None and msg_type is not None:
            normalized_type: TrestleWsMessageType | None = (
                TrestleWsClient._map_aiohttp_type(msg_type)
            )
            if normalized_type is None:
                return None
            return TrestleWsMessage(normalized_type, data)

        # Fallback: treat unknown objects as text via their string repr
        return TrestleWsMessage(TrestleWsMessageType.TEXT, str(msg))

    @staticmethod
    def _map_aiohttp_type(msg_type: Any) -> TrestleWsMessageType | None:
        """Map aiohttp WSMsgType enums to internal message types."""
        if WSMsgType is None:
            return None

        if msg_type is WSMsgType.TEXT:
            return TrestleWsMessageType.TEXT

        if msg_type is WSMsgType.BINARY:
            return None

        if msg_type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
            return TrestleWsMessageType.CLOSED

        if msg_type is WSMsgType.ERROR:
            return TrestleWsMessageType.ERROR

        return None

    @staticmethod
    def decode_json(message: TrestleWsMessage) -> dict[str, Any]:
        """Decode a TEXT message payload into JSON."""
        if message.type is not TrestleWsMessageType.TEXT:
            raise TrestleClientError("Only TEXT messages can be decoded")
        if not isinstance(message.data, str):
            raise TrestleClientError("Message data is not a string")
        result: dict[str, Any] = json.loads(message.data)
        return result
