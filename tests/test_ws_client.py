"""Tests for TrestleWsClient WebSocket wrapper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import ConnectionClosed

from trestle_coordinator_core.errors import TrestleClientError, TrestleConnectionError
from trestle_coordinator_core.transport.ws_client import (
    TrestleWsClient,
    TrestleWsMessage,
    TrestleWsMessageType,
)


class TestTrestleWsMessageType:
    """Tests for TrestleWsMessageType enum."""

    def test_enum_values(self):
        """Test enum has expected values."""
        assert TrestleWsMessageType.TEXT.value == "text"
        assert TrestleWsMessageType.CLOSED.value == "closed"
        assert TrestleWsMessageType.ERROR.value == "error"


class TestTrestleWsMessage:
    """Tests for TrestleWsMessage dataclass."""

    def test_create_text_message(self):
        """Test creating a text message."""
        msg = TrestleWsMessage(type=TrestleWsMessageType.TEXT, data="hello")
        assert msg.type == TrestleWsMessageType.TEXT
        assert msg.data == "hello"

    def test_create_closed_message(self):
        """Test creating a closed message."""
        msg = TrestleWsMessage(type=TrestleWsMessageType.CLOSED)
        assert msg.type == TrestleWsMessageType.CLOSED
        assert msg.data is None

    def test_create_error_message(self):
        """Test creating an error message."""
        msg = TrestleWsMessage(type=TrestleWsMessageType.ERROR)
        assert msg.type == TrestleWsMessageType.ERROR
        assert msg.data is None

    def test_message_is_frozen(self):
        """Test that messages are immutable."""
        msg = TrestleWsMessage(type=TrestleWsMessageType.TEXT, data="test")
        with pytest.raises(AttributeError):
            msg.data = "modified"  # type: ignore[misc]


class TestTrestleWsClientConnect:
    """Tests for TrestleWsClient.connect()."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful WebSocket connection."""
        mock_ws = AsyncMock()

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ) as mock_connect:
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)

            mock_connect.assert_called_once_with(
                "192.168.1.100",
                80,
                path="/ws",
                ping_interval=20,
                timeout=15.0,
            )
            assert client._ws is mock_ws

    @pytest.mark.asyncio
    async def test_connect_custom_params(self):
        """Test connection with custom parameters."""
        mock_ws = AsyncMock()

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ) as mock_connect:
            client = TrestleWsClient()
            await client.connect(
                "10.0.0.1",
                8080,
                path="/api/trestle_ha/tool/ws",
                ping_interval=30,
                timeout=5.0,
            )

            mock_connect.assert_called_once_with(
                "10.0.0.1",
                8080,
                path="/api/trestle_ha/tool/ws",
                ping_interval=30,
                timeout=5.0,
            )

    @pytest.mark.asyncio
    async def test_connect_propagates_errors(self):
        """Test that connection errors are propagated."""
        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            side_effect=TrestleConnectionError("Connection failed"),
        ):
            client = TrestleWsClient()
            with pytest.raises(TrestleConnectionError, match="Connection failed"):
                await client.connect("192.168.1.100", 80)


class TestTrestleWsClientClose:
    """Tests for TrestleWsClient.close()."""

    @pytest.mark.asyncio
    async def test_close_connected(self):
        """Test closing a connected client."""
        mock_ws = AsyncMock()

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)
            await client.close()

            mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_not_connected(self):
        """Test closing when not connected (no error)."""
        client = TrestleWsClient()
        # Should not raise
        await client.close()


class TestTrestleWsClientSendJson:
    """Tests for TrestleWsClient.send_json()."""

    @pytest.mark.asyncio
    async def test_send_json_success(self):
        """Test sending JSON payload."""
        mock_ws = AsyncMock()

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)
            await client.send_json({"type": "auth", "token": "secret"})

            mock_ws.send.assert_called_once_with('{"type": "auth", "token": "secret"}')

    @pytest.mark.asyncio
    async def test_send_json_not_connected(self):
        """Test send_json raises when not connected."""
        client = TrestleWsClient()
        with pytest.raises(TrestleConnectionError, match="not connected"):
            await client.send_json({"type": "test"})


class TestTrestleWsClientSendBytes:
    """Tests for TrestleWsClient.send_bytes()."""

    @pytest.mark.asyncio
    async def test_send_bytes_success(self):
        """Test sending binary data."""
        mock_ws = AsyncMock()

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)
            await client.send_bytes(b"\x00\x01\x02\x03")

            mock_ws.send.assert_called_once_with(b"\x00\x01\x02\x03")

    @pytest.mark.asyncio
    async def test_send_bytes_not_connected(self):
        """Test send_bytes raises when not connected."""
        client = TrestleWsClient()
        with pytest.raises(TrestleConnectionError, match="not connected"):
            await client.send_bytes(b"data")


class AsyncIteratorMock:
    """Helper class to create a proper async iterator mock."""

    def __init__(self, items: list, *, raise_on_iter: Exception | None = None):
        self._items = items
        self._index = 0
        self._raise_on_iter = raise_on_iter
        self.close = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._raise_on_iter is not None:
            raise self._raise_on_iter
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class TestTrestleWsClientIteration:
    """Tests for TrestleWsClient async iteration."""

    @pytest.mark.asyncio
    async def test_iter_not_connected(self):
        """Test iteration raises when not connected."""
        client = TrestleWsClient()
        with pytest.raises(TrestleConnectionError, match="not connected"):
            await client.__anext__()

    @pytest.mark.asyncio
    async def test_iter_text_messages(self):
        """Test iterating over text messages."""
        mock_ws = AsyncIteratorMock(["message1", "message2"])

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)

            messages = [msg async for msg in client]

        # Should have 2 text messages + closed at end
        text_messages = [m for m in messages if m.type == TrestleWsMessageType.TEXT]
        assert len(text_messages) == 2
        assert text_messages[0].data == "message1"
        assert text_messages[1].data == "message2"

    @pytest.mark.asyncio
    async def test_iter_connection_closed(self):
        """Test iteration handles ConnectionClosed."""
        mock_ws = AsyncIteratorMock([], raise_on_iter=ConnectionClosed(None, None))

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)

            messages = [msg async for msg in client]

        assert len(messages) == 1
        assert messages[0].type == TrestleWsMessageType.CLOSED

    @pytest.mark.asyncio
    async def test_iter_unexpected_error(self):
        """Test iteration handles unexpected errors."""
        mock_ws = AsyncIteratorMock([], raise_on_iter=RuntimeError("Unexpected"))

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)

            messages = [msg async for msg in client]

        assert len(messages) == 1
        assert messages[0].type == TrestleWsMessageType.ERROR

    @pytest.mark.asyncio
    async def test_iter_graceful_close(self):
        """Test iteration emits CLOSED on graceful completion."""
        mock_ws = AsyncIteratorMock(["hello"])

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)

            messages = [msg async for msg in client]

        # Should have text message + closed message
        assert len(messages) == 2
        assert messages[0].type == TrestleWsMessageType.TEXT
        assert messages[0].data == "hello"
        assert messages[1].type == TrestleWsMessageType.CLOSED

    @pytest.mark.asyncio
    async def test_iter_skips_binary_messages(self):
        """Test iteration skips binary messages."""
        mock_ws = AsyncIteratorMock(["text1", b"\x00\x01\x02", "text2"])

        with patch(
            "trestle_coordinator_core.transport.ws_client.connect_websocket",
            return_value=mock_ws,
        ):
            client = TrestleWsClient()
            await client.connect("192.168.1.100", 80)

            messages = [msg async for msg in client]

        # Should have 2 text messages + closed (binary skipped)
        text_messages = [m for m in messages if m.type == TrestleWsMessageType.TEXT]
        assert len(text_messages) == 2
        assert text_messages[0].data == "text1"
        assert text_messages[1].data == "text2"


class TestTrestleWsClientNormalization:
    """Tests for TrestleWsClient message normalization."""

    def test_normalize_string_message(self):
        """Test normalizing a plain string."""
        result = TrestleWsClient._normalize_message("hello world")
        assert result is not None
        assert result.type == TrestleWsMessageType.TEXT
        assert result.data == "hello world"

    def test_normalize_bytes_returns_none(self):
        """Test normalizing bytes returns None (skipped)."""
        result = TrestleWsClient._normalize_message(b"\x00\x01\x02")
        assert result is None

    def test_normalize_unknown_object(self):
        """Test normalizing unknown object uses string repr."""
        obj = object()
        result = TrestleWsClient._normalize_message(obj)
        assert result is not None
        assert result.type == TrestleWsMessageType.TEXT
        assert "object at" in result.data  # type: ignore[operator]


class TestTrestleWsClientAiohttpNormalization:
    """Tests for aiohttp WSMsgType normalization."""

    def test_map_text_type(self):
        """Test mapping aiohttp TEXT type."""
        try:
            from aiohttp import WSMsgType

            result = TrestleWsClient._map_aiohttp_type(WSMsgType.TEXT)
            assert result == TrestleWsMessageType.TEXT
        except ImportError:
            pytest.skip("aiohttp not installed")

    def test_map_binary_type(self):
        """Test mapping aiohttp BINARY type returns None."""
        try:
            from aiohttp import WSMsgType

            result = TrestleWsClient._map_aiohttp_type(WSMsgType.BINARY)
            assert result is None
        except ImportError:
            pytest.skip("aiohttp not installed")

    def test_map_close_types(self):
        """Test mapping aiohttp close-related types."""
        try:
            from aiohttp import WSMsgType

            for close_type in [WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED]:
                result = TrestleWsClient._map_aiohttp_type(close_type)
                assert result == TrestleWsMessageType.CLOSED
        except ImportError:
            pytest.skip("aiohttp not installed")

    def test_map_error_type(self):
        """Test mapping aiohttp ERROR type."""
        try:
            from aiohttp import WSMsgType

            result = TrestleWsClient._map_aiohttp_type(WSMsgType.ERROR)
            assert result == TrestleWsMessageType.ERROR
        except ImportError:
            pytest.skip("aiohttp not installed")

    def test_normalize_aiohttp_message(self):
        """Test normalizing a mock aiohttp message."""
        try:
            from aiohttp import WSMsgType

            mock_msg = MagicMock()
            mock_msg.type = WSMsgType.TEXT
            mock_msg.data = '{"key": "value"}'

            result = TrestleWsClient._normalize_message(mock_msg)
            assert result is not None
            assert result.type == TrestleWsMessageType.TEXT
            assert result.data == '{"key": "value"}'
        except ImportError:
            pytest.skip("aiohttp not installed")


class TestTrestleWsClientDecodeJson:
    """Tests for TrestleWsClient.decode_json()."""

    def test_decode_valid_json(self):
        """Test decoding valid JSON from TEXT message."""
        msg = TrestleWsMessage(
            type=TrestleWsMessageType.TEXT,
            data='{"type": "auth_ok", "version": 1}',
        )
        result = TrestleWsClient.decode_json(msg)
        assert result == {"type": "auth_ok", "version": 1}

    def test_decode_nested_json(self):
        """Test decoding nested JSON structure."""
        msg = TrestleWsMessage(
            type=TrestleWsMessageType.TEXT,
            data='{"body": {"nested": {"value": 42}}}',
        )
        result = TrestleWsClient.decode_json(msg)
        assert result["body"]["nested"]["value"] == 42

    def test_decode_non_text_raises(self):
        """Test decoding non-TEXT message raises error."""
        msg = TrestleWsMessage(type=TrestleWsMessageType.CLOSED)
        with pytest.raises(TrestleClientError, match="Only TEXT messages"):
            TrestleWsClient.decode_json(msg)

    def test_decode_non_string_data_raises(self):
        """Test decoding non-string data raises error."""
        msg = TrestleWsMessage(
            type=TrestleWsMessageType.TEXT,
            data={"already": "parsed"},  # type: ignore[arg-type]
        )
        with pytest.raises(TrestleClientError, match="not a string"):
            TrestleWsClient.decode_json(msg)

    def test_decode_invalid_json_raises(self):
        """Test decoding invalid JSON raises error."""
        msg = TrestleWsMessage(
            type=TrestleWsMessageType.TEXT,
            data="not valid json {",
        )
        with pytest.raises(json.JSONDecodeError):
            TrestleWsClient.decode_json(msg)
