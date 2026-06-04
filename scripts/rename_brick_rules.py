#!/usr/bin/env python3
"""Rename production FDD rules to BRICK-consistent labels; disable bench rules."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "workspace" / "data" / "rules_store.json"

# Match rule id suffixes from setup_gl36_fdd / setup_bench_afdd (any site prefix).
SUFFIX_RENAMES: dict[str, str] = {
    "zn-t-flatline-1h": "Zone_Air_Temperature_Sensor · flatline 1h",
    "zn-t-oob-occupied": "Zone_Air_Temperature_Sensor · out of bounds",
    "da-t-flatline-1h": "Discharge_Air_Temperature_Sensor · flatline 1h",
    "sat-flatline-1h": "Supply_Air_Temperature_Sensor · flatline 1h",
    "mat-oob-economizer": "Mixed_Air_Temperature_Sensor · out of bounds",
    "sap-flatline-1h": "Duct_Static_Pressure_Sensor · flatline 1h",
    "ahu-afterhours-runtime": "AHU · supply fan after hours (zones satisfied)",
    "ahu-run-hours": "AHU · fan and system run hours",
    "oa-t-flatline-1h": "Outdoor_Air_Temperature_Sensor · flatline 1h",
    "oa-t-oob": "Outdoor_Air_Temperature_Sensor · out of bounds",
    "stat-zn-t-flatline-1h": "Zone_Air_Temperature_Sensor · flatline 1h",
    "duct-t-flatline-1h": "Discharge_Air_Temperature_Sensor · flatline 1h",
    "duct-t-spread-1h": "Discharge_Air_Temperature_Sensor · spread 1h",
}

# Legacy ids from older site-prefixed installs (e.g. acme-zn-t-flatline-1h).
LEGACY_ID_RENAMES: dict[str, str] = {
    "acme-zn-t-flatline-1h": SUFFIX_RENAMES["zn-t-flatline-1h"],
    "acme-zn-t-oob-occupied": SUFFIX_RENAMES["zn-t-oob-occupied"],
    "acme-da-t-flatline-1h": SUFFIX_RENAMES["da-t-flatline-1h"],
    "acme-sat-flatline-1h": SUFFIX_RENAMES["sat-flatline-1h"],
    "acme-mat-oob-economizer": SUFFIX_RENAMES["mat-oob-economizer"],
    "acme-sap-flatline-1h": SUFFIX_RENAMES["sap-flatline-1h"],
    "acme-ahu-afterhours-runtime": SUFFIX_RENAMES["ahu-afterhours-runtime"],
    "acme-ahu-run-hours": SUFFIX_RENAMES["ahu-run-hours"],
}


def _rename_for_rule_id(rid: str) -> str | None:
    if rid in LEGACY_ID_RENAMES:
        return LEGACY_ID_RENAMES[rid]
    for suffix, label in SUFFIX_RENAMES.items():
        if rid.endswith(f"-{suffix}"):
            return label
    return None


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
        new_name = _rename_for_rule_id(rid)
        if new_name and rule.get("name") != new_name:
            rule["name"] = new_name
            changed += 1
        name = str(rule.get("name") or "")
        if re.search(r"\bRTU\b", name, re.IGNORECASE) and not re.search(r"\bAHU\b", name, re.IGNORECASE):
            rule["name"] = re.sub(r"\bRTU\b", "AHU", name, flags=re.IGNORECASE)
            changed += 1
        if name.lower().startswith("bench "):
            rule["enabled"] = False
            changed += 1
    STORE.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {changed} rule field(s) in {STORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
