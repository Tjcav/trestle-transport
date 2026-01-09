"""Test orphan panel recovery per ICD Section 3.2."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from trestle_coordinator_core import TrestleHttpClient

from .conftest import create_mock_response


class TestOrphanPanelRecovery:
    """Test fetch_device_id() auto-recovery from orphan panel scenario (ICD 3.2)."""

    async def test_401_with_secret_triggers_unpair(
        self, mock_session: MagicMock
    ) -> None:
        """Test 401 response with stored secret triggers unpair call."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="stored-secret",
        )

        # First call with auth returns 401 (orphan scenario)
        response_401 = create_mock_response(status=401)

        # After unpair, second call returns device info
        response_unpair = create_mock_response(status=200, text_data="OK")
        response_success = create_mock_response(
            status=200, json_data={"id": "device-123"}
        )

        mock_session.get.side_effect = [response_401, response_success]
        mock_session.post.return_value = response_unpair

        device_id = await client.fetch_device_id()

        assert device_id == "device-123"

        # Verify unpair was called
        mock_session.post.assert_called_once()
        unpair_call = mock_session.post.call_args
        assert unpair_call.args[0] == "http://192.168.1.100:8080/api/unpair"

        # Verify two GET calls (with auth, then without)
        assert mock_session.get.call_count == 2

    async def test_401_recovery_retries_without_auth(
        self, mock_session: MagicMock
    ) -> None:
        """Test after unpair, retry uses no auth header."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="stored-secret",
        )

        response_401 = create_mock_response(status=401)
        response_unpair = create_mock_response(status=200)
        response_success = create_mock_response(
            status=200, json_data={"id": "device-123"}
        )

        mock_session.get.side_effect = [response_401, response_success]
        mock_session.post.return_value = response_unpair

        await client.fetch_device_id()

        # First call should have Bearer token
        first_call_kwargs = mock_session.get.call_args_list[0].kwargs
        assert first_call_kwargs["headers"] == {"Authorization": "Bearer stored-secret"}

        # Second call (after unpair) should have NO auth
        second_call_kwargs = mock_session.get.call_args_list[1].kwargs
        assert second_call_kwargs["headers"] == {}

    async def test_401_without_secret_no_unpair(self, mock_session: MagicMock) -> None:
        """Test 401 without stored secret does not trigger unpair."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret=None,  # No secret stored
        )

        response_401 = create_mock_response(status=401)
        mock_session.get.return_value = response_401

        device_id = await client.fetch_device_id()

        assert device_id is None

        # Should NOT call unpair (no secret to recover from)
        mock_session.post.assert_not_called()

        # Only one GET call
        assert mock_session.get.call_count == 1

    async def test_401_retry_disabled_no_unpair(self, mock_session: MagicMock) -> None:
        """Test retry_without_auth=False prevents unpair."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="stored-secret",
        )

        response_401 = create_mock_response(status=401)
        mock_session.get.return_value = response_401

        device_id = await client.fetch_device_id(retry_without_auth=False)

        assert device_id is None

        # Should NOT call unpair when retry disabled
        mock_session.post.assert_not_called()

        # Only one GET call
        assert mock_session.get.call_count == 1

    async def test_unpair_failure_propagates(self, mock_session: MagicMock) -> None:
        """Test unpair failure during recovery raises exception."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="stored-secret",
        )

        response_401 = create_mock_response(status=401)
        response_unpair_fail = create_mock_response(status=500)

        mock_session.get.return_value = response_401
        mock_session.post.return_value = response_unpair_fail

        # Unpair failure should propagate as TrestleResponseError
        from trestle_coordinator_core.errors import TrestleResponseError

        with pytest.raises(TrestleResponseError):
            await client.fetch_device_id()

    async def test_full_orphan_recovery_flow(self, mock_session: MagicMock) -> None:
        """Test complete orphan panel recovery scenario.

        Scenario:
        1. Coordinator has stored secret "old-secret"
        2. Device was factory reset (lost secret)
        3. Coordinator tries /api/info with auth → 401
        4. Coordinator calls /api/unpair to clear device state
        5. Coordinator retries /api/info without auth → 200 OK
        6. Recovery complete, coordinator can re-pair
        """
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="old-secret",
        )

        # Device rejects auth (orphan state)
        response_401 = create_mock_response(status=401)

        # Unpair succeeds
        response_unpair = create_mock_response(status=200, text_data="OK")

        # Device now accepts unauthenticated request
        response_unpaired = create_mock_response(
            status=200, json_data={"id": "device-abc", "name": "My Panel"}
        )

        mock_session.get.side_effect = [response_401, response_unpaired]
        mock_session.post.return_value = response_unpair

        device_id = await client.fetch_device_id()

        # Should successfully recover and get device ID
        assert device_id == "device-abc"

        # Verify the call sequence
        assert mock_session.get.call_count == 2
        assert mock_session.post.call_count == 1

        # Verify POST was to unpair endpoint
        unpair_call = mock_session.post.call_args
        assert "/api/unpair" in unpair_call.args[0]

    async def test_second_401_returns_none(self, mock_session: MagicMock) -> None:
        """Test second 401 after unpair returns None (doesn't retry again)."""
        client = TrestleHttpClient(
            host="192.168.1.100",
            port=8080,
            session=mock_session,
            secret="stored-secret",
        )

        # Both attempts return 401
        response_401_first = create_mock_response(status=401)
        response_401_second = create_mock_response(status=401)
        response_unpair = create_mock_response(status=200)

        mock_session.get.side_effect = [response_401_first, response_401_second]
        mock_session.post.return_value = response_unpair

        device_id = await client.fetch_device_id()

        # Should return None (not infinite loop)
        assert device_id is None

        # Should only call unpair once
        assert mock_session.post.call_count == 1

        # Two GET calls (initial with auth, retry without)
        assert mock_session.get.call_count == 2
