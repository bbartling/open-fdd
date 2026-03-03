"""Open-FDD integration: config flow, coordinator, sites→areas, equipment→devices only."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api_client import OpenFDDClient
from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from .coordinator import OpenFDDCoordinator
from .areas_and_devices import ensure_areas_and_equipment_devices

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Integration setup (no YAML config)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Open-FDD from a config entry. Sites→areas, equipment→devices only (no sensors/buttons)."""
    base_url = entry.data[CONF_BASE_URL]
    api_key = entry.data[CONF_API_KEY]
    client = OpenFDDClient(base_url=base_url, api_key=api_key)
    coordinator = OpenFDDCoordinator(
        hass=hass,
        client=client,
        update_interval_seconds=30,
    )

    await coordinator.async_config_entry_first_refresh()

    device_registry = dr.async_get(hass)
    main_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Open-FDD",
        model="Open-FDD Platform",
        name="Open-FDD",
    )
    caps = (coordinator.data or {}).get("capabilities") or {}
    api_version = caps.get("version") if isinstance(caps, dict) else None
    if api_version and isinstance(api_version, str) and len(api_version) < 32:
        device_registry.async_update_device(main_device.id, sw_version=api_version)

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

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
