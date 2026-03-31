"""WebSocket router: GET /ws/events with subscribe/unsubscribe and auth."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from open_fdd.platform.api.auth import validate_access_token
from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.realtime.hub import get_hub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_HEARTBEAT_INTERVAL = 30.0  # seconds


def _ws_auth_ok(token: str | None, headers: Any = None) -> bool:
    """Validate WebSocket auth: token query param, or X-Caddy-Auth when behind Caddy."""
    settings = get_platform_settings()
    if headers and getattr(settings, "caddy_internal_secret", None):
        if headers.get("x-caddy-auth") == settings.caddy_internal_secret:
            return True
    api_key = getattr(settings, "api_key", None)
    app_user = getattr(settings, "app_user", None)
    app_hash = getattr(settings, "app_user_hash", None)
    auth_required = bool(api_key or (app_user and app_hash))
    if not auth_required:
        return True
    if token and api_key and token.strip() == api_key:
        return True
    return validate_access_token(token)


@router.websocket("/ws/events")
async def websocket_events(
    websocket: WebSocket,
    token: str | None = Query(None, description="API key when OFDD_API_KEY is set"),
):
    """
    Event stream with topic subscriptions. Send JSON messages:
    - {"type":"subscribe","topics":["fault.*","crud.point.*"]}
    - {"type":"unsubscribe","topics":["crud.*"]}
    - {"type":"ping"}
    Server sends: {"type":"event",...}, {"type":"pong"}.
    """
    headers = list(websocket.scope.get("headers") or [])
    header_dict = {k.decode().lower(): v.decode() for k, v in headers}
    if not _ws_auth_ok(token, header_dict):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    hub = get_hub()
    await hub.connect(websocket)
    try:
        last_heartbeat = asyncio.get_event_loop().time()
        while True:
            try:
                # Wait for either client message or heartbeat timeout
                msg = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_HEARTBEAT_INTERVAL
                )
                last_heartbeat = asyncio.get_event_loop().time()
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await hub.send_personal(websocket, {"type": "pong"})
                except Exception:
                    break
                continue

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                await hub.send_personal(
                    websocket,
                    {"type": "error", "message": "Invalid JSON"},
                )
                continue

            msg_type = data.get("type")
            if msg_type == "subscribe":
                topics = data.get("topics") or []
                if isinstance(topics, list):
                    await hub.subscribe(websocket, topics)
            elif msg_type == "unsubscribe":
                topics = data.get("topics") or []
                if isinstance(topics, list):
                    await hub.unsubscribe(websocket, topics)
            elif msg_type == "ping":
                await hub.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
