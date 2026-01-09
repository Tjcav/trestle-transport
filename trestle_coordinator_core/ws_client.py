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
                if isinstance(msg, str):
                    yield TrestleWsMessage(
                        type=TrestleWsMessageType.TEXT,
                        data=msg,
                    )
                    continue

                if isinstance(msg, bytes):
                    continue

                # Extract frame type and data from non-string/bytes messages (e.g., aiohttp WSMessage)
                frame_type = getattr(msg, "type", None)
                frame_data = getattr(msg, "data", None)

                # Lazy import to avoid hard dependency on aiohttp at runtime
                try:
                    from aiohttp import WSMsgType
                except Exception:  # pragma: no cover - fallback when aiohttp missing
                    WSMsgType = None

                if WSMsgType is not None and frame_type == WSMsgType.TEXT:
                    yield TrestleWsMessage(
                        type=TrestleWsMessageType.TEXT,
                        data=frame_data,
                    )
                    continue

                if WSMsgType is not None and frame_type in {
                    WSMsgType.CLOSED,
                    WSMsgType.CLOSE,
                }:
                    yield TrestleWsMessage(type=TrestleWsMessageType.CLOSED)
                    continue

                if WSMsgType is not None and frame_type == WSMsgType.ERROR:
                    yield TrestleWsMessage(type=TrestleWsMessageType.ERROR)
                    continue
        except ConnectionClosed:
            yield TrestleWsMessage(type=TrestleWsMessageType.CLOSED)
        except Exception:
            yield TrestleWsMessage(type=TrestleWsMessageType.ERROR)

    @staticmethod
    def decode_json(message: TrestleWsMessage) -> dict[str, Any]:
        """Decode a TEXT message payload into JSON."""
        if message.type is not TrestleWsMessageType.TEXT:
            raise TrestleClientError("Only TEXT messages can be decoded")
        if isinstance(message.data, dict):
            return message.data
        if not isinstance(message.data, str):
            raise ValueError("WebSocket message payload is not text")
        result: dict[str, Any] = json.loads(message.data)
        return result
