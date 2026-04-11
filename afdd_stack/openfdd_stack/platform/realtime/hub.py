"""WebSocket connection manager and topic subscription with wildcard matching."""

import asyncio
import fnmatch
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _topic_matches(subscription: str, topic: str) -> bool:
    return fnmatch.fnmatch(topic, subscription)


class ConnectionManager:
    """Per-connection subscriptions and broadcast with wildcard matching."""

    def __init__(self):
        self._connections: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _set_loop(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    async def connect(self, websocket: WebSocket) -> None:
        self._set_loop()
        await websocket.accept()
        async with self._lock:
            self._connections[websocket] = set()

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)

    async def subscribe(self, websocket: WebSocket, topics: list[str]) -> None:
        async with self._lock:
            s = self._connections.get(websocket)
            if s is not None:
                for t in topics:
                    if t and isinstance(t, str):
                        s.add(t.strip())

    async def unsubscribe(self, websocket: WebSocket, topics: list[str]) -> None:
        async with self._lock:
            s = self._connections.get(websocket)
            if s is not None:
                for t in topics:
                    if t and isinstance(t, str):
                        s.discard(t.strip())

    def _get_subscribers_for_topic(self, topic: str) -> list[WebSocket]:
        result = []
        for ws, patterns in list(self._connections.items()):
            for pat in patterns:
                if _topic_matches(pat, topic):
                    result.append(ws)
                    break
        return result

    async def _broadcast_impl(self, payload: dict[str, Any]) -> None:
        topic = payload.get("topic", "")
        if not topic:
            return
        msg = json.dumps(payload)
        dead = []
        for ws in self._get_subscribers_for_topic(topic):
            try:
                await ws.send_text(msg)
            except Exception as e:
                logger.debug("ws send failed: %s", e)
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast(self, payload: dict[str, Any]) -> None:
        """Call from sync code (e.g. CRUD): schedule async send on event loop."""
        if not self._loop or not payload.get("topic"):
            return
        try:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._broadcast_impl(payload))
            )
        except Exception as e:
            logger.debug("broadcast schedule failed: %s", e)

    async def send_personal(
        self, websocket: WebSocket, payload: dict[str, Any]
    ) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as e:
            logger.debug("ws send failed: %s", e)
            self.disconnect(websocket)


_hub: ConnectionManager | None = None


def get_hub() -> ConnectionManager:
    global _hub
    if _hub is None:
        _hub = ConnectionManager()
    return _hub
