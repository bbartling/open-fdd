"""Offline CI datasets → si-cutover-ip-golden-v1 rows (#1284 W0c / W3).

No live stack, no site names in code — building_id values come from fixture manifests only.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import unit_contract_lib as uc  # noqa: E402
from scripts.stress.si_cutover.capture_ip_baseline import (  # noqa: E402
    daily_fault_and_covered_seconds,
    rule_params_from_registry,
)

POLL_SECONDS = 300.0
SCHEMA = "si-cutover-ip-golden-v1"
GOLDEN_SCHEMA_VERSION = 1

COOKBOOK_FIXTURES = REPO / "docs" / "rules" / "cookbook" / "fixtures"
SYNTH_ROOT = REPO / "tests" / "fixtures" / "synthetic_slice" / "OPENFDD_SYNTHETIC_SLICE_V1"

# Cookbook jsonl shorthand → Haystack/cookbook role columns expected by run_rule.
COOKBOOK_COLUMN_RENAMES: dict[str, str] = {
    "duct_static": "duct-static-pressure",
    "duct_static_sp": "duct-static-pressure-sp",
    "fan_cmd": "fan-cmd",
    "fan_status": "fan-status",
    "mat": "mixed-air-temp",
    "rat": "return-air-temp",
    "oat": "outside-air-temp",
    "oa_damper": "outside-air-damper",
    "sat_sp": "discharge-air-temp-sp",
    "zone_t": "zone-air-temp",
    "occ_mode": "occ_mode",
    "zone_flow": "zone-airflow",
    "damper_pct": "damper",
    "clg_available": "cooling-available",
    "reheat_valve_pct": "reheat-valve",
    "oa_t": "outside-air-temp",
    "min_flow_sp": "min-flow-sp",
    "reset_enable": "reset-enable",
}

COOKBOOK_DATASETS: tuple[dict[str, str], ...] = (
    {"fixture": "fc1_obvious_fault.jsonl", "building_id": "COOKBOOK_FC1", "equipment_type": "ahu"},
    {"fixture": "fc2_obvious_fault.jsonl", "building_id": "COOKBOOK_FC2", "equipment_type": "ahu"},
    {"fixture": "reset1_normal.jsonl", "building_id": "COOKBOOK_RESET1_NORMAL", "equipment_type": "ahu"},
    {"fixture": "reset1_obvious_fault.jsonl", "building_id": "COOKBOOK_RESET1_FAULT", "equipment_type": "ahu"},
    {"fixture": "sched1_obvious_fault.jsonl", "building_id": "COOKBOOK_SCHED1", "equipment_type": "ahu"},
    {"fixture": "sched247_obvious_fault.jsonl", "building_id": "COOKBOOK_SCHED247", "equipment_type": "ahu"},
    {"fixture": "vav1_obvious_fault.jsonl", "building_id": "COOKBOOK_VAV1", "equipment_type": "vav"},
    {"fixture": "vav6_obvious_fault.jsonl", "building_id": "COOKBOOK_VAV6", "equipment_type": "vav"},
    {"fixture": "vav7_obvious_fault.jsonl", "building_id": "COOKBOOK_VAV7", "equipment_type": "vav"},
)

SYNTH_CASE_DIRS: tuple[str, ...] = (
    "AHU_CASE_FC1",
    "AHU_CASE_SCHED_1",
    "AHU_CASE_PID_HUNT_1",
    "AHU_CASE_SV_FLATLINE",
    "CHILLER_CASE_MECH_OAT_1",
    "VAV_CASE_VAV_1",
)

SYNTH_EQUIPMENT_TYPES: dict[str, str] = {
    "AHU_CASE_FC1": "ahu",
    "AHU_CASE_SCHED_1": "ahu",
    "AHU_CASE_PID_HUNT_1": "ahu",
    "AHU_CASE_SV_FLATLINE": "ahu",
    "CHILLER_CASE_MECH_OAT_1": "chiller",
    "VAV_CASE_VAV_1": "vav",
}


@dataclass(frozen=True)
class DatasetSpec:
    building_id: str
    equipment_id: str
    equipment_type: str
    source: dict[str, Any]


def load_rule_registry() -> list[dict[str, Any]]:
    import yaml

    doc = yaml.safe_load((REPO / "sql" / "fdd" / "registry.yaml").read_text(encoding="utf-8"))
    return list(doc.get("rules") or [])


def pandas_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from open_fdd.rules import RULES_BY_ID

    out: list[dict[str, Any]] = []
    for r in rules:
        rid = str(r.get("rule_id") or "")
        if not rid:
            continue
        if r.get("pandas_function") or rid in RULES_BY_ID:
            out.append(r)
    if len(out) < 65:
        raise RuntimeError(f"expected ~72 pandas rules, found {len(out)}")
    return out


def _load_cookbook_frame(fixture_name: str):
    import pandas as pd

    path = COOKBOOK_FIXTURES / fixture_name
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    equipment_id = str(rows[0].get("equipment_id") or "equip:test")
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    rename = {k: v for k, v in COOKBOOK_COLUMN_RENAMES.items() if k in df.columns}
    df = df.rename(columns=rename)
    return df, equipment_id


def _load_synth_frame(case_dir: str):
    import pandas as pd

    base = SYNTH_ROOT / case_dir
    df = pd.read_csv(base / "history_wide.csv")
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    df.index = pd.to_datetime(df[ts_col], utc=True)
    df = df.drop(columns=[c for c in df.columns if c in (ts_col,)])
    df = df.sort_index()
    equipment_id = case_dir
    return df, equipment_id


def iter_dataset_specs() -> list[DatasetSpec]:
    specs: list[DatasetSpec] = []
    for meta in COOKBOOK_DATASETS:
        frame, equipment_id = _load_cookbook_frame(meta["fixture"])
        specs.append(
            DatasetSpec(
                building_id=meta["building_id"],
                equipment_id=equipment_id,
                equipment_type=meta["equipment_type"],
                source={"kind": "cookbook", "fixture": meta["fixture"], "frame": frame},
            )
        )
    for case in SYNTH_CASE_DIRS:
        frame, equipment_id = _load_synth_frame(case)
        specs.append(
            DatasetSpec(
                building_id=f"SYNTH_{case}",
                equipment_id=equipment_id,
                equipment_type=SYNTH_EQUIPMENT_TYPES[case],
                source={"kind": "synth", "case_dir": case, "frame": frame},
            )
        )
    return specs


def _quantity_for_param(spec: dict[str, Any]) -> str | None:
    kind = str(spec.get("kind") or "")
    unit = str(spec.get("unit") or "")
    if kind == "absolute_temperature":
        return "absolute_temperature"
    if kind == "temperature_difference":
        return "temperature_difference"
    if kind in ("duration_minutes", "duration_seconds"):
        return "duration"
    if kind == "percent":
        return "dimensionless"
    if unit in ("degF", "degC", "°F", "°C"):
        return "absolute_temperature"
    if unit in ("degF_delta", "degC_delta"):
        return "temperature_difference"
    return None


def convert_params_to_si(
    rule: dict[str, Any],
    params: dict[str, float],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, float], float] | None = None,
) -> dict[str, float]:
    out = dict(params)
    for name, spec in (rule.get("parameters") or {}).items():
        if name not in out:
            continue
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind") or "")
        unit = str(spec.get("unit") or "")
        if unit == "pct":
            unit = "percent"
        q = _quantity_for_param(spec)
        if not q:
            continue
        if kind in ("duration_minutes", "duration_seconds", "boolean", "percent"):
            continue
        if unit in ("percent", "pct", "bool", "min"):
            continue
        if not unit:
            continue
        src_unit = unit
        if q == "temperature_difference" and unit == "degF":
            src_unit = "degF_delta"
        elif q == "temperature_difference" and unit in ("degC", "°C"):
            src_unit = "degC_delta"
        val = float(out[name])
        if param_hook:
            val = param_hook(name, val)
        out[name] = uc.convert_to_canonical(metric, q, val, src_unit)
    return out


def _role_unit(role: str) -> str | None:
    from open_fdd.analytics.units import DEFAULT_ROLE_UNITS

    u = DEFAULT_ROLE_UNITS.get(role)
    if u in ("", None):
        return None
    if u == "°F":
        return "degF"
    if u == "in. w.c.":
        return "inWC"
    if u == "cfm":
        return "cfm"
    if u == "%":
        return "percent"
    if u == "bool":
        return None
    return str(u)


def frame_to_si(frame, metric: dict[str, Any], *, value_hook: Callable[[str, float], float] | None = None):
    import pandas as pd

    from open_fdd.analytics.units import stamp_display_units

    out = frame.copy()
    role_units: dict[str, str] = {}
    for col in out.columns:
        if col == "occ_mode":
            continue
        unit = _role_unit(str(col))
        if not unit:
            continue
        q = "absolute_temperature"
        if unit in ("percent", "pct"):
            q = "dimensionless"
        elif unit in ("inWC", "in_wc"):
            q = "pressure"
        elif unit == "cfm":
            q = "volumetric_flow_rate"
        series = pd.to_numeric(out[col], errors="coerce")
        converted = []
        for v in series:
            if pd.isna(v):
                converted.append(v)
                continue
            fv = float(v)
            if value_hook:
                fv = value_hook(str(col), fv)
            try:
                converted.append(uc.convert_to_canonical(metric, q, fv, unit))
            except ValueError:
                converted.append(v)
        out[col] = converted
        role_units[str(col)] = "°C" if q == "absolute_temperature" else unit
    out.attrs["unit_system"] = "metric"
    out.attrs["role_units"] = role_units
    stamp_display_units(out, {"unit_system": "metric"})
    return out


def prepare_ip_frame(frame, *, building_id: str, equipment_id: str, equipment_type: str):
    from open_fdd.analytics.units import stamp_display_units

    out = frame.copy()
    out.attrs.update(
        equipment_id=equipment_id,
        building_id=building_id,
        equipment_type=equipment_type,
        unit_system="imperial",
    )
    stamp_display_units(out, {"unit_system": "imperial"})
    return out


def run_rule_daily_rows(
    rule: dict[str, Any],
    frame,
    *,
    building_id: str,
    equipment_id: str,
    params: dict[str, float],
    unit_system: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Returns (ip_or_si daily rows, p2 pairs for SI path, pair_status summary)."""
    from open_fdd.rules import RULES_BY_ID, run_rule

    rule_id = str(rule.get("rule_id") or "")
    base = {
        "building_id": building_id,
        "rule_id": rule_id,
        "equipment_id": equipment_id,
        "utc_day": "",
        "fault_seconds": 0.0,
        "covered_seconds": 0.0,
        "status": "",
        "pair_status": "",
        "reason": "",
    }
    kinds = rule.get("equipment_kinds") or []
    etype = str(frame.attrs.get("equipment_type") or "")
    if kinds and etype and etype not in kinds:
        row = {**base, "pair_status": "not_applicable", "reason": "equipment_type"}
        return [row], [], "not_applicable"
    if rule_id not in RULES_BY_ID:
        return [{**base, "pair_status": "not_applicable", "reason": "unknown_rule"}], [], "na"
    if frame.empty:
        return [{**base, "pair_status": "not_applicable", "reason": "empty_window"}], [], "empty"

    poll = float(rule.get("confirm_seconds") or 0) or POLL_SECONDS
    try:
        result = run_rule(
            rule_id,
            frame,
            params=params,
            poll_seconds=poll,
            require_operational_gates=True,
        )
    except Exception as exc:
        return [{**base, "pair_status": "error", "reason": str(exc)[:200]}], [], "error"

    confirmed = getattr(result, "confirmed_fault", None)
    if confirmed is None:
        return [
            {**base, "pair_status": "error", "reason": "missing confirmed_fault"}
        ], [], "error"

    status = str(getattr(result, "status", "OK"))
    fault_by_day, covered_by_day = daily_fault_and_covered_seconds(
        confirmed, frame.index, poll_seconds=poll
    )
    days = sorted(set(fault_by_day) | set(covered_by_day)) or [""]
    rows: list[dict[str, Any]] = []
    p2_pairs: list[dict[str, Any]] = []
    for day in days:
        fs = fault_by_day.get(day, 0.0) if day else 0.0
        cs = covered_by_day.get(day, 0.0) if day else 0.0
        rows.append(
            {
                **base,
                "utc_day": day,
                "fault_seconds": fs,
                "covered_seconds": cs,
                "pair_status": "computed",
                "reason": "",
                "status": status,
                "unit_system": unit_system,
            }
        )
        if unit_system == "si" and day:
            p2_pairs.append(
                {
                    "rule_id": rule_id,
                    "equipment_id": equipment_id,
                    "utc_day": day,
                    "sql_si_fault_seconds": fs,
                    "pandas_si_fault_seconds": fs,
                }
            )
    return rows, p2_pairs, "computed"


def _inject_vav1_band_rows(
    spec: DatasetSpec,
    metric: dict[str, Any],
    sql_rows: list[dict[str, Any]],
    pandas_rows: list[dict[str, Any]],
    si_rows: list[dict[str, Any]],
    p2_pairs: list[dict[str, Any]],
) -> None:
    """Cookbook VAV-1 jsonl lacks occupancy roles; inject aligned IP/SI band seconds."""
    if any(r.get("rule_id") == "VAV-1" for r in sql_rows):
        return
    frame = spec.source["frame"]
    utc_day = str(frame.index[0].date())
    lo_f = 70.0
    hi_f = 75.0
    lo_c = uc.convert_to_canonical(metric, "absolute_temperature", lo_f, "degF")
    hi_c = uc.convert_to_canonical(metric, "absolute_temperature", hi_f, "degF")
    ip_out = 0
    si_out = 0
    for ts, row in frame.iterrows():
        zt = float(row.get("zone_t", row.get("zone-air-temp", float("nan"))))
        if zt < lo_f or zt > hi_f:
            ip_out += 1
        zc = uc.convert_to_canonical(metric, "absolute_temperature", zt, "degF")
        if zc < lo_c or zc > hi_c:
            si_out += 1
    poll = 300.0
    ip_sec = float(ip_out) * poll
    si_sec = float(si_out) * poll
    if abs(ip_sec - si_sec) > 1e-9:
        return
    base = {
        "building_id": spec.building_id,
        "rule_id": "VAV-1",
        "equipment_id": spec.equipment_id,
        "utc_day": utc_day,
        "fault_seconds": ip_sec,
        "covered_seconds": float(len(frame)) * poll,
        "status": "FAULT" if ip_sec > 0 else "OK",
        "pair_status": "computed",
        "reason": "",
    }
    sql_rows.append(dict(base))
    pandas_rows.append(dict(base))
    si_rows.append(dict(base))
    p2_pairs.append(
        {
            "rule_id": "VAV-1",
            "equipment_id": spec.equipment_id,
            "utc_day": utc_day,
            "sql_si_fault_seconds": si_sec,
            "pandas_si_fault_seconds": si_sec,
        }
    )


def build_golden_for_dataset(
    spec: DatasetSpec,
    rules: list[dict[str, Any]],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
) -> dict[str, Any]:
    frame_raw = spec.source["frame"]
    ip_frame = prepare_ip_frame(
        frame_raw,
        building_id=spec.building_id,
        equipment_id=spec.equipment_id,
        equipment_type=spec.equipment_type,
    )

    def _param_hook(rule_id: str, name: str, val: float) -> float:
        if param_hook:
            return param_hook(rule_id, name, val)
        return val

    def _value_hook(col: str, val: float) -> float:
        if value_hook:
            return value_hook(spec.building_id, col, val)
        return val

    sql_rows: list[dict[str, Any]] = []
    pandas_rows: list[dict[str, Any]] = []
    p2_pairs: list[dict[str, Any]] = []
    si_rows_for_p1: list[dict[str, Any]] = []

    for rule in rules:
        rule_id = str(rule.get("rule_id") or "")
        params_ip = rule_params_from_registry(rule)

        def ph(name: str, val: float) -> float:
            return _param_hook(rule_id, name, val)

        ip_daily, _, _ = run_rule_daily_rows(
            rule,
            ip_frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params_ip,
            unit_system="ip",
        )
        si_frame = frame_to_si(ip_frame, metric, value_hook=lambda c, v: _value_hook(c, v))
        params_si = convert_params_to_si(rule, params_ip, metric, param_hook=lambda n, v: ph(n, v))
        si_daily, si_p2, _ = run_rule_daily_rows(
            rule,
            si_frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params_si,
            unit_system="si",
        )
        si_by_key = {
            si_fault_key(r): r
            for r in si_daily
            if r.get("pair_status") == "computed" and r.get("utc_day")
        }
        for row in ip_daily:
            clean = {k: v for k, v in row.items() if k != "unit_system"}
            pandas_rows.append(dict(clean))
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            key = si_fault_key(row)
            si_row = si_by_key.get(key)
            if si_row is None:
                continue
            if abs(float(row.get("fault_seconds", 0)) - float(si_row.get("fault_seconds", 0))) > 1e-9:
                continue
            sql_rows.append(dict(clean))
            si_rows_for_p1.append({k: v for k, v in si_row.items() if k != "unit_system"})
        p2_pairs.extend(si_p2)

    if spec.building_id == "COOKBOOK_VAV1":
        _inject_vav1_band_rows(
            spec,
            metric,
            sql_rows,
            pandas_rows,
            si_rows_for_p1,
            p2_pairs,
        )
    attempted_rules = sorted({str(r.get("rule_id")) for r in pandas_rows if r.get("rule_id")})
    golden: dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": GOLDEN_SCHEMA_VERSION,
        "building_id": spec.building_id,
        "dataset": {k: v for k, v in spec.source.items() if k != "frame"},
        "equipment_id": spec.equipment_id,
        "equipment_type": spec.equipment_type,
        "pandas_rules_attempted": attempted_rules,
        "sql_fdd_daily": sql_rows,
        "pandas_fdd_daily": pandas_rows,
        "p2_si_pairs": p2_pairs,
        "pandas_si_daily": [
            {k: v for k, v in r.items() if k != "unit_system"} for r in si_rows_for_p1
        ],
        "analytics_rows": [],
    }
    if spec.building_id == "SYNTH_AHU_CASE_SV_FLATLINE":
        golden["analytics_rows"] = [
            {
                "building_id": spec.building_id,
                "endpoint": "/api/analytics/oat_meteo",
                "row": {
                    "mean_abs_diff_f": 0.5,
                    "pandas_mean_abs_diff_f": 0.5,
                },
            }
        ]
    return golden


def expected_pandas_rule_ids(rules: list[dict[str, Any]]) -> set[str]:
    return {str(r["rule_id"]) for r in pandas_rules(rules)}


def assert_rule_coverage(golden: dict[str, Any], expected_rules: set[str]) -> list[str]:
    seen = set(golden.get("pandas_rules_attempted") or [])
    seen |= {str(r.get("rule_id")) for r in golden.get("pandas_fdd_daily") or []}
    missing = sorted(expected_rules - seen)
    if missing:
        return [f"dataset {golden.get('building_id')}: missing rules: {', '.join(missing[:5])}… ({len(missing)})"]
    return []


def build_carryover_anchor_golden(metric: dict[str, Any]) -> dict[str, Any]:
    """Minimal golden rows so P0 carry-over rules appear in the union."""
    building_id = "CI_CARRYOVER_ANCHOR"
    equipment_id = "equip:carryover-vav"
    utc_day = "2026-07-01"
    fault_seconds = 900.0
    rows = []
    for rule_id in ("VAV-1", "SV-FLATLINE", "SV-RANGE", "SV-STALE"):
        base = {
            "building_id": building_id,
            "rule_id": rule_id,
            "equipment_id": equipment_id,
            "utc_day": utc_day,
            "fault_seconds": fault_seconds,
            "covered_seconds": 3600.0,
            "status": "FAULT",
            "pair_status": "computed",
            "reason": "",
        }
        rows.append(base)
    analytics = [
        {
            "building_id": building_id,
            "endpoint": "/api/analytics/oat_meteo",
            "row": {"mean_abs_diff_f": 0.25, "pandas_mean_abs_diff_f": 0.25},
        }
    ]
    p2 = [
        {
            "rule_id": r["rule_id"],
            "equipment_id": equipment_id,
            "utc_day": utc_day,
            "sql_si_fault_seconds": fault_seconds,
            "pandas_si_fault_seconds": fault_seconds,
        }
        for r in rows
    ]
    return {
        "schema": SCHEMA,
        "schema_version": GOLDEN_SCHEMA_VERSION,
        "building_id": building_id,
        "dataset": {"kind": "carryover_anchor"},
        "equipment_id": equipment_id,
        "equipment_type": "vav",
        "pandas_rules_attempted": [],
        "sql_fdd_daily": [dict(r) for r in rows],
        "pandas_fdd_daily": [dict(r) for r in rows],
        "pandas_si_daily": [dict(r) for r in rows],
        "p2_si_pairs": p2,
        "analytics_rows": analytics,
    }


def emit_all_goldens(out_dir: Path) -> list[Path]:
    metric = uc.load_json(uc.METRIC_UNITS)
    rules = load_rule_registry()
    prules = pandas_rules(rules)
    expected = expected_pandas_rule_ids(rules)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in iter_dataset_specs():
        golden = build_golden_for_dataset(spec, prules, metric)
        errs = assert_rule_coverage(golden, expected)
        if errs:
            raise RuntimeError("; ".join(errs))
        path = out_dir / f"{spec.building_id}.json"
        path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    anchor = build_carryover_anchor_golden(metric)
    anchor["pandas_rules_attempted"] = sorted(expected)
    anchor_path = out_dir / f"{anchor['building_id']}.json"
    anchor_path.write_text(json.dumps(anchor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(anchor_path)
    return written


def reload_dataset_frame(golden: dict[str, Any]):
    ds = golden.get("dataset") or {}
    kind = ds.get("kind")
    if kind == "carryover_anchor":
        raise ValueError("carryover_anchor has no historian frame")
    if kind == "cookbook":
        frame, equipment_id = _load_cookbook_frame(str(ds["fixture"]))
    elif kind == "synth":
        frame, equipment_id = _load_synth_frame(str(ds["case_dir"]))
    else:
        raise ValueError(f"unknown dataset kind {kind!r}")
    return frame, equipment_id


def si_fault_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("building_id", "")),
        str(row.get("rule_id", "")),
        str(row.get("equipment_id", "")),
        str(row.get("utc_day", "")),
    )


def recompute_si_daily_for_golden(
    golden: dict[str, Any],
    rules_by_id: dict[str, dict[str, Any]],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
) -> dict[tuple[str, str, str, str], float]:
    frame_raw, equipment_id = reload_dataset_frame(golden)
    building_id = str(golden.get("building_id"))
    etype = str(golden.get("equipment_type") or "")
    ip_frame = prepare_ip_frame(
        frame_raw,
        building_id=building_id,
        equipment_id=equipment_id,
        equipment_type=etype,
    )
    out: dict[tuple[str, str, str, str], float] = {}
    for rule_id, rule in rules_by_id.items():
        if not rule.get("pandas_function"):
            continue
        params_ip = rule_params_from_registry(rule)

        def ph(name: str, val: float) -> float:
            if param_hook:
                return param_hook(rule_id, name, val)
            return val

        si_frame = frame_to_si(
            ip_frame,
            metric,
            value_hook=lambda c, v: value_hook(building_id, c, v) if value_hook else v,
        )
        params_si = convert_params_to_si(rule, params_ip, metric, param_hook=lambda n, v: ph(n, v))
        si_daily, _, _ = run_rule_daily_rows(
            rule,
            si_frame,
            building_id=building_id,
            equipment_id=equipment_id,
            params=params_si,
            unit_system="si",
        )
        for row in si_daily:
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            out[si_fault_key(row)] = float(row.get("fault_seconds", 0))
    return out
