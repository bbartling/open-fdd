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
        "name": "Acme zone temp flatline 1h",
        "fault_code": "VAV-03",
        "code_file": "flatline_1h.py",
        "config": {"flatline_tolerance": 0.15, "temp_unit": "imperial", "rolling_avg_minutes": 1},
        "bindings": {"point_ids": [], "equipment_ids": [], "brick_types": ["Zone_Air_Temperature_Sensor"]},
    },
    {
        "id": "acme-zn-t-oob-occupied",
        "name": "Acme zone temp out of bounds",
        "fault_code": "VAV-03",
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
        "name": "Acme discharge temp flatline 1h",
        "fault_code": "VAV-04",
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
        "name": "Acme AHU SAT flatline 1h (GL36 plant request input)",
        "fault_code": "AHU-03",
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
        "name": "Acme mixed air temp OOB (economizer diagnostic)",
        "fault_code": "AHU-05",
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
        "name": "Acme duct static flatline 1h (GL36 duct T&R input)",
        "fault_code": "AHU-06",
        "code_file": "flatline_1h.py",
        "config": {"flatline_tolerance": 0.02, "temp_unit": "imperial", "rolling_avg_minutes": 1},
        "bindings": {
            "point_ids": [],
            "equipment_ids": [],
            "brick_types": ["Supply_Air_Static_Pressure_Sensor"],
        },
    },
]


def save_rules() -> None:
    store = RuleStore()
    for spec in ACME_RULES:
        code = _read(spec["code_file"])
        lint = lint_python(code)
        if not lint["ok"]:
            raise SystemExit(f"Lint failed {spec['id']}: {lint['issues']}")
        store.upsert(
            {
                "id": spec["id"],
                "name": spec["name"],
                "mode": "rule",
                "code": code,
                "fault_code": spec["fault_code"],
                "config": spec["config"],
                "bindings": spec["bindings"],
                "severity": "warning",
                "enabled": True,
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
