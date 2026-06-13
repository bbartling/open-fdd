"""FDD / BRICK query preset buttons (parity with Edge DataModelSparqlPanel)."""

from __future__ import annotations

FDD_PRESET_BUTTONS: list[tuple[str, str]] = [
    ("rules_to_equipment", "Rules → Equipment"),
    ("rules_to_sensors", "Rules → Sensors"),
    ("rules_to_bacnet_devices", "Rules → BACnet Devices"),
    ("equipment_to_points", "Equipment → Points"),
    ("ahus_vavs_zones", "AHUs / VAVs / Zones"),
    ("missing_rule_bindings", "Missing Rule Bindings"),
    ("points_by_bacnet_device", "Points by BACnet Device"),
    ("sensor_classes_used_by_fdd", "Sensor Classes Used by FDD"),
    ("rule_coverage_by_equipment_type", "Rule Coverage by Equipment Type"),
    ("orphan_points", "Orphan Points / Unused Sensors"),
]
