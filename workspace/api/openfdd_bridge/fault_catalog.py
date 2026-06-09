"""Fixed building "check-engine" fault-code catalog.

Letter suffixes only (e.g. ``VAV-C``, ``AHU-B``) — never numeric suffixes like
``VAV-03``, which collide with physical equipment names on retrofit sites.

Codes link to expression-rule cookbook patterns and form a small bipartite graph:
fault_code → category → cookbook_pattern (see ``catalog_graph()``).
"""

from __future__ import annotations

import re
from typing import Any

CATALOG_VERSION = 2

# FAMILY-SUFFIX: 1–3 uppercase letters (no digits)
CODE_PATTERN = re.compile(r"^[A-Z]{2,8}-[A-Z]{1,3}$")

CATEGORIES: dict[str, dict[str, str]] = {
    "performance_degradation": {
        "label": "Performance degradation",
        "detail": "Efficiency or capacity drifting from expected/baseline (kW/ton, COP, delta-T, runtime).",
    },
    "simultaneous_heat_cool": {
        "label": "Simultaneous heating & cooling",
        "detail": "Heating and cooling active at the same time / equipment fighting each other.",
    },
    "sensor_fault": {
        "label": "Sensor fault",
        "detail": "Flatline, out-of-range, drift, or physically inconsistent sensor readings.",
    },
    "io_fault": {
        "label": "I/O fault",
        "detail": "Command vs feedback mismatch, stuck dampers/valves, or stale/dropped points.",
    },
}

SEVERITIES = frozenset({"info", "warning", "critical"})

# Cookbook pattern ids (Rule Lab / rules_py) — edges in catalog_graph()
COOKBOOK_PATTERNS: dict[str, str] = {
    "flatline_1h": "Rolling 1h spread below tolerance (sensor stuck)",
    "spread_1h": "Rolling 1h max−min above threshold (performance / delta)",
    "oob_rolling": "Sample outside cfg low/high band",
    "rate_of_change": "Step-to-step |Δ| exceeds physical limit (spike / bad sample)",
    "mixing_envelope": "MAT outside OAT–RAT band while fan on (AHU-D)",
    "duct_spread_1h": "Duct delta-T spread over 1h (AHU/VAV duct rules)",
    "custom_arrow": "Site-specific apply_faults_arrow logic in rules_py",
    "schedule_compare": "Runtime vs occupancy schedule",
    "stale_points": "Telemetry freshness / poll dropout",
}


def _code(
    code: str,
    category: str,
    title: str,
    severity: str,
    description: str,
    likely_causes: list[str],
    suggested_checks: list[str],
    *,
    cookbook_patterns: list[str] | None = None,
) -> dict[str, Any]:
    patterns = list(cookbook_patterns or [])
    return {
        "code": code,
        "category": category,
        "title": title,
        "severity": severity,
        "description": description,
        "likely_causes": likely_causes,
        "suggested_checks": suggested_checks,
        "cookbook_patterns": patterns,
        "suffix": code.split("-", 1)[-1],
    }


FAULT_CATALOG: dict[str, dict[str, Any]] = {
    "AHU": {
        "label": "Air Handling Unit",
        "description": "Built-up or packaged air handlers (SAT/RAT/MAT, economizer, heating/cooling coils, supply fan).",
        "codes": [
            _code(
                "AHU-A", "performance_degradation", "Supply fan performance degradation", "warning",
                "Supply fan delivering less airflow per unit power or running near-continuously vs baseline.",
                ["Belt slip / failing fan", "Loaded filters", "VFD limit or fault"],
                ["Trend fan speed vs airflow", "Check filter dP", "Compare runtime to schedule"],
                cookbook_patterns=["spread_1h"],
            ),
            _code(
                "AHU-B", "simultaneous_heat_cool", "Simultaneous heating and cooling", "critical",
                "Heating and cooling coil commands are both active at the same time.",
                ["Sequencing/PID conflict", "Leaking coil valve", "Bad sensor driving both loops"],
                ["Trend heating vs cooling output", "Check valve feedback", "Verify SAT setpoint logic"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "AHU-C", "sensor_fault", "Supply air temperature sensor fault", "warning",
                "SAT sensor flatlined, out of range, or drifting from coil behavior.",
                ["Failed/disconnected sensor", "Bad calibration", "Sensor in wrong location"],
                ["Inspect SAT trend for flatline", "Compare to discharge of coil", "Cross-check with handheld"],
                cookbook_patterns=["flatline_1h"],
            ),
            _code(
                "AHU-D", "sensor_fault", "Mixed-air temperature inconsistent with OAT/RAT", "warning",
                "MAT falls outside the range bounded by outdoor and return air temperatures.",
                ["MAT sensor fault", "Stratification", "OAT or RAT sensor fault"],
                ["Verify MAT between OAT and RAT", "Check damper position", "Cross-check OAT source"],
                cookbook_patterns=["mixing_envelope", "custom_arrow", "oob_rolling"],
            ),
            _code(
                "AHU-E", "performance_degradation", "Economizer not economizing", "warning",
                "Free-cooling conditions exist but outdoor-air dampers remain at minimum.",
                ["Economizer disabled/locked out", "Stuck OA damper", "Bad changeover setpoint"],
                ["Trend OA damper vs OAT", "Check economizer enable logic", "Verify damper feedback"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "AHU-F", "io_fault", "Damper/valve command vs feedback mismatch", "warning",
                "Commanded actuator position does not match feedback (stuck or failed actuator).",
                ["Stuck/failed actuator", "Linkage slippage", "Feedback wiring fault"],
                ["Compare command to feedback", "Manually stroke actuator", "Inspect linkage"],
                cookbook_patterns=["custom_arrow"],
            ),
        ],
    },
    "VAV": {
        "label": "VAV terminal unit",
        "description": "Variable-air-volume boxes with optional reheat (zone temp, airflow, damper, reheat valve).",
        "codes": [
            _code(
                "VAV-A", "simultaneous_heat_cool", "Reheat active during cooling demand", "critical",
                "Terminal reheat is energized while the zone/AHU is in a cooling mode.",
                ["Reheat valve leak-by", "Sequencing error", "Zone sensor fault"],
                ["Trend reheat vs airflow/mode", "Check reheat valve feedback", "Verify zone setpoints"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "VAV-B", "performance_degradation", "Airflow not meeting setpoint", "warning",
                "Measured airflow chronically below commanded setpoint (starved box).",
                ["Undersized/starved duct", "Upstream AHU static low", "Damper actuator weak"],
                ["Trend airflow vs setpoint", "Check AHU duct static", "Verify damper stroke"],
                cookbook_patterns=["spread_1h"],
            ),
            _code(
                "VAV-C", "sensor_fault", "Zone temperature sensor fault", "warning",
                "Zone temperature flatlined, out of range, or stuck.",
                ["Failed sensor", "Disconnected wiring", "Sensor behind furniture/heat source"],
                ["Inspect zone temp trend", "Cross-check neighbor zones", "Field verify sensor"],
                cookbook_patterns=["flatline_1h", "oob_rolling"],
            ),
            _code(
                "VAV-D", "io_fault", "Damper command vs airflow mismatch", "warning",
                "Damper command changes but airflow does not respond (stuck damper).",
                ["Stuck damper", "Failed actuator", "Airflow sensor fault"],
                ["Step damper and watch airflow", "Inspect actuator", "Verify flow sensor"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "VAV-E", "performance_degradation", "Rogue zone (chronic reheat/overcooling)", "warning",
                "A single zone drives AHU reset due to chronic reheat or overcooling.",
                ["Oversized/undersized box", "Bad setpoints", "Solar/internal load mismatch"],
                ["Identify reset-driving zone", "Review zone setpoints", "Check load profile"],
                cookbook_patterns=["spread_1h", "custom_arrow"],
            ),
        ],
    },
    "HEATPUMP": {
        "label": "Heat pump / RTU heat pump",
        "description": "Air-source heat pumps and heat-pump RTUs (compressor, reversing valve, aux heat, defrost).",
        "codes": [
            _code(
                "HP-A", "performance_degradation", "Heating/cooling capacity or COP degradation", "warning",
                "Delivered capacity or efficiency below expected for current conditions.",
                ["Low refrigerant charge", "Fouled coil", "Failing compressor"],
                ["Trend delta-T across coil", "Compare COP to baseline", "Check refrigerant pressures"],
                cookbook_patterns=["spread_1h"],
            ),
            _code(
                "HP-B", "simultaneous_heat_cool", "Auxiliary heat with compressor cooling", "critical",
                "Auxiliary/strip heat energized while the unit is in cooling mode.",
                ["Control sequencing fault", "Reversing valve confusion", "Sensor fault"],
                ["Trend aux heat vs mode", "Verify reversing valve state", "Check mode logic"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "HP-C", "io_fault", "Reversing valve fault (mode mismatch)", "warning",
                "Commanded mode (heat/cool) does not match measured supply behavior.",
                ["Stuck reversing valve", "Failed solenoid", "Wiring fault"],
                ["Compare mode command to supply temp", "Cycle reversing valve", "Check solenoid"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "HP-D", "sensor_fault", "Discharge/suction temperature sensor fault", "warning",
                "Refrigerant or air temperature sensor flatlined or out of range.",
                ["Failed sensor", "Calibration drift", "Disconnected probe"],
                ["Inspect sensor trend", "Cross-check with pressures", "Field verify"],
                cookbook_patterns=["flatline_1h", "oob_rolling"],
            ),
            _code(
                "HP-E", "performance_degradation", "Excessive defrost cycling", "warning",
                "Defrost cycles far more frequently than expected for conditions.",
                ["Defrost sensor fault", "Low airflow", "Iced coil / drainage"],
                ["Trend defrost frequency vs OAT", "Check coil airflow", "Inspect defrost sensor"],
                cookbook_patterns=["spread_1h"],
            ),
        ],
    },
    "GEO": {
        "label": "Ground-source (geo) loop",
        "description": "Geothermal/ground-source heat-pump loops (loop water temps, loop pumps, isolation valves).",
        "codes": [
            _code(
                "GEO-A", "performance_degradation", "Ground loop temperature out of band", "warning",
                "Loop entering/leaving water temperature outside expected seasonal band (loop degradation).",
                ["Loop undersized / heat saturation", "Low flow", "Air in loop"],
                ["Trend loop EWT/LWT vs season", "Verify flow rate", "Purge/inspect loop"],
                cookbook_patterns=["oob_rolling"],
            ),
            _code(
                "GEO-B", "performance_degradation", "Loop pump performance / low delta-T", "warning",
                "Loop pump delivering low delta-T or running near-continuously.",
                ["Failing pump/impeller", "Closed/throttled valve", "VFD limit"],
                ["Trend loop delta-T", "Check pump speed vs flow", "Verify valve positions"],
                cookbook_patterns=["spread_1h"],
            ),
            _code(
                "GEO-C", "sensor_fault", "Loop water temperature sensor fault", "warning",
                "Loop EWT/LWT sensor flatlined or physically inconsistent.",
                ["Failed sensor", "Poor thermal contact", "Calibration drift"],
                ["Inspect loop temp trend", "Compare EWT vs LWT plausibility", "Field verify"],
                cookbook_patterns=["flatline_1h"],
            ),
            _code(
                "GEO-D", "io_fault", "Loop isolation valve command vs feedback mismatch", "warning",
                "Isolation valve command does not match feedback or flow response.",
                ["Stuck valve", "Failed actuator", "Feedback fault"],
                ["Compare command vs feedback", "Watch flow on valve change", "Inspect actuator"],
                cookbook_patterns=["custom_arrow"],
            ),
        ],
    },
    "CHILLER": {
        "label": "Chiller plant",
        "description": "Chilled-water plants (chillers, CHW/CW pumps, towers, CHW supply temp, delta-T).",
        "codes": [
            _code(
                "CH-A", "performance_degradation", "Condenser approach temperature high", "warning",
                "Condenser approach rising vs baseline (fouling / tower or flow problems).",
                ["Condenser tube fouling", "Low CW flow", "Tower capacity loss"],
                ["Trend condenser approach", "Check CW flow", "Inspect tower/fill"],
                cookbook_patterns=["spread_1h"],
            ),
            _code(
                "CH-B", "performance_degradation", "Low delta-T syndrome", "warning",
                "Chilled-water delta-T chronically below design (excess flow / valve issues).",
                ["Stuck coil valves", "Decoupler bypass", "3-way valves / improper balancing"],
                ["Trend plant delta-T", "Audit coil valves", "Check decoupler flow"],
                cookbook_patterns=["spread_1h", "duct_spread_1h"],
            ),
            _code(
                "CH-C", "simultaneous_heat_cool", "Mechanical cooling with heating in same loop/zone", "critical",
                "Chiller cooling while a heating source serves the same air/water path.",
                ["Sequencing fault", "Changeover error", "Sensor fault"],
                ["Trend chiller vs heating plant", "Verify changeover logic", "Check loop topology"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "CH-D", "sensor_fault", "Chilled-water supply temperature sensor fault", "warning",
                "CHWS temperature flatlined, out of range, or inconsistent with load.",
                ["Failed sensor", "Calibration drift", "Sensor location"],
                ["Inspect CHWS trend", "Cross-check return temp", "Field verify"],
                cookbook_patterns=["flatline_1h"],
            ),
            _code(
                "CH-E", "io_fault", "CHW valve/pump command vs feedback mismatch", "warning",
                "Pump or valve command does not match feedback or flow.",
                ["Stuck valve", "Failed pump/VFD", "Feedback fault"],
                ["Compare command vs feedback", "Verify flow response", "Inspect actuator/VFD"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "CH-F", "performance_degradation", "Chiller efficiency drift (kW/ton)", "warning",
                "Plant kW/ton trending worse than baseline at similar load.",
                ["Fouling", "Refrigerant issues", "Suboptimal staging/reset"],
                ["Trend kW/ton vs load", "Review staging/reset", "Schedule service"],
                cookbook_patterns=["spread_1h"],
            ),
        ],
    },
    "DATACENTER": {
        "label": "Data center cooling (CRAH/CRAC)",
        "description": "Computer-room air handlers/units (supply/return air temp, humidity, fans, cooling valves).",
        "codes": [
            _code(
                "DC-A", "simultaneous_heat_cool", "Units fighting (simultaneous humidify/dehumidify or heat/cool)", "critical",
                "Adjacent room units run opposing modes (one humidifies while another dehumidifies, or heat vs cool).",
                ["No master/coordination", "Setpoint deadband too tight", "Sensor disagreement"],
                ["Compare unit modes across room", "Widen/align deadbands", "Cross-check room sensors"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "DC-B", "performance_degradation", "Cooling capacity degradation / high return temp", "warning",
                "Return-air temperature climbing or cooling output saturated vs IT load.",
                ["Fouled coil/filter", "Low chilled water flow", "Airflow bypass"],
                ["Trend return temp vs IT load", "Check coil/flow", "Inspect containment"],
                cookbook_patterns=["spread_1h", "oob_rolling"],
            ),
            _code(
                "DC-C", "sensor_fault", "Supply/return air temperature sensor fault", "warning",
                "CRAH supply or return temperature sensor flatlined or out of range.",
                ["Failed sensor", "Calibration drift", "Sensor placement"],
                ["Inspect temp trend", "Cross-check neighbors", "Field verify"],
                cookbook_patterns=["flatline_1h"],
            ),
            _code(
                "DC-D", "io_fault", "CRAH valve/fan command vs feedback mismatch", "warning",
                "Cooling valve or fan command does not match feedback.",
                ["Stuck valve", "Failed EC fan", "Feedback fault"],
                ["Compare command vs feedback", "Verify fan/valve response", "Inspect hardware"],
                cookbook_patterns=["custom_arrow"],
            ),
            _code(
                "DC-E", "performance_degradation", "Overcooling / bypass air (low return temp)", "warning",
                "Return-air temperature very low, indicating bypass air and wasted cooling.",
                ["Bypass/short-circuit air", "Oversized cooling", "Poor containment"],
                ["Trend return temp", "Inspect containment/blanking", "Right-size staging"],
                cookbook_patterns=["spread_1h"],
            ),
        ],
    },
    "BUILDING": {
        "label": "Whole building / office",
        "description": "Building-level items (energy baseline, shared OAT sensor, schedules, point data quality).",
        "codes": [
            _code(
                "BLD-A", "performance_degradation", "Whole-building energy deviation", "warning",
                "Building energy use deviating from weather-normalized baseline.",
                ["Equipment running off-schedule", "Degraded plant", "Control reset failures"],
                ["Trend energy vs baseline", "Review schedules", "Check plant efficiency codes"],
                cookbook_patterns=["spread_1h", "schedule_compare"],
            ),
            _code(
                "BLD-B", "sensor_fault", "Outdoor-air temperature sensor fault", "warning",
                "Shared OAT sensor flatlined, sun-baked, or out of range (drives many sequences).",
                ["Sensor in sun", "Failed sensor", "Calibration drift"],
                ["Compare OAT to weather service", "Inspect sensor shielding", "Field verify"],
                cookbook_patterns=["flatline_1h", "oob_rolling", "rate_of_change"],
            ),
            _code(
                "BLD-C", "performance_degradation", "Equipment running outside occupancy schedule", "warning",
                "HVAC operating during unoccupied hours without override justification.",
                ["Schedule misconfigured", "Stuck override", "Time-clock drift"],
                ["Trend equipment vs schedule", "Audit overrides", "Verify controller clock"],
                cookbook_patterns=["schedule_compare"],
            ),
            _code(
                "BLD-D", "io_fault", "Point data dropout (stale points)", "critical",
                "Telemetry points stopped updating (driver/comm loss) so FDD cannot evaluate.",
                ["BACnet comm loss", "Poll driver down", "Controller offline"],
                ["Check poll CSV freshness", "Verify BACnet driver", "Ping controllers"],
                cookbook_patterns=["stale_points"],
            ),
        ],
    },
}

# Legacy numeric codes (v1) → letter codes (v2) for migrations and docs
LEGACY_CODE_MAP: dict[str, str] = {
    "AHU-01": "AHU-A", "AHU-02": "AHU-B", "AHU-03": "AHU-C", "AHU-04": "AHU-D", "AHU-05": "AHU-E", "AHU-06": "AHU-F",
    "VAV-01": "VAV-A", "VAV-02": "VAV-B", "VAV-03": "VAV-C", "VAV-04": "VAV-D", "VAV-05": "VAV-E",
    "HP-01": "HP-A", "HP-02": "HP-B", "HP-03": "HP-C", "HP-04": "HP-D", "HP-05": "HP-E",
    "GEO-01": "GEO-A", "GEO-02": "GEO-B", "GEO-03": "GEO-C", "GEO-04": "GEO-D",
    "CH-01": "CH-A", "CH-02": "CH-B", "CH-03": "CH-C", "CH-04": "CH-D", "CH-05": "CH-E", "CH-06": "CH-F",
    "DC-01": "DC-A", "DC-02": "DC-B", "DC-03": "DC-C", "DC-04": "DC-D", "DC-05": "DC-E",
    "BLD-01": "BLD-A", "BLD-02": "BLD-B", "BLD-03": "BLD-C", "BLD-04": "BLD-D",
}


def normalize_code(code: str | None) -> str | None:
    """Map legacy numeric suffix codes to letter codes; pass through valid v2 codes."""
    if not code:
        return None
    raw = str(code).strip().upper()
    if raw in LEGACY_CODE_MAP:
        return LEGACY_CODE_MAP[raw]
    return raw


def all_codes() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for family, block in FAULT_CATALOG.items():
        for entry in block["codes"]:
            out[entry["code"]] = {**entry, "family": family, "family_label": block["label"]}
    return out


def is_valid_code(code: str | None) -> bool:
    """True only for letter-suffix catalog codes (numeric legacy codes like VAV-03 are rejected)."""
    if not code:
        return False
    raw = str(code).strip().upper()
    if not CODE_PATTERN.match(raw):
        return False
    return raw in all_codes()


def entry_for_code(code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    return all_codes().get(normalize_code(code) or "")


def family_for_code(code: str | None) -> str | None:
    entry = entry_for_code(code)
    return entry["family"] if entry else None


def family_label(family: str | None) -> str:
    if not family:
        return "General"
    block = FAULT_CATALOG.get(str(family).strip().upper())
    return block["label"] if block else str(family)


def catalog_payload() -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "code_format": "FAMILY-SUFFIX (1–3 letters, no digits — avoids collision with equipment names like VAV-03)",
        "categories": CATEGORIES,
        "cookbook_patterns": COOKBOOK_PATTERNS,
        "families": [
            {"family": fam, "label": block["label"], "description": block["description"], "codes": block["codes"]}
            for fam, block in FAULT_CATALOG.items()
        ],
    }


def catalog_tree() -> dict[str, Any]:
    families: list[dict[str, Any]] = []
    for fam, block in FAULT_CATALOG.items():
        cats: list[dict[str, Any]] = []
        for cat_id, cat_meta in CATEGORIES.items():
            codes = [c for c in block["codes"] if c["category"] == cat_id]
            if codes:
                cats.append({"category": cat_id, "label": cat_meta["label"], "codes": codes})
        families.append(
            {"family": fam, "label": block["label"], "description": block["description"], "categories": cats}
        )
    return {"version": CATALOG_VERSION, "families": families}


def catalog_graph() -> dict[str, Any]:
    """Bipartite-style link graph: fault codes ↔ categories ↔ cookbook patterns."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen_nodes: set[str] = set()

    def add_node(node_id: str, node_type: str, label: str, **extra: Any) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({"id": node_id, "type": node_type, "label": label, **extra})

    for cat_id, meta in CATEGORIES.items():
        add_node(f"cat:{cat_id}", "category", meta["label"], category=cat_id)

    for pat_id, pat_label in COOKBOOK_PATTERNS.items():
        add_node(f"pat:{pat_id}", "cookbook_pattern", pat_label, pattern=pat_id)

    for code, entry in all_codes().items():
        add_node(
            code,
            "fault_code",
            entry["title"],
            family=entry["family"],
            severity=entry["severity"],
            suffix=entry.get("suffix"),
        )
        edges.append({"from": code, "to": f"cat:{entry['category']}", "relation": "has_category"})
        for pat in entry.get("cookbook_patterns") or []:
            if pat in COOKBOOK_PATTERNS:
                edges.append({"from": code, "to": f"pat:{pat}", "relation": "implemented_by"})

    return {
        "version": CATALOG_VERSION,
        "description": "Fault codes (letter suffix) link to FDD categories and Rule Lab cookbook patterns.",
        "nodes": nodes,
        "edges": edges,
    }
