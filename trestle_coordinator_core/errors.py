"""Client error types for RockBridge Trestle device interactions.

Owned by the Trestle Coordinator Core team.
"""

from __future__ import annotations


class TrestleClientError(Exception):
    """Base error for RockBridge Trestle client failures."""


class TrestleTimeout(TrestleClientError):
    """Timeout while communicating with the device."""


class TrestleConnectionError(TrestleClientError):
    """Network connection to the device failed."""


class TrestleHandshakeError(TrestleClientError):
    """WebSocket handshake failed."""


class TrestleResponseError(TrestleClientError):
    """HTTP response error from the device."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
