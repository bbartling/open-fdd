#!/usr/bin/env python3
"""
Minimal column_map demo: one YAML rule + five ways to key the same sensor column.

From the open-fdd repo root (with open-fdd installed):

    python examples/column_map_resolver_workshop/simple_ontology_demo.py

The rule file is ``simple_ontology_rule.yaml`` (cookbook-style ``inputs`` with
brick / haystack / dbo / s223 / 223p). Your ``column_map`` only needs the key
that matches *your* naming system; open-fdd picks the first matching ontology
label in order: brick → haystack → dbo → s223 → 223p.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.engine.runner import RuleRunner, load_rule

HERE = Path(__file__).resolve().parent
RULE_YAML = HERE / "simple_ontology_rule.yaml"


def sample_frame() -> pd.DataFrame:
    # One row goes over ``hi`` (100) so the fault flag fires.
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC"),
            "sat": [72.0, 105.0, 70.0],
        }
    )


def main() -> None:
    rule = load_rule(RULE_YAML)
    runner = RuleRunner(rules=[rule])
    df = sample_frame()

    demos: list[tuple[str, dict[str, str]]] = [
        ("Brick", {"Supply_Air_Temperature_Sensor": "sat"}),
        ("Haystack", {"discharge_air_temp_sensor": "sat"}),
        ("DBO (Google Digital Buildings style)", {"SupplyAirTemperatureSensor": "sat"}),
        ("ASHRAE 223P (s223 field)", {"bldg1_supply_air_temperature_sensor": "sat"}),
        ("ASHRAE 223P (223p field)", {"ahu1_supply_air_temp_223p": "sat"}),
    ]

    print("Rule:", RULE_YAML.name)
    print("DataFrame columns: sat (supply air temp), timestamp")
    print("Expression: Supply_Air_Temperature_Sensor > hi  (hi=100)\n")

    for label, column_map in demos:
        out = runner.run(
            df,
            timestamp_col="timestamp",
            column_map=column_map,
            params={"units": "imperial"},
            skip_missing_columns=True,
        )
        fired = bool(out["supply_air_hot_flag"].astype(bool).any())
        print(f"--- {label} ---")
        print(f"  column_map key → column: {next(iter(column_map.items()))}")
        print(f"  supply_air_hot_flag fired (any True): {fired}")


if __name__ == "__main__":
    main()
