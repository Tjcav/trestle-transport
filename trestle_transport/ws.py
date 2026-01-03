"""WebSocket helpers for Rocky Panel device transport."""

from __future__ import annotations

import asyncio

import aiohttp

from .errors import (
    RockyPanelConnectionError,
    RockyPanelHandshakeError,
    RockyPanelTimeout,
)


async def connect_websocket(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    *,
    heartbeat: int = 30,
    timeout: float = 15.0,
) -> aiohttp.ClientWebSocketResponse:
    """Connect to the Rocky Panel WebSocket endpoint."""
    ws_url = f"ws://{host}:{port}/ws"
    try:
        return await asyncio.wait_for(
            session.ws_connect(
                ws_url,
                heartbeat=heartbeat,
                compress=0,
                max_msg_size=0,
            ),
            timeout=timeout,
        )
    except TimeoutError as err:
        raise RockyPanelTimeout("WebSocket connection timed out") from err
    except aiohttp.WSServerHandshakeError as err:
        raise RockyPanelHandshakeError("WebSocket handshake failed") from err
    except aiohttp.ClientConnectorError as err:
        raise RockyPanelConnectionError("WebSocket connection failed") from err
