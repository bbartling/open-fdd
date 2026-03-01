"""Optional WebSocket listener for fault.* events — refresh coordinator on fault.raised/cleared."""

import asyncio
import json
import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import OpenFDDClient

_LOGGER = logging.getLogger(__name__)


async def _ws_listener_task(
    hass: HomeAssistant,
    client: OpenFDDClient,
    coordinator: DataUpdateCoordinator,
) -> None:
    """Connect to Open-FDD WebSocket, subscribe to fault.*, refresh coordinator on events."""
    import aiohttp
    url = client.ws_url()
    headers = client.ws_headers()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, heartbeat=25, headers=headers) as ws:
                await ws.send_str(json.dumps({"type": "subscribe", "topics": ["fault.*"]}))
                async for msg in ws:
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(msg.data)
                        if data.get("type") == "event":
                            topic = data.get("topic", "")
                            if topic.startswith("fault."):
                                hass.async_create_task(coordinator.async_request_refresh())
                    except (json.JSONDecodeError, KeyError):
                        pass
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _LOGGER.warning("Open-FDD WebSocket listener stopped: %s", e)


def start_ws_listener(
    hass: HomeAssistant,
    client: OpenFDDClient,
    coordinator: DataUpdateCoordinator,
    capabilities: dict,
) -> asyncio.Task | None:
    """Start WebSocket listener if capabilities.websocket is true. Returns task to cancel on unload."""
    if not capabilities.get("websocket"):
        return None
    task = hass.loop.create_task(_ws_listener_task(hass, client, coordinator))
    return task
