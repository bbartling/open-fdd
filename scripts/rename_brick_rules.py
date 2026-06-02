#!/usr/bin/env python3
"""Rename production FDD rules to BRICK-consistent labels; disable bench rules."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "workspace" / "data" / "rules_store.json"

RENAMES: dict[str, str] = {
    "acme-zn-t-flatline-1h": "Zone_Air_Temperature_Sensor · flatline 1h",
    "acme-zn-t-oob-occupied": "Zone_Air_Temperature_Sensor · out of bounds",
    "acme-da-t-flatline-1h": "Discharge_Air_Temperature_Sensor · flatline 1h",
    "acme-sat-flatline-1h": "Supply_Air_Temperature_Sensor · flatline 1h",
    "acme-mat-oob-economizer": "Mixed_Air_Temperature_Sensor · out of bounds",
    "acme-sap-flatline-1h": "Duct_Static_Pressure_Sensor · flatline 1h",
    "acme-ahu-afterhours-runtime": "AHU · supply fan after hours (zones satisfied)",
    "acme-ahu-run-hours": "AHU · fan and system run hours",
    "duct-t-flatline-1h": "Discharge_Air_Temperature_Sensor · flatline 1h",
    "duct-t-spread-1h": "Discharge_Air_Temperature_Sensor · spread 1h",
}


def main() -> int:
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read {STORE}: {exc}", file=sys.stderr)
        return 1
    rules = raw.get("rules") or []
    changed = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "")
        if rid.startswith("bench-"):
            if rule.get("enabled", True):
                rule["enabled"] = False
                changed += 1
            continue
        new_name = RENAMES.get(rid)
        if new_name and rule.get("name") != new_name:
            rule["name"] = new_name
            changed += 1
        # Legacy RTU wording in names not covered by id map
        name = str(rule.get("name") or "")
        if re.search(r"\bRTU\b", name, re.IGNORECASE) and not re.search(r"\bAHU\b", name, re.IGNORECASE):
            rule["name"] = re.sub(r"\bRTU\b", "AHU", name, flags=re.IGNORECASE)
            changed += 1
        if name.lower().startswith("acme "):
            rule["name"] = name[5:].strip()
            changed += 1
        if name.lower().startswith("bench "):
            rule["enabled"] = False
            changed += 1
    STORE.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {changed} rule field(s) in {STORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
