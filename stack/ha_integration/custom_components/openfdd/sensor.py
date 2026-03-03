"""Open-FDD point telemetry sensors: one sensor per point, value from DB + stale indicator."""

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STALE_DATA_SECONDS

_LOGGER = logging.getLogger(__name__)

# Map Brick type (or unit) to HA device_class and state_class for area/dashboard display
# (OCCUPANCY is BinarySensorDeviceClass only; numeric point sensors don't use it)
_BRICK_DEVICE_CLASS: dict[str, str] = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "pressure": SensorDeviceClass.PRESSURE,
    "power": SensorDeviceClass.POWER,
    "humidity": SensorDeviceClass.HUMIDITY,
    "flow": SensorDeviceClass.VOLUME_FLOW_RATE,
    "co2": SensorDeviceClass.CO2,
}
_UNIT_DEVICE_CLASS: dict[str, str] = {
    "celsius": SensorDeviceClass.TEMPERATURE,
    "fahrenheit": SensorDeviceClass.TEMPERATURE,
    "degrees-fahrenheit": SensorDeviceClass.TEMPERATURE,
    "degrees-celsius": SensorDeviceClass.TEMPERATURE,
    "kwh": SensorDeviceClass.ENERGY,
    "watt": SensorDeviceClass.POWER,
    "kw": SensorDeviceClass.POWER,
    "pa": SensorDeviceClass.PRESSURE,
    "inwc": SensorDeviceClass.PRESSURE,
    "cfm": SensorDeviceClass.VOLUME_FLOW_RATE,
    "ppm": SensorDeviceClass.CO2,
}


def _device_and_state_class(point: dict) -> tuple[str | None, str | None]:
    """Infer device_class and state_class from point brick_type and unit."""
    brick = (point.get("brick_type") or "").lower()
    unit = (point.get("unit") or "").lower()
    dc: str | None = None
    for key, val in _BRICK_DEVICE_CLASS.items():
        if key in brick:
            dc = val
            break
    if dc is None:
        for u, val in _UNIT_DEVICE_CLASS.items():
            if u in unit:
                dc = val
                break
    state_class = SensorStateClass.MEASUREMENT if dc else None
    if dc == SensorDeviceClass.ENERGY:
        state_class = SensorStateClass.TOTAL_INCREASING
    return dc, state_class


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one sensor per point; value and staleness from GET /timeseries/latest."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    main_device_id = data.get("device_id")
    if not coordinator:
        return

    added_point_ids: set[str] = set()

    @callback
    def _add_point_sensors() -> None:
        d = coordinator.data or {}
        points_list = d.get("points") or []
        latest = d.get("timeseries_latest") or {}
        new_entities: list[SensorEntity] = []
        for pt in points_list:
            point_id = pt.get("id")
            if point_id is not None:
                point_id = str(point_id)
            if not point_id or point_id in added_point_ids:
                continue
            # Only create sensors for points that are Brick-tagged (show telemetry under device only when tagged)
            if not (pt.get("brick_type") or "").strip():
                continue
            added_point_ids.add(point_id)
            new_entities.append(
                OpenFDDPointSensor(
                    coordinator,
                    entry.entry_id,
                    point_id,
                    pt,
                    main_device_id,
                )
            )
        if new_entities:
            async_add_entities(new_entities)

    _add_point_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_point_sensors))


class OpenFDDPointSensor(CoordinatorEntity, SensorEntity):
    """One sensor per point: state = latest value from DB; attributes = data_age_seconds, is_stale."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry_id: str,
        point_id: str,
        point: dict,
        main_device_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._point_id = point_id
        self._point = point
        self._main_device_id = main_device_id
        external_id = (point.get("external_id") or point_id or "point").strip()
        self._attr_unique_id = f"{DOMAIN}_point_{point_id}"
        self._attr_name = external_id.replace("_", " ").title()
        if point.get("unit"):
            self._attr_native_unit_of_measurement = point["unit"]
        dc, sc = _device_and_state_class(point)
        if dc:
            self._attr_device_class = dc
        if sc:
            self._attr_state_class = sc
        # Device: attach to equipment device if present, else main Open-FDD device
        eq_id = point.get("equipment_id")
        if eq_id:
            self._attr_device_info = {"identifiers": {(DOMAIN, str(eq_id))}}
        else:
            self._attr_device_info = {"identifiers": {(DOMAIN, entry_id)}}

    def _handle_coordinator_update(self) -> None:
        """Use reading timestamp as last_updated so area card shows when value was taken."""
        super()._handle_coordinator_update()
        latest = (self.coordinator.data or {}).get("timeseries_latest") or {}
        row = latest.get(self._point_id)
        if not row:
            return
        ts_str = row.get("ts")
        if not ts_str:
            return
        try:
            if isinstance(ts_str, datetime):
                reading_dt = ts_str
            else:
                reading_dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if reading_dt.tzinfo is None:
                reading_dt = reading_dt.replace(tzinfo=timezone.utc)
            self._attr_last_updated = reading_dt
        except Exception:
            pass

    @property
    def native_value(self) -> Any:
        latest = (self.coordinator.data or {}).get("timeseries_latest") or {}
        row = latest.get(self._point_id)
        if not row:
            return None
        return row.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        latest = (self.coordinator.data or {}).get("timeseries_latest") or {}
        row = latest.get(self._point_id)
        if not row:
            return {}
        ts_str = row.get("ts")
        if not ts_str:
            return {"is_stale": True, "data_age_seconds": None}
        try:
            if isinstance(ts_str, datetime):
                reading_dt = ts_str
            else:
                reading_dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if reading_dt.tzinfo is None:
                reading_dt = reading_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age = int((now - reading_dt).total_seconds())
            return {
                "data_age_seconds": age,
                "is_stale": age > STALE_DATA_SECONDS,
                "last_reading_ts": reading_dt.isoformat(),
            }
        except Exception:
            return {"is_stale": True, "data_age_seconds": None}
