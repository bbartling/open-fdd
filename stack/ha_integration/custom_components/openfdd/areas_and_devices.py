"""
Site → Area and Equipment → Device mapping for the Open-FDD HA integration.

- Each site from GET /sites gets an HA Area (by name); site_id → area_id stored.
- Each equipment from GET /equipment gets an HA Device with suggested_area (or suggested_area_id on older HA).
"""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def ensure_areas_and_equipment_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
    main_device_id: str | None = None,
) -> dict[str, str]:
    """
    Ensure HA areas exist for each site and HA devices for each equipment.
    Updates hass.data[DOMAIN][entry_id]["site_area_ids"] and creates/updates devices.
    Returns site_id -> area_id mapping.
    """
    sites = data.get("sites") or []
    equipment_list = data.get("equipment") or []
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    site_area_ids: dict[str, str] = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("site_area_ids") or {}

    existing_areas = {a.name: a for a in area_registry.async_list_areas()}
    for site in sites:
        site_id = site.get("id")
        if site_id is not None:
            site_id = str(site_id)
        name = (site.get("name") or "").strip() or f"Site {site_id}"
        if not site_id:
            continue
        area_entry = existing_areas.get(name)
        if area_entry is None:
            area_entry = area_registry.async_create(name)
            existing_areas[name] = area_entry
        area_id = area_entry.id
        site_area_ids[site_id] = area_id
        if area_entry.name != name:
            area_registry.async_update(area_id, name=name)

    for eq in equipment_list:
        eq_id = eq.get("id")
        if eq_id is not None:
            eq_id = str(eq_id)
        site_id = eq.get("site_id")
        if site_id is not None:
            site_id = str(site_id)
        name = (eq.get("name") or "").strip() or f"Equipment {eq_id}"
        if not eq_id:
            continue
        area_id = site_area_ids.get(site_id) if site_id else None
        # HA 2025+ uses suggested_area; older versions used suggested_area_id
        # Only pass via_device if the parent device exists (HA 2025.12+ requires it)
        create_kw: dict[str, Any] = {
            "config_entry_id": entry.entry_id,
            "identifiers": {(DOMAIN, eq_id)},
            "manufacturer": "Open-FDD",
            "model": "Equipment",
            "name": name,
        }
        # Omit via_device to avoid HA 2025.12+ "non existing via_device" errors when registry
        # is not yet committed. Equipment still appears under the integration via config_entry_id.
        if area_id:
            try:
                import inspect
                params = inspect.signature(device_registry.async_get_or_create).parameters
                if "suggested_area" in params:
                    create_kw["suggested_area"] = area_id
                else:
                    create_kw["suggested_area_id"] = area_id
            except Exception:
                create_kw["suggested_area"] = area_id
        dev = device_registry.async_get_or_create(**create_kw)
        # Update name/area if equipment was renamed or moved
        if dev.name != name or (area_id and dev.area_id != area_id):
            device_registry.async_update_device(
                dev.id,
                name=name,
                area_id=area_id or dev.area_id,
            )

    # Persist mapping for platforms
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if entry.entry_id not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.entry_id] = {}
    hass.data[DOMAIN][entry.entry_id]["site_area_ids"] = site_area_ids
    return site_area_ids
