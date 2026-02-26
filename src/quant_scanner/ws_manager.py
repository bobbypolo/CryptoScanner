"""WebSocket connection manager for the Crypto Quant Scanner dashboard.

Manages a set of active WebSocket connections and provides fault-tolerant
broadcasting. If one client's send fails, it is removed and the broadcast
continues to remaining clients.
"""

from __future__ import annotations

import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages.

    Thread-safety note: This class is NOT thread-safe. All access must happen
    on a single asyncio event loop (the same loop running the FastAPI server).
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and add it to the active set."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.debug("WebSocket connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from the active set.

        Safe to call even if the websocket is not in the set (uses discard).
        """
        self._connections.discard(websocket)
        logger.debug("WebSocket disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected clients.

        Iterates over a COPY of the connections set. If any client's send_json
        raises an exception, that client is removed via disconnect() and
        iteration continues to the remaining clients.
        """
        for ws in self._connections.copy():
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)
                logger.debug("Removed dead WebSocket during broadcast")
        logger.debug("Broadcast sent to %d clients", len(self._connections))

    def client_count(self) -> int:
        """Return the number of active WebSocket connections."""
        return len(self._connections)
