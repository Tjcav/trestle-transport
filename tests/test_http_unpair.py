"""Test unpair_device() method per ICD Section 3.2."""

from __future__ import annotations

from unittest.mock import MagicMock

import aiohttp
import pytest

from trestle_coordinator_core import TrestleHttpClient
from trestle_coordinator_core.errors import (
    TrestleConnectionError,
    TrestleResponseError,
    TrestleTimeout,
)

from .conftest import create_mock_response


class TestUnpairDevice:
    """Test ICD 3.2 compliance: unauthenticated /api/unpair endpoint."""

    async def test_unpair_success(self, mock_session: MagicMock) -> None:
        """Test successful unpair request returns without error."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        # Device returns 200 OK per ICD 3.2.1
        mock_response = create_mock_response(status=200, text_data="OK")
        mock_session.post.return_value = mock_response

        # Should complete without raising
        await client.unpair_device()

        # Verify POST to /api/unpair
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert call_args.args[0] == "http://192.168.1.100:8080/api/unpair"

    async def test_unpair_no_auth_header(self, mock_session: MagicMock) -> None:
        """Test unpair sends no authentication header per ICD 3.2."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        mock_response = create_mock_response(status=200)
        mock_session.post.return_value = mock_response

        await client.unpair_device()

        # Verify no Authorization header sent
        call_kwargs = mock_session.post.call_args.kwargs
        # Should not have headers key or should be empty
        headers = call_kwargs.get("headers", {})
        assert "Authorization" not in headers

    async def test_unpair_non_200_raises_response_error(
        self, mock_session: MagicMock
    ) -> None:
        """Test non-200 response raises TrestleResponseError per strict ICD compliance."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        # Device returns error status
        mock_response = create_mock_response(status=500)
        mock_session.post.return_value = mock_response

        with pytest.raises(
            TrestleResponseError,
            match=r"Unpair failed - device must return 200 OK per ICD 3\.2",
        ):
            await client.unpair_device()

    async def test_unpair_404_raises_response_error(
        self, mock_session: MagicMock
    ) -> None:
        """Test 404 (endpoint not implemented) raises error - no backward compatibility."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        mock_response = create_mock_response(status=404)
        mock_session.post.return_value = mock_response

        # Should raise, not gracefully handle
        with pytest.raises(TrestleResponseError):
            await client.unpair_device()

    async def test_unpair_timeout_raises_trestle_timeout(
        self, mock_session: MagicMock
    ) -> None:
        """Test timeout raises TrestleTimeout."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        mock_session.post.side_effect = TimeoutError("Request timed out")

        with pytest.raises(TrestleTimeout, match="Unpair request timed out"):
            await client.unpair_device()

    async def test_unpair_client_error_raises_connection_error(
        self, mock_session: MagicMock
    ) -> None:
        """Test aiohttp ClientError raises TrestleConnectionError."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        mock_session.post.side_effect = aiohttp.ClientError("Connection refused")

        with pytest.raises(TrestleConnectionError, match="Unpair request failed"):
            await client.unpair_device()

    async def test_unpair_uses_10_second_timeout(self, mock_session: MagicMock) -> None:
        """Test unpair request uses 10 second timeout."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="test-secret",
        )

        mock_response = create_mock_response(status=200)
        mock_session.post.return_value = mock_response

        await client.unpair_device()

        # Verify timeout parameter
        call_kwargs = mock_session.post.call_args.kwargs
        timeout = call_kwargs.get("timeout")
        assert timeout is not None
        assert timeout.total == 10
