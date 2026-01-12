"""WebSocket helpers for RockBridge Trestle device transport."""

from __future__ import annotations

import asyncio

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import (
    InvalidHandshake,
    InvalidURI,
    WebSocketException,
)

from ..errors import (
    TrestleConnectionError,
    TrestleHandshakeError,
    TrestleTimeout,
)


async def connect_websocket(
    host: str,
    port: int,
    *,
    path: str = "/ws",
    ping_interval: int | None = 20,
    timeout: float = 15.0,
) -> ClientConnection:
    """Connect to a WebSocket endpoint.

    Uses the websockets library which properly implements RFC 6455 frame masking.
    All client-to-server frames are automatically masked per the standard.

    Args:
        host: Target host
        port: Target port
        path: WebSocket path (default: /ws)
        ping_interval: Interval for ping frames
        timeout: Connection timeout
    """
    ws_url = f"ws://{host}:{port}{path}"
    try:
        return await asyncio.wait_for(
            websockets.connect(
                ws_url,
                ping_interval=ping_interval,
                close_timeout=5,
                max_size=None,
            ),
            timeout=timeout,
        )
    except TimeoutError as err:
        raise TrestleTimeout("WebSocket connection timed out") from err
    except (InvalidHandshake, InvalidURI) as err:
        raise TrestleHandshakeError("WebSocket handshake failed") from err
    except (OSError, WebSocketException) as err:
        raise TrestleConnectionError("WebSocket connection failed") from err
