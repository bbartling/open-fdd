#!/usr/bin/env python3
"""Emit haystack_point_role_golden.json (dev helper; mirrors fdd_core columns.rs)."""

from __future__ import annotations

import json
from pathlib import Path

from open_fdd.role_candidates import haystack_point_to_role

TAGS = [
    "discharge-air-temp",
    "discharge-air-temp-sp",
    "mixed-air-temp",
    "return-air-temp",
    "outside-air-temp",
    "outside-air-temperature",
    "bas-outside-air-temp",
    "outside-air-humidity",
    "outside-air-damper",
    "cooling-valve",
    "heating-valve",
    "fan-cmd",
    "return-fan-cmd",
    "fan-status",
    "duct-static-pressure",
    "duct-static-pressure-sp",
    "vav-pressure-request-sum",
    "static-reset-request",
    "cooling-coil-entering-temp",
    "cooling-coil-leaving-temp",
    "heating-coil-entering-temp",
    "heating-coil-leaving-temp",
    "chiller-status",
    "loop-enabled",
    "zone-air-temp",
    "zone-air-temp-sp",
    "cooling-sp",
    "zone-cooling-sp",
    "heating-sp",
    "zone-heating-sp",
    "zone-co2",
    "co2",
    "zone-air-humidity",
    "zone-humidity",
    "zone-airflow",
    "airflow",
    "vav-total-airflow",
    "min-flow-sp",
    "chw-pump-status",
    "compressor-status",
    "building-zone-load-satisfied",
    "building-ahu-load-satisfied",
    "damper",
    "damper-position",
    "damper-cmd",
    "reheat-valve",
    "vav-discharge-air-temp",
    "vav-inlet-air-temp",
    "ahu-discharge-air-temp",
    "chilled-water-supply-temp",
    "chw-st",
    "chilled-water-return-temp",
    "chw-rt",
    "chilled-water-supply-temp-sp",
    "hot-water-supply-temp",
    "hot-water-return-temp",
    "occupied",
    "chw-diff-pressure",
    "chw-diff-pressure-sp",
    "chw-flow",
    "chw-pump-cmd",
    "cw-pump-cmd",
    "tower-fan-cmd",
    "cw-fan-cmd",
    "condenser-water-supply-temp",
    "condenser-water-return-temp",
    "preheat-leaving-temp",
    "web-outside-air-temp",
    "web-outside-air-dewpoint",
    "web-outside-air-wetbulb",
    "web-outside-air-humidity",
    "chiller-power",
    "power",
    "chiller-amps",
    "chiller-current",
    "pump-status",
    "fan_cmd",
]

OUT = Path(__file__).resolve().parents[2] / "crates/fdd_core/testdata/haystack_point_role_golden.json"


def main() -> None:
    rows = [[tag, haystack_point_to_role(tag)] for tag in TAGS]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
