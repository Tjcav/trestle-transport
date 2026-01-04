"""Trestle transport adapter package."""

from .errors import (
    TrestleClientError,
    TrestleConnectionError,
    TrestleHandshakeError,
    TrestleResponseError,
    TrestleTimeout,
)
from .http import TrestleHttpClient
from .protocol import build_envelope
from .ws import connect_websocket
from .ws_client import TrestleWsClient, TrestleWsMessage, TrestleWsMessageType

__all__ = [
    "TrestleClientError",
    "TrestleConnectionError",
    "TrestleHandshakeError",
    "TrestleHttpClient",
    "TrestleResponseError",
    "TrestleTimeout",
    "TrestleWsClient",
    "TrestleWsMessage",
    "TrestleWsMessageType",
    "build_envelope",
    "connect_websocket",
]
