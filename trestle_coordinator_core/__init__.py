"""Core shared helpers for Trestle coordinators.

Owned by the Trestle Coordinator Core team.
"""

__version__ = "0.1.0"

from .errors import (
    TrestleClientError,
    TrestleConnectionError,
    TrestleHandshakeError,
    TrestleResponseError,
    TrestleTimeout,
)
from .http import TrestleHttpClient
from .protocol import (
    build_auth_confirmed,
    build_auth_invalid,
    build_auth_ok,
    build_envelope,
    build_time_body,
    parse_auth_ok,
)
from .session import TrestleSession
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
    "TrestleSession",
    "TrestleTimeout",
    "TrestleWsClient",
    "TrestleWsMessage",
    "TrestleWsMessageType",
    "__version__",
    "build_auth_confirmed",
    "build_auth_invalid",
    "build_auth_ok",
    "build_envelope",
    "build_time_body",
    "connect_websocket",
    "parse_auth_ok",
]
