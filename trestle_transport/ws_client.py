"""WebSocket client wrapper for Rocky Panel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import aiohttp

from .errors import RockyPanelClientError, RockyPanelConnectionError
from .ws import connect_websocket

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class RockyPanelWsMessageType(Enum):
    """Normalized WebSocket message types."""

    TEXT = "text"
    CLOSED = "closed"
    ERROR = "error"


@dataclass(frozen=True)
class RockyPanelWsMessage:
    """Normalized WebSocket message payload."""

    type: RockyPanelWsMessageType
    data: str | dict[str, Any] | None = None


class RockyPanelWsClient:
    """Wrapper around aiohttp websocket for Rocky Panel."""

    def __init__(self) -> None:
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def connect(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        *,
        heartbeat: int = 30,
        timeout: float = 15.0,
    ) -> None:
        """Connect to the device websocket."""
        self._ws = await connect_websocket(
            session,
            host,
            port,
            heartbeat=heartbeat,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the websocket connection."""
        if self._ws is not None:
            await self._ws.close()

    async def send_json(self, payload: dict[str, Any]) -> None:
        """Send a JSON payload to the websocket."""
        if self._ws is None:
            raise RockyPanelConnectionError("WebSocket is not connected")
        await self._ws.send_json(payload)

    def __aiter__(self) -> AsyncIterator[RockyPanelWsMessage]:
        if self._ws is None:
            raise RockyPanelConnectionError("WebSocket is not connected")
        return self._iter_messages()

    async def _iter_messages(self) -> AsyncIterator[RockyPanelWsMessage]:
        if self._ws is None:
            raise RockyPanelConnectionError("WebSocket is not connected")

        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                yield RockyPanelWsMessage(
                    type=RockyPanelWsMessageType.TEXT,
                    data=msg.data,
                )
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                yield RockyPanelWsMessage(type=RockyPanelWsMessageType.CLOSED)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                yield RockyPanelWsMessage(type=RockyPanelWsMessageType.ERROR)
            else:
                continue

    @staticmethod
    def decode_json(message: RockyPanelWsMessage) -> dict[str, Any]:
        """Decode a TEXT message payload into JSON."""
        if message.type is not RockyPanelWsMessageType.TEXT:
            raise RockyPanelClientError("Only TEXT messages can be decoded")
        if isinstance(message.data, dict):
            return message.data
        if not isinstance(message.data, str):
            raise ValueError("WebSocket message payload is not text")
        return json.loads(message.data)
