"""Open-FDD sensors: main summary + per-equipment fault summary."""

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Open-FDD sensors: main device summary + per-equipment fault summary."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    if not coordinator:
        return

    added_eq: set[str] = set()

    @callback
    def _add_equipment_sensors() -> None:
        d = coordinator.data or {}
        equipment_list = d.get("equipment") or []
        new_entities: list[SensorEntity] = []
        for eq in equipment_list:
            eq_id = eq.get("id")
            if not eq_id:
                continue
            eq_id = str(eq_id)
            if eq_id in added_eq:
                continue
            added_eq.add(eq_id)
            new_entities.append(OpenFDDEquipmentActiveFaultCountSensor(coordinator, eq_id, eq.get("name") or eq_id))
            new_entities.append(OpenFDDEquipmentLastFaultChangeSensor(coordinator, eq_id, eq.get("name") or eq_id))
        if new_entities:
            async_add_entities(new_entities)

    async_add_entities([
        OpenFDDActiveFaultCountSensor(coordinator, entry.entry_id),
        OpenFDDLastRunSensor(coordinator, entry.entry_id),
    ])
    _add_equipment_sensors()

    added_suggested: set[str] = set()

    @callback
    def _add_suggested_sensors() -> None:
        d = coordinator.data or {}
        suggested = d.get("entities_suggested") or []
        new_entities = []
        for item in suggested:
            if (item.get("suggested_ha_domain") or "").strip().lower() != "sensor":
                continue
            eq_id = str(item.get("equipment_id") or "")
            ha_id = (item.get("suggested_ha_id") or item.get("point_id") or "").strip() or "sensor"
            uid = f"{DOMAIN}_suggested_{eq_id}_{ha_id}".replace(" ", "_")
            if uid in added_suggested:
                continue
            added_suggested.add(uid)
            new_entities.append(OpenFDDSuggestedSensor(coordinator, item))
        if new_entities:
            async_add_entities(new_entities)

    def _on_data() -> None:
        _add_equipment_sensors()
        _add_suggested_sensors()

    _on_data()
    entry.async_on_unload(coordinator.async_add_listener(_on_data))


class OpenFDDSummarySensor(CoordinatorEntity, SensorEntity):
    """Base for Open-FDD summary sensors on the main gateway device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_device_info = {"identifiers": {(DOMAIN, entry_id)}}


class OpenFDDActiveFaultCountSensor(OpenFDDSummarySensor):
    """Total active fault count (main device)."""

    _attr_unique_id = "openfdd_active_fault_count"
    _attr_name = "Active fault count"
    _attr_native_unit_of_measurement = "faults"

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data or {}
        return len(data.get("faults_active") or [])


class OpenFDDLastRunSensor(OpenFDDSummarySensor):
    """Last FDD run timestamp (main device)."""

    _attr_unique_id = "openfdd_last_run_ts"
    _attr_name = "Last FDD run"
    _attr_device_class = "timestamp"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        run_status = data.get("run_fdd_status") or {}
        last_run = run_status.get("last_run") or {}
        run_ts = last_run.get("run_ts")
        return str(run_ts) if run_ts else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        last_run = (data.get("run_fdd_status") or {}).get("last_run") or {}
        return {
            "status": last_run.get("status"),
            "sites_processed": last_run.get("sites_processed"),
            "faults_written": last_run.get("faults_written"),
        }


class OpenFDDEquipmentSensorBase(CoordinatorEntity, SensorEntity):
    """Base for per-equipment sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, equipment_id: str, equipment_name: str, unique_suffix: str, name: str) -> None:
        super().__init__(coordinator)
        self._equipment_id = equipment_id
        self._equipment_name = equipment_name
        self._attr_unique_id = f"{DOMAIN}_{unique_suffix}_{equipment_id}"
        self._attr_name = name
        self._attr_device_info = {"identifiers": {(DOMAIN, equipment_id)}}


class OpenFDDEquipmentActiveFaultCountSensor(OpenFDDEquipmentSensorBase):
    """Active fault count for one equipment."""

    def __init__(self, coordinator, equipment_id: str, equipment_name: str) -> None:
        super().__init__(
            coordinator, equipment_id, equipment_name,
            "equipment_active_fault_count", "Active fault count",
        )
        self._attr_native_unit_of_measurement = "faults"

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        faults = data.get("faults_active") or []
        return sum(1 for f in faults if str(f.get("equipment_id")) == self._equipment_id)


class OpenFDDEquipmentLastFaultChangeSensor(OpenFDDEquipmentSensorBase):
    """Latest fault last_changed_ts for one equipment (for history/log)."""

    def __init__(self, coordinator, equipment_id: str, equipment_name: str) -> None:
        super().__init__(
            coordinator, equipment_id, equipment_name,
            "equipment_last_fault_change", "Last fault change",
        )
        self._attr_device_class = "timestamp"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        faults = data.get("faults_active") or []
        times = []
        for f in faults:
            if str(f.get("equipment_id")) != self._equipment_id:
                continue
            ts = f.get("last_changed_ts")
            if ts:
                if isinstance(ts, datetime):
                    times.append(ts)
                else:
                    try:
                        times.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
                    except Exception:
                        pass
        if not times:
            return None
        return max(times).isoformat()


# ----- Brick suggested entities (placeholder until timeseries read API) -----

class OpenFDDSuggestedSensor(CoordinatorEntity, SensorEntity):
    """Placeholder sensor for Brick-tagged point (e.g. OA temp); unavailable until timeseries read."""

    _attr_has_entity_name = True
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator, item: dict) -> None:
        super().__init__(coordinator)
        self._item = item
        eq_id = str(item.get("equipment_id") or "")
        point_id = str(item.get("point_id") or "")
        ha_id = (item.get("suggested_ha_id") or point_id or "").strip() or "sensor"
        self._attr_unique_id = f"{DOMAIN}_suggested_{eq_id}_{ha_id}".replace(" ", "_")
        self._attr_name = (item.get("external_id") or ha_id or "Point").replace("_", " ").title()
        self._attr_device_info = {"identifiers": {(DOMAIN, eq_id)}}
        self._attr_native_value = None
        self._attr_available = False
        if item.get("unit"):
            self._attr_native_unit_of_measurement = item["unit"]
