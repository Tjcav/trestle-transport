"""Trestle transport adapter package."""

from .errors import (
    RockyPanelClientError,
    RockyPanelConnectionError,
    RockyPanelHandshakeError,
    RockyPanelResponseError,
    RockyPanelTimeout,
)
from .http import RockyPanelHttpClient
from .protocol import build_envelope
from .ws import connect_websocket
from .ws_client import RockyPanelWsClient, RockyPanelWsMessage, RockyPanelWsMessageType

__all__ = [
    "RockyPanelClientError",
    "RockyPanelConnectionError",
    "RockyPanelHandshakeError",
    "RockyPanelHttpClient",
    "RockyPanelResponseError",
    "RockyPanelTimeout",
    "RockyPanelWsClient",
    "RockyPanelWsMessage",
    "RockyPanelWsMessageType",
    "build_envelope",
    "connect_websocket",
]
