"""Client error types for Rocky Panel device interactions."""

from __future__ import annotations


class RockyPanelClientError(Exception):
    """Base error for Rocky Panel client failures."""


class RockyPanelTimeout(RockyPanelClientError):
    """Timeout while communicating with the device."""


class RockyPanelConnectionError(RockyPanelClientError):
    """Network connection to the device failed."""


class RockyPanelHandshakeError(RockyPanelClientError):
    """WebSocket handshake failed."""


class RockyPanelResponseError(RockyPanelClientError):
    """HTTP response error from the device."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
