"""Pytest configuration and fixtures for trestle_coordinator_core tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_session() -> MagicMock:
    """Create a mock aiohttp ClientSession."""
    import aiohttp

    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def mock_response() -> AsyncMock:
    """Create a mock aiohttp ClientResponse."""
    response = AsyncMock()
    response.__aenter__.return_value = response
    response.__aexit__.return_value = None
    return response


def create_mock_response(
    status: int = 200,
    json_data: dict[str, Any] | None = None,
    text_data: str | None = None,
    read_data: bytes | None = None,
) -> AsyncMock:
    """Create a configured mock response.

    Args:
        status: HTTP status code
        json_data: Data to return from json() call
        text_data: Data to return from text() call
        read_data: Data to return from read() call

    Returns:
        Configured AsyncMock response
    """
    response = AsyncMock()
    response.status = status

    if json_data is not None:
        response.json.return_value = json_data
    if text_data is not None:
        response.text.return_value = text_data
    if read_data is not None:
        response.read.return_value = read_data

    response.__aenter__.return_value = response
    response.__aexit__.return_value = None

    return response
