"""Transport layer for Trestle coordinator.

This package contains all IO, wire protocol, and network handling.

Components:
- http: HTTP client for REST API calls
- ws: WebSocket connection management
- ws_client: WebSocket message iteration
- session: Session state management
- protocol: Envelope and auth message builders
- protobuf_util: Protobuf serialization helpers
"""

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

__all__ = [
    "TrestleHttpClient",
    "TrestleSession",
    "TrestleWsClient",
    "TrestleWsMessage",
    "TrestleWsMessageType",
    "build_auth_confirmed",
    "build_auth_invalid",
    "build_auth_ok",
    "build_envelope",
    "build_time_body",
    "connect_websocket",
    "parse_auth_ok",
]
