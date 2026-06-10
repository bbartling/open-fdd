#!/usr/bin/env python3
"""Install default GL36 FDD rules for a site (brick-scoped flatline + OOB + optional AHU scripts).

Brick-bound rules (``Zone_Air_Temperature_Sensor``, etc.) use one equation config for every
matched point; the FDD runner sweeps all binding-matched historian columns and OR-combines
fault masks (see ``historian_columns_for_rule``).

Acme bench device map (BACnet device instance → units at wire):

- **JCI VAV** — instances **1–100** (imperial °F at BACnet; rules use ``temp_unit: imperial``)
- **RTU AHU** — instance **1100** (imperial)
- **Boiler** — instance **1002** (imperial)
- **Trane VAV** — instances **11000–13000** (~6–8 boxes; BACnet temps are °C)

Trane °C is converted to °F before feather ingest via
``edge_config/acme/vm-bbartling/device_poll_profiles.csv`` (``metric_temp_f``). All zone-temp
rules therefore share imperial bounds (65–78 °F occupied OOB) after poll conversion. If a Trane
box is added without a poll profile, add a profile row or split a metric-only rule variant.

Example:
  python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling \\
    --ahu-equipment-id acme-vm-bbartling-rtu-01 --ahu-system-id rtu-01 \\
    --fan-point-id 1100-analog-output-1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(API))
sys.path.insert(0, str(REPO / "scripts"))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.playground import lint_python  # noqa: E402
from openfdd_bridge.rule_store import RuleStore  # noqa: E402
from lib.site_pack_paths import equipment_id, rule_id_prefix  # noqa: E402

RULES_PY = REPO / "workspace" / "data" / "rules_py"

# Acme BACnet poll loop is 60 s; 1 h flatline = 60 samples (not legacy 5-min × 12).
ACME_POLL_CFG: dict[str, Any] = {
    "poll_interval_s": 60,
    "flatline_minutes": 60,
    "temp_unit": "imperial",
    "occupied_start_hour": 8,
    "occupied_end_hour": 17,
    "tz_offset_hours": -6,
}


def _read(name: str) -> str:
    return (RULES_PY / name).read_text(encoding="utf-8")


def _cfg(*, extra: dict[str, Any] | None = None, occupied: bool = False) -> dict[str, Any]:
    out = dict(ACME_POLL_CFG)
    if occupied:
        out["occupied_only"] = True
    if extra:
        out.update(extra)
    return out


def gl36_rule_specs(
    *,
    site_id: str,
    prefix: str,
    ahu_equipment_id: str,
    fan_point_id: str,
    zone_avg_cols: list[str],
    column_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Rule templates for a GL36-style building; ids are ``{prefix}-…`` not customer names."""
    p = prefix
    applies = {"site_ids": [site_id]}
    ahu_bindings = {
        "point_ids": [fan_point_id] if fan_point_id else [],
        "equipment_ids": [ahu_equipment_id] if ahu_equipment_id else [],
        "brick_types": [],
    }
    return [
        # Phase 0 — data quality (low noise)
        {
            "id": f"{p}-oat-bounds",
            "name": "Outdoor air temp bounds",
            "fault_code": "BLD-B",
            "code_file": "oat_sensor_bounds.py",
            "config": _cfg(extra={"rolling_avg_minutes": 5}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Outside_Air_Temperature_Sensor"],
            },
        },
        {
            "id": f"{p}-oat-flatline-1h",
            "name": "Outdoor air temp flatline 1h",
            "fault_code": "BLD-B",
            "code_file": "oat_sensor_flatline.py",
            "config": _cfg(),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Outside_Air_Temperature_Sensor"],
            },
        },
        {
            "id": f"{p}-oat-spike",
            "name": "Outdoor air temp spike",
            "fault_code": "BLD-B",
            "code_file": "oat_sensor_spike.py",
            "config": _cfg(),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Outside_Air_Temperature_Sensor"],
            },
            "enabled": False,
        },
        {
            "id": f"{p}-zn-t-flatline-1h",
            "name": "Zone temp flatline 1h occupied",
            "fault_code": "VAV-C",
            "code_file": "vav_zone_temp_flatline_occupied.py",
            "config": _cfg(extra={"flatline_tolerance": 0.10}, occupied=True),
            "bindings": {"point_ids": [], "equipment_ids": [], "brick_types": ["Zone_Air_Temperature_Sensor"]},
        },
        {
            "id": f"{p}-zn-t-oob-occupied",
            "name": "Zone temp out of bounds occupied",
            "fault_code": "VAV-C",
            "code_file": "vav_zone_temp_bounds_occupied.py",
            "config": _cfg(
                extra={"bounds_low": 65, "bounds_high": 78, "rolling_avg_minutes": 5},
                occupied=True,
            ),
            "bindings": {"point_ids": [], "equipment_ids": [], "brick_types": ["Zone_Air_Temperature_Sensor"]},
        },
        {
            "id": f"{p}-da-t-flatline-1h",
            "name": "Discharge temp flatline 1h",
            "fault_code": "VAV-E",
            "code_file": "flatline_1h.py",
            "config": _cfg(extra={"flatline_tolerance": 0.15}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Discharge_Air_Temperature_Sensor"],
            },
        },
        {
            "id": f"{p}-sat-flatline-1h",
            "name": "AHU SAT flatline 1h",
            "fault_code": "AHU-C",
            "code_file": "flatline_1h.py",
            "config": _cfg(extra={"flatline_tolerance": 0.15}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Supply_Air_Temperature_Sensor"],
            },
        },
        {
            "id": f"{p}-mat-oob-economizer",
            "name": "Mixed air temp OOB",
            "fault_code": "AHU-D",
            "code_file": "oob_rolling.py",
            "config": _cfg(extra={"bounds_low": 40, "bounds_high": 110, "rolling_avg_minutes": 5}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Mixed_Air_Temperature_Sensor"],
            },
            "enabled": False,
        },
        {
            "id": f"{p}-sap-flatline-1h",
            "name": "Duct static flatline 1h",
            "fault_code": "AHU-F",
            "code_file": "flatline_1h.py",
            "config": _cfg(extra={"flatline_tolerance": 0.02}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Supply_Air_Static_Pressure_Sensor"],
            },
        },
        {
            "id": f"{p}-ahu-afterhours-runtime",
            "name": "AHU fan after hours with satisfied zones",
            "fault_code": "BLD-C",
            "code_file": "ahu_afterhours_runtime.py",
            "config": {
                **_cfg(),
                "fan_on_threshold": 5.0,
                "zone_satisfied_low": 68.0,
                "zone_satisfied_high": 76.0,
                "min_fault_samples": 10,
                "fan_speed_col": "supply-fan-speed-command",
                "fan_binary_col": "supply-fan-start-stop-command",
                "zone_avg_cols": zone_avg_cols,
                "column_map": column_map,
                "rolling_avg_minutes": 1,
            },
            "bindings": ahu_bindings,
            "applies_to": applies,
        },
        {
            "id": f"{p}-ahu-run-hours",
            "name": "AHU fan and system run hours",
            "fault_code": "",
            "mode": "script",
            "code_file": "ahu_run_hours.py",
            "config": {
                "site_id": site_id,
                "equipment_id": ahu_equipment_id,
                "occupied_start_hour": 8,
                "occupied_end_hour": 17,
                "tz_offset_hours": -6,
                "fan_on_threshold": 5.0,
                "fan_speed_col": "supply-fan-speed-command",
                "fan_binary_col": "supply-fan-start-stop-command",
                "compressor_cols": [
                    "compressor-1-command",
                    "compressor-2-command",
                    "compressor-3-command",
                    "compressor-4-command",
                ],
                "max_gap_hours": 2.0,
            },
            "bindings": ahu_bindings,
            "applies_to": applies,
        },
        {
            "id": f"{p}-vav-damper-stuck",
            "name": "VAV damper stuck open",
            "fault_code": "VAV-D",
            "code_file": "vav_damper_stuck_flatline.py",
            "config": _cfg(extra={"flatline_tolerance": 0.02, "damper_open_min": 0.975}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Damper_Position_Command", "Damper_Position_Sensor"],
            },
        },
        {
            "id": f"{p}-vav-airflow-low",
            "name": "VAV airflow low with damper open",
            "fault_code": "VAV-D",
            "code_file": "vav_airflow_low.py",
            "config": {"min_airflow_cfm": 50, "damper_open_min": 0.15, "damper_column": "damper-position-command"},
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Air_Flow_Sensor", "Supply_Air_Flow_Sensor"],
            },
        },
        {
            "id": f"{p}-vav-reheat-leak",
            "name": "VAV reheat leak (DAT vs AHU SAT)",
            "fault_code": "VAV-A",
            "code_file": "vav_reheat_dat_vs_sat.py",
            "config": {"reference_sat_column": "sa-t", "reheat_delta_f": 8.0},
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Discharge_Air_Temperature_Sensor"],
            },
            "enabled": False,
        },
        {
            "id": f"{p}-vav-reheat-warm-ambient",
            "name": "VAV reheat during warm ambient",
            "fault_code": "VAV-A",
            "code_file": "zone_reheat_warm_ambient.py",
            "config": _cfg(extra={"t_amb_cutoff": 78.0, "reheat_open_min": 0.52}),
            "bindings": {
                "point_ids": [],
                "equipment_ids": [],
                "brick_types": ["Heating_Valve_Command"],
            },
            "enabled": False,
        },
    ]


def save_rules(specs: list[dict[str, Any]], *, site_id: str) -> None:
    store = RuleStore()
    for spec in specs:
        code = _read(spec["code_file"])
        is_script = (spec.get("mode") or "rule") == "script"
        lint = lint_python(code, require_arrow_rule=not is_script)
        if not lint["ok"]:
            raise SystemExit(f"Lint failed {spec['id']}: {lint['issues']}")
        store.upsert(
            {
                "id": spec["id"],
                "name": spec["name"],
                "mode": spec.get("mode") or "rule",
                "code": code,
                "fault_code": spec["fault_code"],
                "config": spec["config"],
                "bindings": spec["bindings"],
                "severity": "warning",
                "enabled": spec.get("enabled", True),
                **({"applies_to": spec["applies_to"]} if spec.get("applies_to") else {}),
            },
            saved_by=f"setup_gl36_fdd:{site_id}",
        )
        print(f"Saved rule {spec['id']}")


def _save_rule_payload(rule: dict[str, Any]) -> dict[str, Any]:
    """Map rules_store entry to POST /api/rules/save body."""
    out: dict[str, Any] = {
        "id": rule.get("id"),
        "name": rule.get("name") or "Untitled rule",
        "description": rule.get("description") or "",
        "mode": rule.get("mode") or "rule",
        "code": rule.get("code") or "",
        "fault_code": rule.get("fault_code") or "",
        "fault_codes": rule.get("fault_codes") or [],
        "config": rule.get("config") if isinstance(rule.get("config"), dict) else {},
        "bindings": rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {},
        "severity": rule.get("severity") or "warning",
        "enabled": rule.get("enabled") is not False,
    }
    if isinstance(rule.get("applies_to"), dict):
        out["applies_to"] = rule["applies_to"]
    if isinstance(rule.get("column_map"), dict):
        out["column_map"] = rule["column_map"]
    return out


def push_rules_to_edge(base: str, token: str, *, site_id: str, rule_ids: set[str]) -> None:
    store_path = REPO / "workspace" / "data" / "rules_store.json"
    if not store_path.is_file():
        return
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    for rule in payload.get("rules") or []:
        rid = str(rule.get("id") or "")
        if rid not in rule_ids:
            continue
        if not str(rule.get("code") or "").strip():
            print(f"Note: skip push {rid} — no inline code in rules_store")
            continue
        body = json.dumps(_save_rule_payload(rule)).encode()
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/rules/save",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"Pushed {rid} → HTTP {resp.status}")
        except Exception as exc:
            print(f"Note: could not push {rid} to edge ({exc}) — rules sync on next deploy")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install GL36 default FDD rules for a site")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--building-id", default="", help="Used to derive default AHU equipment id")
    parser.add_argument("--rule-prefix", default="", help="Rule id prefix (default: site-id slug)")
    parser.add_argument("--ahu-system-id", default="rtu-01", help="system_id for default equipment id")
    parser.add_argument("--ahu-equipment-id", default="", help="Override BRICK equipment id for AHU rules")
    parser.add_argument("--fan-point-id", default="", help="BACnet point_id bound to supply fan command")
    parser.add_argument(
        "--zone-avg-cols",
        default="",
        help="Comma-separated wide-frame columns for zone average temp (afterhours rule)",
    )
    parser.add_argument("--host", default="")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    prefix = (args.rule_prefix or rule_id_prefix(args.site_id)).strip()
    ahu_eid = (args.ahu_equipment_id or "").strip()
    if not ahu_eid and args.building_id and args.ahu_system_id:
        ahu_eid = equipment_id(args.site_id, args.building_id, args.ahu_system_id)

    zone_cols = [c.strip() for c in args.zone_avg_cols.split(",") if c.strip()]
    column_map = {
        "Supply_Fan_Speed_Command": "supply-fan-speed-command",
        "Supply_Fan_Start_Stop_Command": "supply-fan-start-stop-command",
    }

    specs = gl36_rule_specs(
        site_id=args.site_id,
        prefix=prefix,
        ahu_equipment_id=ahu_eid,
        fan_point_id=args.fan_point_id.strip(),
        zone_avg_cols=zone_cols,
        column_map=column_map,
    )
    save_rules(specs, site_id=args.site_id)

    if args.host and args.token:
        push_rules_to_edge(
            f"http://{args.host}",
            args.token,
            site_id=args.site_id,
            rule_ids={s["id"] for s in specs},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
