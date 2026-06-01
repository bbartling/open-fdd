"""Fixed building "check-engine" fault-code catalog.

This is the OBD-II analogue for buildings: a **finite, fixed** set of fault
codes per HVAC equipment family. The local AI agent maps observed conditions to
these codes; it must NOT invent new ones (see
``skills/building-check-engine/SKILL.md``). FDD here focuses on four families of
problem only:

* ``performance_degradation`` — efficiency / capacity drifting from baseline
* ``simultaneous_heat_cool`` — heating and cooling fighting each other
* ``sensor_fault`` — flatline / out-of-range / drift / inconsistent sensors
* ``io_fault`` — command vs feedback mismatch, stuck actuators, stale points

It is explicitly **not** a classic BAS nuisance-alarm / dial-out list (no
"space temp 0.5 deg above setpoint" pager spam). Codes are stable identifiers so
the dashboard can render a fixed GREEN/YELLOW/RED light with an equipment tree.
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = 1

# --- FDD categories (the only things this check-engine system reasons about) ---
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


def _code(
    code: str,
    category: str,
    title: str,
    severity: str,
    description: str,
    likely_causes: list[str],
    suggested_checks: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "title": title,
        "severity": severity,
        "description": description,
        "likely_causes": likely_causes,
        "suggested_checks": suggested_checks,
    }


# --- Fixed catalog: family -> {label, description, codes[]} ----------------------
FAULT_CATALOG: dict[str, dict[str, Any]] = {
    "AHU": {
        "label": "Air Handling Unit",
        "description": "Built-up or packaged air handlers (SAT/RAT/MAT, economizer, heating/cooling coils, supply fan).",
        "codes": [
            _code(
                "AHU-01", "performance_degradation", "Supply fan performance degradation", "warning",
                "Supply fan delivering less airflow per unit power or running near-continuously vs baseline.",
                ["Belt slip / failing fan", "Loaded filters", "VFD limit or fault"],
                ["Trend fan speed vs airflow", "Check filter dP", "Compare runtime to schedule"],
            ),
            _code(
                "AHU-02", "simultaneous_heat_cool", "Simultaneous heating and cooling", "critical",
                "Heating and cooling coil commands are both active at the same time.",
                ["Sequencing/PID conflict", "Leaking coil valve", "Bad sensor driving both loops"],
                ["Trend heating vs cooling output", "Check valve feedback", "Verify SAT setpoint logic"],
            ),
            _code(
                "AHU-03", "sensor_fault", "Supply air temperature sensor fault", "warning",
                "SAT sensor flatlined, out of range, or drifting from coil behavior.",
                ["Failed/disconnected sensor", "Bad calibration", "Sensor in wrong location"],
                ["Inspect SAT trend for flatline", "Compare to discharge of coil", "Cross-check with handheld"],
            ),
            _code(
                "AHU-04", "sensor_fault", "Mixed-air temperature inconsistent with OAT/RAT", "warning",
                "MAT falls outside the range bounded by outdoor and return air temperatures.",
                ["MAT sensor fault", "Stratification", "OAT or RAT sensor fault"],
                ["Verify MAT between OAT and RAT", "Check damper position", "Cross-check OAT source"],
            ),
            _code(
                "AHU-05", "performance_degradation", "Economizer not economizing", "warning",
                "Free-cooling conditions exist but outdoor-air dampers remain at minimum.",
                ["Economizer disabled/locked out", "Stuck OA damper", "Bad changeover setpoint"],
                ["Trend OA damper vs OAT", "Check economizer enable logic", "Verify damper feedback"],
            ),
            _code(
                "AHU-06", "io_fault", "Damper/valve command vs feedback mismatch", "warning",
                "Commanded actuator position does not match feedback (stuck or failed actuator).",
                ["Stuck/failed actuator", "Linkage slippage", "Feedback wiring fault"],
                ["Compare command to feedback", "Manually stroke actuator", "Inspect linkage"],
            ),
        ],
    },
    "VAV": {
        "label": "VAV terminal unit",
        "description": "Variable-air-volume boxes with optional reheat (zone temp, airflow, damper, reheat valve).",
        "codes": [
            _code(
                "VAV-01", "simultaneous_heat_cool", "Reheat active during cooling demand", "critical",
                "Terminal reheat is energized while the zone/AHU is in a cooling mode.",
                ["Reheat valve leak-by", "Sequencing error", "Zone sensor fault"],
                ["Trend reheat vs airflow/mode", "Check reheat valve feedback", "Verify zone setpoints"],
            ),
            _code(
                "VAV-02", "performance_degradation", "Airflow not meeting setpoint", "warning",
                "Measured airflow chronically below commanded setpoint (starved box).",
                ["Undersized/starved duct", "Upstream AHU static low", "Damper actuator weak"],
                ["Trend airflow vs setpoint", "Check AHU duct static", "Verify damper stroke"],
            ),
            _code(
                "VAV-03", "sensor_fault", "Zone temperature sensor fault", "warning",
                "Zone temperature flatlined, out of range, or stuck.",
                ["Failed sensor", "Disconnected wiring", "Sensor behind furniture/heat source"],
                ["Inspect zone temp trend", "Cross-check neighbor zones", "Field verify sensor"],
            ),
            _code(
                "VAV-04", "io_fault", "Damper command vs airflow mismatch", "warning",
                "Damper command changes but airflow does not respond (stuck damper).",
                ["Stuck damper", "Failed actuator", "Airflow sensor fault"],
                ["Step damper and watch airflow", "Inspect actuator", "Verify flow sensor"],
            ),
            _code(
                "VAV-05", "performance_degradation", "Rogue zone (chronic reheat/overcooling)", "warning",
                "A single zone drives AHU reset due to chronic reheat or overcooling.",
                ["Oversized/undersized box", "Bad setpoints", "Solar/internal load mismatch"],
                ["Identify reset-driving zone", "Review zone setpoints", "Check load profile"],
            ),
        ],
    },
    "HEATPUMP": {
        "label": "Heat pump / RTU heat pump",
        "description": "Air-source heat pumps and heat-pump RTUs (compressor, reversing valve, aux heat, defrost).",
        "codes": [
            _code(
                "HP-01", "performance_degradation", "Heating/cooling capacity or COP degradation", "warning",
                "Delivered capacity or efficiency below expected for current conditions.",
                ["Low refrigerant charge", "Fouled coil", "Failing compressor"],
                ["Trend delta-T across coil", "Compare COP to baseline", "Check refrigerant pressures"],
            ),
            _code(
                "HP-02", "simultaneous_heat_cool", "Auxiliary heat with compressor cooling", "critical",
                "Auxiliary/strip heat energized while the unit is in cooling mode.",
                ["Control sequencing fault", "Reversing valve confusion", "Sensor fault"],
                ["Trend aux heat vs mode", "Verify reversing valve state", "Check mode logic"],
            ),
            _code(
                "HP-03", "io_fault", "Reversing valve fault (mode mismatch)", "warning",
                "Commanded mode (heat/cool) does not match measured supply behavior.",
                ["Stuck reversing valve", "Failed solenoid", "Wiring fault"],
                ["Compare mode command to supply temp", "Cycle reversing valve", "Check solenoid"],
            ),
            _code(
                "HP-04", "sensor_fault", "Discharge/suction temperature sensor fault", "warning",
                "Refrigerant or air temperature sensor flatlined or out of range.",
                ["Failed sensor", "Calibration drift", "Disconnected probe"],
                ["Inspect sensor trend", "Cross-check with pressures", "Field verify"],
            ),
            _code(
                "HP-05", "performance_degradation", "Excessive defrost cycling", "warning",
                "Defrost cycles far more frequently than expected for conditions.",
                ["Defrost sensor fault", "Low airflow", "Iced coil / drainage"],
                ["Trend defrost frequency vs OAT", "Check coil airflow", "Inspect defrost sensor"],
            ),
        ],
    },
    "GEO": {
        "label": "Ground-source (geo) loop",
        "description": "Geothermal/ground-source heat-pump loops (loop water temps, loop pumps, isolation valves).",
        "codes": [
            _code(
                "GEO-01", "performance_degradation", "Ground loop temperature out of band", "warning",
                "Loop entering/leaving water temperature outside expected seasonal band (loop degradation).",
                ["Loop undersized / heat saturation", "Low flow", "Air in loop"],
                ["Trend loop EWT/LWT vs season", "Verify flow rate", "Purge/inspect loop"],
            ),
            _code(
                "GEO-02", "performance_degradation", "Loop pump performance / low delta-T", "warning",
                "Loop pump delivering low delta-T or running near-continuously.",
                ["Failing pump/impeller", "Closed/throttled valve", "VFD limit"],
                ["Trend loop delta-T", "Check pump speed vs flow", "Verify valve positions"],
            ),
            _code(
                "GEO-03", "sensor_fault", "Loop water temperature sensor fault", "warning",
                "Loop EWT/LWT sensor flatlined or physically inconsistent.",
                ["Failed sensor", "Poor thermal contact", "Calibration drift"],
                ["Inspect loop temp trend", "Compare EWT vs LWT plausibility", "Field verify"],
            ),
            _code(
                "GEO-04", "io_fault", "Loop isolation valve command vs feedback mismatch", "warning",
                "Isolation valve command does not match feedback or flow response.",
                ["Stuck valve", "Failed actuator", "Feedback fault"],
                ["Compare command vs feedback", "Watch flow on valve change", "Inspect actuator"],
            ),
        ],
    },
    "CHILLER": {
        "label": "Chiller plant",
        "description": "Chilled-water plants (chillers, CHW/CW pumps, towers, CHW supply temp, delta-T).",
        "codes": [
            _code(
                "CH-01", "performance_degradation", "Condenser approach temperature high", "warning",
                "Condenser approach rising vs baseline (fouling / tower or flow problems).",
                ["Condenser tube fouling", "Low CW flow", "Tower capacity loss"],
                ["Trend condenser approach", "Check CW flow", "Inspect tower/fill"],
            ),
            _code(
                "CH-02", "performance_degradation", "Low delta-T syndrome", "warning",
                "Chilled-water delta-T chronically below design (excess flow / valve issues).",
                ["Stuck coil valves", "Decoupler bypass", "3-way valves / improper balancing"],
                ["Trend plant delta-T", "Audit coil valves", "Check decoupler flow"],
            ),
            _code(
                "CH-03", "simultaneous_heat_cool", "Mechanical cooling with heating in same loop/zone", "critical",
                "Chiller cooling while a heating source serves the same air/water path.",
                ["Sequencing fault", "Changeover error", "Sensor fault"],
                ["Trend chiller vs heating plant", "Verify changeover logic", "Check loop topology"],
            ),
            _code(
                "CH-04", "sensor_fault", "Chilled-water supply temperature sensor fault", "warning",
                "CHWS temperature flatlined, out of range, or inconsistent with load.",
                ["Failed sensor", "Calibration drift", "Sensor location"],
                ["Inspect CHWS trend", "Cross-check return temp", "Field verify"],
            ),
            _code(
                "CH-05", "io_fault", "CHW valve/pump command vs feedback mismatch", "warning",
                "Pump or valve command does not match feedback or flow.",
                ["Stuck valve", "Failed pump/VFD", "Feedback fault"],
                ["Compare command vs feedback", "Verify flow response", "Inspect actuator/VFD"],
            ),
            _code(
                "CH-06", "performance_degradation", "Chiller efficiency drift (kW/ton)", "warning",
                "Plant kW/ton trending worse than baseline at similar load.",
                ["Fouling", "Refrigerant issues", "Suboptimal staging/reset"],
                ["Trend kW/ton vs load", "Review staging/reset", "Schedule service"],
            ),
        ],
    },
    "DATACENTER": {
        "label": "Data center cooling (CRAH/CRAC)",
        "description": "Computer-room air handlers/units (supply/return air temp, humidity, fans, cooling valves).",
        "codes": [
            _code(
                "DC-01", "simultaneous_heat_cool", "Units fighting (simultaneous humidify/dehumidify or heat/cool)", "critical",
                "Adjacent room units run opposing modes (one humidifies while another dehumidifies, or heat vs cool).",
                ["No master/coordination", "Setpoint deadband too tight", "Sensor disagreement"],
                ["Compare unit modes across room", "Widen/align deadbands", "Cross-check room sensors"],
            ),
            _code(
                "DC-02", "performance_degradation", "Cooling capacity degradation / high return temp", "warning",
                "Return-air temperature climbing or cooling output saturated vs IT load.",
                ["Fouled coil/filter", "Low chilled water flow", "Airflow bypass"],
                ["Trend return temp vs IT load", "Check coil/flow", "Inspect containment"],
            ),
            _code(
                "DC-03", "sensor_fault", "Supply/return air temperature sensor fault", "warning",
                "CRAH supply or return temperature sensor flatlined or out of range.",
                ["Failed sensor", "Calibration drift", "Sensor placement"],
                ["Inspect temp trend", "Cross-check neighbors", "Field verify"],
            ),
            _code(
                "DC-04", "io_fault", "CRAH valve/fan command vs feedback mismatch", "warning",
                "Cooling valve or fan command does not match feedback.",
                ["Stuck valve", "Failed EC fan", "Feedback fault"],
                ["Compare command vs feedback", "Verify fan/valve response", "Inspect hardware"],
            ),
            _code(
                "DC-05", "performance_degradation", "Overcooling / bypass air (low return temp)", "warning",
                "Return-air temperature very low, indicating bypass air and wasted cooling.",
                ["Bypass/short-circuit air", "Oversized cooling", "Poor containment"],
                ["Trend return temp", "Inspect containment/blanking", "Right-size staging"],
            ),
        ],
    },
    "BUILDING": {
        "label": "Whole building / office",
        "description": "Building-level items (energy baseline, shared OAT sensor, schedules, point data quality).",
        "codes": [
            _code(
                "BLD-01", "performance_degradation", "Whole-building energy deviation", "warning",
                "Building energy use deviating from weather-normalized baseline.",
                ["Equipment running off-schedule", "Degraded plant", "Control reset failures"],
                ["Trend energy vs baseline", "Review schedules", "Check plant efficiency codes"],
            ),
            _code(
                "BLD-02", "sensor_fault", "Outdoor-air temperature sensor fault", "warning",
                "Shared OAT sensor flatlined, sun-baked, or out of range (drives many sequences).",
                ["Sensor in sun", "Failed sensor", "Calibration drift"],
                ["Compare OAT to weather service", "Inspect sensor shielding", "Field verify"],
            ),
            _code(
                "BLD-03", "performance_degradation", "Equipment running outside occupancy schedule", "warning",
                "HVAC operating during unoccupied hours without override justification.",
                ["Schedule misconfigured", "Stuck override", "Time-clock drift"],
                ["Trend equipment vs schedule", "Audit overrides", "Verify controller clock"],
            ),
            _code(
                "BLD-04", "io_fault", "Point data dropout (stale points)", "critical",
                "Telemetry points stopped updating (driver/comm loss) so FDD cannot evaluate.",
                ["BACnet comm loss", "Poll driver down", "Controller offline"],
                ["Check poll CSV freshness", "Verify BACnet driver", "Ping controllers"],
            ),
        ],
    },
}


def all_codes() -> dict[str, dict[str, Any]]:
    """Flat map of code -> entry (with family attached)."""
    out: dict[str, dict[str, Any]] = {}
    for family, block in FAULT_CATALOG.items():
        for entry in block["codes"]:
            out[entry["code"]] = {**entry, "family": family, "family_label": block["label"]}
    return out


def is_valid_code(code: str | None) -> bool:
    if not code:
        return False
    return str(code).strip().upper() in all_codes()


def entry_for_code(code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    return all_codes().get(str(code).strip().upper())


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
        "categories": CATEGORIES,
        "families": [
            {"family": fam, "label": block["label"], "description": block["description"], "codes": block["codes"]}
            for fam, block in FAULT_CATALOG.items()
        ],
    }


def catalog_tree() -> dict[str, Any]:
    """Family -> category -> codes, for the dashboard reference tree."""
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
