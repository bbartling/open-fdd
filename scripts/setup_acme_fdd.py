#!/usr/bin/env python3
"""Install Acme default zone-temperature FDD rules (brick-scoped flatline + OOB)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.playground import lint_python  # noqa: E402
from openfdd_bridge.rule_store import RuleStore  # noqa: E402

RULES_PY = REPO / "workspace" / "data" / "rules_py"


def _read(name: str) -> str:
    return (RULES_PY / name).read_text(encoding="utf-8")


ACME_RULES = [
    {
        "id": "acme-zn-t-flatline-1h",
        "name": "Zone temp flatline 1h",
        "fault_code": "VAV-C",
        "code_file": "flatline_1h.py",
        "config": {"flatline_tolerance": 0.15, "temp_unit": "imperial", "rolling_avg_minutes": 1},
        "bindings": {"point_ids": [], "equipment_ids": [], "brick_types": ["Zone_Air_Temperature_Sensor"]},
    },
    {
        "id": "acme-zn-t-oob-occupied",
        "name": "Zone temp out of bounds",
        "fault_code": "VAV-C",
        "code_file": "oob_rolling.py",
        "config": {
            "bounds_low": 65,
            "bounds_high": 78,
            "temp_unit": "imperial",
            "rolling_avg_minutes": 5,
        },
        "bindings": {"point_ids": [], "equipment_ids": [], "brick_types": ["Zone_Air_Temperature_Sensor"]},
    },
    {
        "id": "acme-da-t-flatline-1h",
        "name": "Discharge temp flatline 1h",
        "fault_code": "VAV-D",
        "code_file": "flatline_1h.py",
        "config": {"flatline_tolerance": 0.15, "temp_unit": "imperial", "rolling_avg_minutes": 1},
        "bindings": {
            "point_ids": [],
            "equipment_ids": [],
            "brick_types": ["Discharge_Air_Temperature_Sensor"],
        },
    },
    {
        "id": "acme-sat-flatline-1h",
        "name": "AHU SAT flatline 1h",
        "fault_code": "AHU-C",
        "code_file": "flatline_1h.py",
        "config": {"flatline_tolerance": 0.15, "temp_unit": "imperial", "rolling_avg_minutes": 1},
        "bindings": {
            "point_ids": [],
            "equipment_ids": [],
            "brick_types": ["Supply_Air_Temperature_Sensor"],
        },
    },
    {
        "id": "acme-mat-oob-economizer",
        "name": "Mixed air temp OOB",
        "fault_code": "AHU-E",
        "code_file": "oob_rolling.py",
        "config": {
            "bounds_low": 40,
            "bounds_high": 110,
            "temp_unit": "imperial",
            "rolling_avg_minutes": 5,
        },
        "bindings": {
            "point_ids": [],
            "equipment_ids": [],
            "brick_types": ["Mixed_Air_Temperature_Sensor"],
        },
    },
    {
        "id": "acme-sap-flatline-1h",
        "name": "Duct static flatline 1h",
        "fault_code": "AHU-F",
        "code_file": "flatline_1h.py",
        "config": {"flatline_tolerance": 0.02, "temp_unit": "imperial", "rolling_avg_minutes": 1},
        "bindings": {
            "point_ids": [],
            "equipment_ids": [],
            "brick_types": ["Supply_Air_Static_Pressure_Sensor"],
        },
    },
    {
        "id": "acme-ahu-afterhours-runtime",
        "name": "AHU fan after hours with satisfied zones",
        "fault_code": "BLD-C",
        "code_file": "acme_ahu_afterhours_runtime.py",
        "config": {
            "occupied_start_hour": 8,
            "occupied_end_hour": 17,
            "tz_offset_hours": -6,
            "fan_on_threshold": 5.0,
            "zone_satisfied_low": 68.0,
            "zone_satisfied_high": 76.0,
            "min_fault_samples": 10,
            "fan_speed_col": "supply-fan-speed-command",
            "fan_binary_col": "supply-fan-start-stop-command",
            "zone_avg_cols": [
                "averagespacetemperature-first-floor-area-2",
                "averagespacetemperature-second-floor-area-3",
            ],
            "column_map": {
                "Supply_Fan_Speed_Command": "supply-fan-speed-command",
                "Supply_Fan_Start_Stop_Command": "supply-fan-start-stop-command",
            },
            "temp_unit": "imperial",
            "rolling_avg_minutes": 1,
        },
        "bindings": {
            "point_ids": ["1100-analog-output-1"],
            "equipment_ids": ["acme-vm-bbartling-rtu-01"],
            "brick_types": [],
        },
        "applies_to": {"site_ids": ["acme"]},
    },
    {
        "id": "acme-ahu-run-hours",
        "name": "RTU fan and system run hours",
        "fault_code": "",
        "mode": "script",
        "code_file": "acme_ahu_run_hours.py",
        "config": {
            "site_id": "acme",
            "equipment_id": "acme-vm-bbartling-rtu-01",
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
        "bindings": {
            "point_ids": ["1100-analog-output-1"],
            "equipment_ids": ["acme-vm-bbartling-rtu-01"],
            "brick_types": [],
        },
        "applies_to": {"site_ids": ["acme"]},
    },
]


def save_rules() -> None:
    store = RuleStore()
    for spec in ACME_RULES:
        code = _read(spec["code_file"])
        lint = lint_python(code, require_evaluate=(spec.get("mode") or "rule") != "script")
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
                "enabled": True,
                **({"applies_to": spec["applies_to"]} if spec.get("applies_to") else {}),
            },
            saved_by="setup_acme_fdd",
        )
        print(f"Saved rule {spec['id']}")


def push_rules_to_edge(base: str, token: str) -> None:
    """Copy rules_store.json content via API if edge has different data dir — best-effort."""
    store_path = REPO / "workspace" / "data" / "rules_store.json"
    if not store_path.is_file():
        return
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    for rule in payload.get("rules") or []:
        if not str(rule.get("id", "")).startswith("acme-"):
            continue
        body = json.dumps(rule).encode()
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/rules/saved",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"Pushed {rule['id']} → HTTP {resp.status}")
        except Exception as exc:
            print(f"Note: could not push {rule.get('id')} to edge ({exc}) — rules sync on next deploy")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    save_rules()
    if args.host and args.token:
        push_rules_to_edge(f"http://{args.host}", args.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
