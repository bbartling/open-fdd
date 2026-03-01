"""Open-FDD integration: config flow, coordinator, and full API services."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api_client import OpenFDDClient
from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from .coordinator import OpenFDDCoordinator
from .services import async_setup_services

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
        update_interval_seconds=60,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await coordinator.async_config_entry_first_refresh()

    # Register services once (use first entry's client in handlers)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
