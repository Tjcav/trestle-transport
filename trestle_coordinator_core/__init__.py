"""Core shared helpers for Trestle coordinators.

Owned by the Trestle Coordinator Core team.
"""

from .errors import (
    TrestleClientError,
    TrestleConnectionError,
    TrestleHandshakeError,
    TrestleResponseError,
    TrestleTimeout,
)
from .http import TrestleHttpClient
from .protocol import build_envelope, build_time_body, parse_auth_ok
from .ws import connect_websocket
from .ws_client import TrestleWsClient, TrestleWsMessage, TrestleWsMessageType

SUPPORTED_PROTOCOL_VERSIONS: tuple[int, ...] = (1,)

__all__ = [
    "SUPPORTED_PROTOCOL_VERSIONS",
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
    "build_time_body",
    "parse_auth_ok",
    "connect_websocket",
]
