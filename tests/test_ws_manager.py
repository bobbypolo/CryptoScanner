"""Tests for the WebSocket ConnectionManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from quant_scanner.ws_manager import ConnectionManager


def _make_mock_ws() -> MagicMock:
    """Create a mock WebSocket with accept and send_json as AsyncMock."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


async def test_connect_adds_to_set():
    """After connect(), client_count() should be 1."""
    manager = ConnectionManager()
    ws = _make_mock_ws()
    await manager.connect(ws)
    assert manager.client_count() == 1
    ws.accept.assert_awaited_once()


async def test_disconnect_removes():
    """After connect then disconnect, client_count() should be 0."""
    manager = ConnectionManager()
    ws = _make_mock_ws()
    await manager.connect(ws)
    assert manager.client_count() == 1
    manager.disconnect(ws)
    assert manager.client_count() == 0


async def test_disconnect_idempotent():
    """Disconnecting a websocket that was never connected raises no error."""
    manager = ConnectionManager()
    ws = _make_mock_ws()
    # Should not raise
    manager.disconnect(ws)
    assert manager.client_count() == 0

    # Also test double-disconnect after connect
    await manager.connect(ws)
    manager.disconnect(ws)
    manager.disconnect(ws)
    assert manager.client_count() == 0


async def test_broadcast_sends_to_all():
    """Broadcast sends the message to all connected clients."""
    manager = ConnectionManager()
    ws1 = _make_mock_ws()
    ws2 = _make_mock_ws()
    await manager.connect(ws1)
    await manager.connect(ws2)

    message = {"type": "scan_complete", "coin_count": 5}
    await manager.broadcast(message)

    ws1.send_json.assert_awaited_once_with(message)
    ws2.send_json.assert_awaited_once_with(message)


async def test_broadcast_handles_dead_client():
    """If one client raises on send_json, the other still receives the message."""
    manager = ConnectionManager()
    ws_alive = _make_mock_ws()
    ws_dead = _make_mock_ws()
    ws_dead.send_json = AsyncMock(side_effect=Exception("Connection closed"))

    await manager.connect(ws_alive)
    await manager.connect(ws_dead)
    assert manager.client_count() == 2

    message = {"type": "scan_complete", "coin_count": 3}
    await manager.broadcast(message)

    # The alive client should have received the message
    ws_alive.send_json.assert_awaited_once_with(message)
    # The dead client was removed
    assert manager.client_count() == 1


async def test_client_count():
    """Connect 3, disconnect 1, verify client_count() == 2."""
    manager = ConnectionManager()
    ws1 = _make_mock_ws()
    ws2 = _make_mock_ws()
    ws3 = _make_mock_ws()
    await manager.connect(ws1)
    await manager.connect(ws2)
    await manager.connect(ws3)
    assert manager.client_count() == 3

    manager.disconnect(ws2)
    assert manager.client_count() == 2


async def test_broadcast_to_zero_clients():
    """Broadcasting with no connections raises no error."""
    manager = ConnectionManager()
    assert manager.client_count() == 0
    # Should not raise
    await manager.broadcast({"type": "test"})
