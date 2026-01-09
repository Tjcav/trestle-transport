"""Test TrestleSession basic functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trestle_coordinator_core import TrestleSession


@pytest.fixture
def mock_ws_client():
    """Create a mock WebSocket client."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.send_json = AsyncMock()

    # Mock async iterator
    async def mock_iter():
        # Yield auth_ok message
        msg = MagicMock()
        msg.type = MagicMock()
        msg.type.__eq__ = lambda self, other: other == "TEXT"
        msg.json = MagicMock(
            return_value={
                "type": "auth_ok",
                "body": {"device_protocol_versions": [1], "capabilities": {}},
            }
        )
        yield msg

    client.__aiter__ = lambda self: mock_iter()
    return client


@pytest.mark.asyncio
async def test_session_creation():
    """Test TrestleSession can be created."""
    session = TrestleSession(
        device_id="test123",
        host="192.168.1.10",
        port=80,
        token="secret",
    )

    assert session.device_id == "test123"
    assert session.host == "192.168.1.10"
    assert session.port == 80
    assert session.connection_state == "disconnected"
    assert not session.is_connected


@pytest.mark.asyncio
async def test_session_connect(mock_ws_client):
    """Test session connection."""
    with patch(
        "trestle_coordinator_core.session.TrestleWsClient", return_value=mock_ws_client
    ):
        session = TrestleSession(
            device_id="test123",
            host="192.168.1.10",
            port=80,
            token="secret",
        )

        result = await session.connect()

        assert result is True
        assert mock_ws_client.connect.called


@pytest.mark.asyncio
async def test_session_callbacks():
    """Test session callback registration."""
    session = TrestleSession(
        device_id="test123",
        host="192.168.1.10",
        port=80,
        token="secret",
    )

    input_callback = MagicMock()
    state_callback = MagicMock()
    connection_callback = MagicMock()

    session.on_input_event(input_callback)
    session.on_state_request(state_callback)
    session.on_connection_state_changed(connection_callback)

    assert session._input_event_callback == input_callback
    assert session._state_request_callback == state_callback
    assert session._connection_state_callback == connection_callback


@pytest.mark.asyncio
async def test_session_state_update():
    """Test state update scheduling."""
    session = TrestleSession(
        device_id="test123",
        host="192.168.1.10",
        port=80,
        token="secret",
    )

    session.schedule_state_update("binding_1", "on")
    session.schedule_state_update("binding_2", "off")

    assert session._pending_batch == {"binding_1": "on", "binding_2": "off"}


@pytest.mark.asyncio
async def test_session_close():
    """Test session close."""
    session = TrestleSession(
        device_id="test123",
        host="192.168.1.10",
        port=80,
        token="secret",
    )

    await session.close()

    assert session._shutdown_requested is True
    assert session.connection_state == "disconnected"
