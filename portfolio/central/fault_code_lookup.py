"""Stable fault-code → short description lookup (mirrors fault_catalog.py titles).

Source of truth for operator UI labels: docs/fault-codes/short-lookup.md
Runtime catalog: workspace/api/openfdd_bridge/fault_catalog.py
"""

from __future__ import annotations

# Letter-suffix codes only — titles match fault_catalog.py (do not remove entries).
SHORT_DESCRIPTIONS: dict[str, str] = {
    "AHU-A": "Supply fan performance degradation",
    "AHU-B": "Simultaneous heating and cooling",
    "AHU-C": "Supply air temperature sensor fault",
    "AHU-D": "Mixed-air temperature inconsistent with OAT/RAT",
    "AHU-E": "Economizer not economizing",
    "AHU-F": "Damper/valve command vs feedback mismatch",
    "VAV-A": "Reheat active during cooling demand",
    "VAV-B": "Airflow not meeting setpoint",
    "VAV-C": "Zone temperature sensor fault",
    "VAV-D": "Damper command vs airflow mismatch",
    "VAV-E": "Rogue zone (chronic reheat/overcooling)",
    "HP-A": "Heating/cooling capacity or COP degradation",
    "HP-B": "Auxiliary heat with compressor cooling",
    "HP-C": "Reversing valve fault (mode mismatch)",
    "HP-D": "Discharge/suction temperature sensor fault",
    "HP-E": "Excessive defrost cycling",
    "GEO-A": "Ground loop temperature out of band",
    "GEO-B": "Loop pump performance / low delta-T",
    "GEO-C": "Loop water temperature sensor fault",
    "GEO-D": "Loop isolation valve command vs feedback mismatch",
    "CH-A": "Condenser approach temperature high",
    "CH-B": "Low delta-T syndrome",
    "CH-C": "Mechanical cooling with heating in same loop/zone",
    "CH-D": "Chilled-water supply temperature sensor fault",
    "CH-E": "CHW valve/pump command vs feedback mismatch",
    "CH-F": "Chiller efficiency drift (kW/ton)",
    "DC-A": "Units fighting (simultaneous humidify/dehumidify or heat/cool)",
    "DC-B": "Cooling capacity degradation / high return temp",
    "DC-C": "Supply/return air temperature sensor fault",
    "DC-D": "Fan command vs feedback mismatch",
    "BLD-A": "Whole-building energy deviation",
    "BLD-B": "Outdoor-air temperature sensor fault",
    "BLD-C": "Equipment running outside occupancy schedule",
    "BLD-D": "Point data dropout (stale points)",
    "RTU-A": "Supply fan performance degradation",
    "RTU-B": "Simultaneous heating and cooling",
    "RTU-C": "Discharge air temperature sensor fault",
    "RTU-D": "Damper/valve command vs feedback mismatch",
}


def lookup_fault_description(code: str) -> str:
    raw = str(code or "").strip().upper()
    if not raw:
        return "Fault"
    if raw in SHORT_DESCRIPTIONS:
        return SHORT_DESCRIPTIONS[raw]
    # Legacy numeric aliases (e.g. BLD-02 → BLD-B) — map via prefix family if needed
    if "-" in raw:
        family, suffix = raw.split("-", 1)
        if suffix.isdigit():
            legacy = {
                ("BLD", "02"): "BLD-B",
                ("BLD", "03"): "BLD-C",
                ("BLD", "04"): "BLD-D",
            }
            mapped = legacy.get((family, suffix))
            if mapped and mapped in SHORT_DESCRIPTIONS:
                return SHORT_DESCRIPTIONS[mapped]
    return ""
