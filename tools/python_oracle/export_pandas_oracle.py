#!/usr/bin/env python3
"""Export pandas oracle metrics for Rust/DataFusion SQL parity comparison.

Uses ``cookbook_engine`` (same path as the dashboard) for fault rules and
deterministic rollups aligned with ``sql_rules/`` for analytics rules.

Output: ``.cache/oracle/pandas_rules.json``
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_APP = Path(__file__).resolve().parent
_BACKEND = _APP / "backend"
_ROOT = _APP.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.data_config import get_config  # noqa: E402
from haystack_rdf.csv_discovery import discover_historian_bundles  # noqa: E402

import cookbook_engine as ce  # noqa: E402
import cookbook_rules as cb  # noqa: E402
from rules.base import confirm_fault, hours_true  # noqa: E402


# SQL rule id -> cookbook rule id (None = analytics-only, no cookbook rule)
SQL_TO_COOKBOOK: dict[str, str | None] = {
    "FAN-RUNTIME-HOURS": None,
    "VAV-1": "VAV-1",
    "AVG-ZONE-TEMP": None,
    "ZONE-COMFORT-PCT": None,
    "FAULT-ELAPSED-HOURS": None,
    "OAT-METEO": "OAT-METEO",
    "FC13-SAT-HIGH": "FC13",
    "ECON-2": "ECON-2",
    "FC1": "FC1",
    "FC2": "FC2",
    "FC3": "FC3",
    "FC7": "FC7",
    "FC8": "FC8",
    "FC9": "FC9",
    "FC10": "FC10",
    "FC11": "FC11",
    "FC12": "FC12",
    "ECON-1": "ECON-1",
    "ECON-4": "ECON-4",
    "ECON-5": "ECON-5",
    "PID-HUNT-1": "PID-HUNT-1",
}

# Which equipment kinds each SQL rule applies to
RULE_KINDS: dict[str, list[str]] = {
    "FAN-RUNTIME-HOURS": ["ahu", "chiller", "boiler", "heatpump"],
    "VAV-1": ["vav", "zone"],
    "AVG-ZONE-TEMP": ["vav", "zone"],
    "ZONE-COMFORT-PCT": ["vav", "zone"],
    "FAULT-ELAPSED-HOURS": ["vav", "zone"],
    "OAT-METEO": ["ahu"],
    "FC13-SAT-HIGH": ["ahu"],
    "FC13": ["ahu"],
    "ECON-2": ["ahu"],
    "FC1": ["ahu"],
    "FC2": ["ahu"],
    "FC3": ["ahu"],
    "FC7": ["ahu"],
    "FC8": ["ahu"],
    "FC9": ["ahu"],
    "FC10": ["ahu"],
    "FC11": ["ahu"],
    "FC12": ["ahu"],
    "ECON-1": ["ahu"],
    "ECON-4": ["ahu"],
    "ECON-5": ["ahu"],
    "PID-HUNT-1": ["ahu", "vav", "chiller", "boiler", "heatpump", "equip"],
}


def _infer_kind(equipment_id: str, history_subdir: str) -> str:
    upper = equipment_id.upper()
    sub = history_subdir.upper()
    if upper.startswith("AHU") or "/AHU" in sub:
        return "ahu"
    if upper.startswith("VAV") or "/VAV/" in sub or sub.startswith("VAV/"):
        return "vav"
    if upper.startswith("CHILLER"):
        return "chiller"
    if "BOILER" in upper:
        return "boiler"
    if upper == "WEATHER":
        return "weather"
    if upper.startswith("ZONE"):
        return "zone"
    return "equip"


def _rule_by_id(rule_id: str) -> cb.CookbookRule | None:
    return cb.RULES_BY_ID.get(rule_id)


def _ts_range(d: pd.DataFrame) -> tuple[str | None, str | None]:
    if "timestamp" not in d.columns or d.empty:
        return None, None
    ts = pd.to_datetime(d["timestamp"], errors="coerce").dropna()
    if ts.empty:
        return None, None
    return ts.min().isoformat(), ts.max().isoformat()


def _fan_runtime_hours(d: pd.DataFrame, poll: float) -> dict[str, float]:
    if "fan_cmd" not in d.columns:
        return {}
    fan = cb.norm_cmd(d["fan_cmd"]).fillna(0)
    on = fan > 0.05
    n = int(on.sum())
    return {
        "fan_runtime_hours": round(n * poll / 3600.0, 4),
        "total_hours": round(len(d) * poll / 3600.0, 4),
        "fault_sample_count": n,
    }


def _zone_analytics(d: pd.DataFrame, poll: float) -> dict[str, float]:
    if "zone_t" not in d.columns:
        return {}
    zt = pd.to_numeric(d["zone_t"], errors="coerce")
    valid = zt.notna()
    if not valid.any():
        return {}
    lo, hi = 68.0, 76.0
    fault = (zt < lo) | (zt > hi)
    fault_n = int((fault & valid).sum())
    return {
        "avg_zone_temp": round(float(zt[valid].mean()), 4),
        "min_zone_temp": round(float(zt[valid].min()), 4),
        "max_zone_temp": round(float(zt[valid].max()), 4),
        "comfort_pct": round(100.0 * float(((zt >= lo) & (zt <= hi) & valid).sum()) / valid.sum(), 4),
        "fault_samples": fault_n,
        "fault_hours": round(fault_n * poll / 3600.0, 4),
        "fault_pct": round(100.0 * fault_n / valid.sum(), 4),
        "row_count": int(valid.sum()),
    }


def _cookbook_metrics(
    rule: cb.CookbookRule,
    d: pd.DataFrame,
    resolved: dict,
    poll: float,
    wx_avail: bool,
) -> dict[str, Any]:
    res = ce.run_rule(rule, d, resolved, poll, {}, wx_avail)
    metrics: dict[str, float] = {}
    if res.get("applicable"):
        fh = float(res.get("fault_hours", 0.0))
        metrics["fault_hours"] = fh
        metrics["fault_pct"] = float(res.get("fault_pct", 0.0))
        metrics["total_hours"] = float(res.get("total_hours", 0.0))
        fs = res.get("fault_series")
        if fs is not None:
            metrics["fault_sample_count"] = int(fs.sum())
    return {
        "applicable": bool(res.get("applicable")),
        "missing_roles": list(res.get("missing_roles") or []),
        "notes": res.get("message"),
        "metrics": metrics,
        "rule_name": rule.title,
    }


def _export_equipment_rule(
    *,
    building_id: str,
    equipment_id: str,
    kind: str,
    rule_id: str,
    d: pd.DataFrame,
    resolved: dict,
    poll: float,
    wx_avail: bool,
) -> dict[str, Any]:
    ts_start, ts_end = _ts_range(d)
    base: dict[str, Any] = {
        "building_id": building_id,
        "equipment_id": equipment_id,
        "kind": kind,
        "rule_id": rule_id,
        "poll_seconds": poll,
        "timestamp_start": ts_start,
        "timestamp_end": ts_end,
        "row_count": len(d),
    }

    cookbook_id = SQL_TO_COOKBOOK.get(rule_id)
    if cookbook_id:
        rule = _rule_by_id(cookbook_id)
        if rule is None:
            base["applicable"] = False
            base["missing_roles"] = ["cookbook_rule"]
            base["notes"] = f"No cookbook rule for {cookbook_id}"
            base["metrics"] = {}
            return base
        out = _cookbook_metrics(rule, d, resolved, poll, wx_avail)
        base.update(out)
        base["rule_name"] = out.get("rule_name", rule.title)
        return base

    # Analytics rules (no cookbook rule)
    base["rule_name"] = rule_id.replace("-", " ").title()
    base["missing_roles"] = []
    if rule_id == "FAN-RUNTIME-HOURS":
        if "fan_cmd" not in d.columns or d["fan_cmd"].notna().sum() == 0:
            base["applicable"] = False
            base["missing_roles"] = ["fan_cmd"]
            base["notes"] = "fan_cmd not in data model"
            base["metrics"] = {}
        else:
            base["applicable"] = True
            base["metrics"] = _fan_runtime_hours(d, poll)
    elif rule_id in ("AVG-ZONE-TEMP", "ZONE-COMFORT-PCT", "FAULT-ELAPSED-HOURS"):
        if "zone_t" not in d.columns or d["zone_t"].notna().sum() == 0:
            base["applicable"] = False
            base["missing_roles"] = ["zone_t"]
            base["notes"] = "zone_t not in data model"
            base["metrics"] = {}
        else:
            base["applicable"] = True
            za = _zone_analytics(d, poll)
            if rule_id == "AVG-ZONE-TEMP":
                base["metrics"] = {k: za[k] for k in ("avg_zone_temp", "min_zone_temp", "max_zone_temp") if k in za}
            elif rule_id == "ZONE-COMFORT-PCT":
                base["metrics"] = {"comfort_pct": za["comfort_pct"]}
            else:
                base["metrics"] = {k: za[k] for k in ("fault_samples", "fault_hours") if k in za}
    else:
        base["applicable"] = False
        base["notes"] = "unknown analytics rule"
        base["metrics"] = {}
    return base


def _flatten_metrics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for rec in records:
        if not rec.get("applicable"):
            continue
        for metric, value in (rec.get("metrics") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flat.append(
                    {
                        "rule_id": rec["rule_id"],
                        "equipment_id": rec["equipment_id"],
                        "metric": metric,
                        "value": float(value),
                    }
                )
    return flat


def export_oracle(
    *,
    rule_ids: list[str] | None = None,
    building: str | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    cfg = get_config()
    building_id = building or cfg.building
    poll = float(cfg.poll_seconds(building_id))
    out = out_path or (_ROOT / ".cache" / "oracle" / "pandas_rules.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    rule_ids = rule_ids or list(SQL_TO_COOKBOOK.keys())
    bundles = discover_historian_bundles(cfg.building_dir, building_dir=cfg.building_dir)

    from haystack_rdf.resolver import get_resolver

    resolver = get_resolver()
    weather = ce.load_weather(resolver)

    records: list[dict[str, Any]] = []
    for bundle in bundles:
        kind = _infer_kind(bundle.equipment_id, bundle.history_subdir)
        try:
            d, resolved, eq_poll, wx_avail = ce.build_logical_frame(
                bundle.equipment_id, kind, resolver, weather
            )
        except Exception as exc:
            for rule_id in rule_ids:
                if kind not in RULE_KINDS.get(rule_id, [kind]):
                    continue
                records.append(
                    {
                        "building_id": building_id,
                        "equipment_id": bundle.equipment_id,
                        "kind": kind,
                        "rule_id": rule_id,
                        "applicable": False,
                        "missing_roles": [],
                        "notes": f"load error: {exc}",
                        "metrics": {},
                    }
                )
            continue

        poll_use = float(eq_poll or poll)
        for rule_id in rule_ids:
            kinds = RULE_KINDS.get(rule_id, [])
            if kind not in kinds:
                continue
            rec = _export_equipment_rule(
                building_id=building_id,
                equipment_id=bundle.equipment_id,
                kind=kind,
                rule_id=rule_id,
                d=d,
                resolved=resolved,
                poll=poll_use,
                wx_avail=wx_avail,
            )
            records.append(rec)

    payload = {
        "building_id": building_id,
        "poll_seconds": poll,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_ids": rule_ids,
        "records": records,
        "metrics": _flatten_metrics(records),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["output_path"] = str(out)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Export pandas oracle for SQL parity")
    parser.add_argument("--building", default=None, help="Building id (default from config)")
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default .cache/oracle/pandas_rules.json)",
    )
    parser.add_argument("--rules", nargs="*", default=None, help="Rule ids to export")
    args = parser.parse_args()
    out_path = Path(args.out) if args.out else None
    result = export_oracle(rule_ids=args.rules, building=args.building, out_path=out_path)
    print(json.dumps({"ok": True, "records": len(result["records"]), "output": result["output_path"]}))


if __name__ == "__main__":
    main()
