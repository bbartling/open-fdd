"""Open-FDD integration: config flow, coordinator, devices, entities, and services."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api_client import OpenFDDClient
from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from .coordinator import OpenFDDCoordinator
from .areas_and_devices import ensure_areas_and_equipment_devices
from .services import async_setup_services
from .ws_listener import start_ws_listener

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Integration setup (no YAML config)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Open-FDD from a config entry."""
    base_url = entry.data[CONF_BASE_URL]
    api_key = entry.data[CONF_API_KEY]
    client = OpenFDDClient(base_url=base_url, api_key=api_key)
    coordinator = OpenFDDCoordinator(
        hass=hass,
        client=client,
        update_interval_seconds=30,
    )

    await coordinator.async_config_entry_first_refresh()

    # Main gateway device (summary sensors + global buttons)
    device_registry = dr.async_get(hass)
    main_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Open-FDD",
        model="Open-FDD Platform",
        name="Open-FDD",
    )

    # Site → Area, Equipment → Device (from coordinator data)
    def _sync_areas_and_devices() -> None:
        d = coordinator.data or {}
        ensure_areas_and_equipment_devices(hass, entry, d, main_device.id)
    _sync_areas_and_devices()
    entry.async_on_unload(coordinator.async_add_listener(_sync_areas_and_devices))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "device_id": main_device.id,
    }

    # Optional WebSocket listener for fault.* (refresh coordinator on fault.raised/cleared)
    caps = (coordinator.data or {}).get("capabilities") or {}
    features = caps.get("features") if isinstance(caps.get("features"), dict) else caps
    ws_task = start_ws_listener(hass, client, coordinator, features)
    if ws_task is not None:
        entry.async_on_unload(ws_task.cancel)

    # Register services once (use first entry's client in handlers)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(
        entry, ["binary_sensor", "sensor", "button"]
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(
        entry, ["binary_sensor", "sensor", "button"]
    )
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
