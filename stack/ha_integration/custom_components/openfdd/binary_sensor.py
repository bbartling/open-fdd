"""Open-FDD fault binary sensors — one per (equipment, fault_id) under the equipment device."""

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CONTEXT,
    ATTR_FAULT_ID,
    ATTR_LAST_CHANGED_TS,
    ATTR_LAST_EVALUATED_TS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _ts_iso(ts: Any) -> str | None:
    """Return ISO string for timestamp (datetime or str)."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def _definitions_for_equipment(fault_definitions: list, equipment: dict) -> list:
    """Return fault definitions that apply to this equipment (by equipment_type or all)."""
    eq_type = (equipment.get("equipment_type") or "").strip()
    out = []
    for d in fault_definitions or []:
        types = d.get("equipment_types") or []
        if not types or (eq_type and eq_type in types):
            out.append(d)
    return out


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Open-FDD fault binary sensors: one per (equipment, fault_id) under equipment device."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    if not coordinator:
        return

    added: set[tuple[str, str]] = set()

    @callback
    def _add_entities() -> None:
        d = coordinator.data or {}
        equipment_list = d.get("equipment") or []
        fault_definitions = d.get("fault_definitions") or []
        faults_active = d.get("faults_active") or []
        active_by_eq_fault: set[tuple[str, str]] = {
            (str(f.get("equipment_id") or ""), str(f.get("fault_id") or ""))
            for f in faults_active
        }
        new_entities: list[OpenFDDFaultBinarySensor] = []
        for eq in equipment_list:
            eq_id = eq.get("id")
            if not eq_id:
                continue
            eq_id = str(eq_id)
            for defn in _definitions_for_equipment(fault_definitions, eq):
                fault_id = defn.get("fault_id") or ""
                if not fault_id:
                    continue
                key = (eq_id, fault_id)
                if key in added:
                    continue
                added.add(key)
                # Find current active state for this (equipment, fault_id)
                fault_row = next(
                    (f for f in faults_active
                     if str(f.get("equipment_id")) == eq_id and str(f.get("fault_id")) == fault_id),
                    None,
                )
                new_entities.append(
                    OpenFDDFaultBinarySensor(
                        coordinator=coordinator,
                        equipment_id=eq_id,
                        equipment_name=eq.get("name") or eq_id,
                        fault_id=fault_id,
                        fault_name=defn.get("name") or fault_id,
                        severity=defn.get("severity"),
                        initial_fault_row=fault_row,
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    added_suggested: set[str] = set()

    @callback
    def _add_suggested_binary_sensors() -> None:
        d = coordinator.data or {}
        suggested = d.get("entities_suggested") or []
        new_entities = []
        for item in suggested:
            if (item.get("suggested_ha_domain") or "").strip().lower() != "binary_sensor":
                continue
            eq_id = str(item.get("equipment_id") or "")
            ha_id = (item.get("suggested_ha_id") or item.get("point_id") or "").strip() or "binary_sensor"
            uid = f"{DOMAIN}_suggested_bin_{eq_id}_{ha_id}".replace(" ", "_")
            if uid in added_suggested:
                continue
            added_suggested.add(uid)
            new_entities.append(OpenFDDSuggestedBinarySensor(coordinator, item))
        if new_entities:
            async_add_entities(new_entities)

    def _on_data() -> None:
        _add_entities()
        _add_suggested_binary_sensors()

    _on_data()
    entry.async_on_unload(coordinator.async_add_listener(_on_data))


class OpenFDDFaultBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for one (equipment, fault_id); attached to the equipment device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        equipment_id: str,
        equipment_name: str,
        fault_id: str,
        fault_name: str,
        severity: str | None,
        initial_fault_row: dict | None,
    ) -> None:
        super().__init__(coordinator)
        self._equipment_id = equipment_id
        self._equipment_name = equipment_name
        self._fault_id = fault_id
        self._attr_unique_id = f"{DOMAIN}_fault_{equipment_id}_{fault_id}"
        self._attr_name = fault_name or fault_id
        self._attr_device_info = {"identifiers": {(DOMAIN, equipment_id)}}
        self._update_from_row(initial_fault_row)

    def _update_from_row(self, row: dict | None) -> None:
        self._attr_is_on = bool(row and row.get("active", False))
        if row:
            self._attr_extra_state_attributes = {
                ATTR_FAULT_ID: self._fault_id,
                ATTR_LAST_CHANGED_TS: _ts_iso(row.get("last_changed_ts")),
                ATTR_LAST_EVALUATED_TS: _ts_iso(row.get("last_evaluated_ts")),
                ATTR_CONTEXT: row.get("context"),
                "site_id": row.get("site_id"),
                "equipment_id": row.get("equipment_id"),
            }
        else:
            self._attr_extra_state_attributes = {
                ATTR_FAULT_ID: self._fault_id,
                "site_id": None,
                "equipment_id": self._equipment_id,
            }

    @callback
    def _handle_coordinator_update(self) -> None:
        faults = (self.coordinator.data or {}).get("faults_active") or []
        row = next(
            (f for f in faults
             if str(f.get("equipment_id")) == self._equipment_id and str(f.get("fault_id")) == self._fault_id),
            None,
        )
        self._update_from_row(row)
        super()._handle_coordinator_update()

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._equipment_id)}}


class OpenFDDSuggestedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Placeholder binary_sensor for Brick-tagged point (e.g. occupancy); unavailable until timeseries read."""

    _attr_has_entity_name = True
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator, item: dict) -> None:
        super().__init__(coordinator)
        self._item = item
        eq_id = str(item.get("equipment_id") or "")
        ha_id = (item.get("suggested_ha_id") or item.get("point_id") or "").strip() or "binary_sensor"
        self._attr_unique_id = f"{DOMAIN}_suggested_bin_{eq_id}_{ha_id}".replace(" ", "_")
        self._attr_name = (item.get("external_id") or ha_id or "Point").replace("_", " ").title()
        self._attr_device_info = {"identifiers": {(DOMAIN, eq_id)}}
        self._attr_is_on = None
        self._attr_available = False
