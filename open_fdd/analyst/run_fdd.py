#!/usr/bin/env python3
"""
Run open-fdd rules on each heat pump DataFrame, aggregate faults, generate report.

Use run_fdd_pipeline() for programmatic access (notebook, scripts).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.analyst.config import AnalystConfig, default_analyst_config


def _filter_rules_by_equipment(rules: list, equipment_types: list[str]) -> list:
    """Only run rules whose equipment_type matches Brick model (e.g. Heat_Pump)."""
    if not equipment_types:
        return rules
    return [
        r
        for r in rules
        if (not r.get("equipment_type"))
        or any(et in equipment_types for et in r.get("equipment_type", []))
    ]


def _add_synthetic_columns(
    df: pd.DataFrame, column_map: dict[str, str]
) -> pd.DataFrame:
    """Add placeholder columns for setpoints if rules expect them but data doesn't."""
    df = df.copy()
    for brick_key, csv_col in column_map.items():
        if csv_col not in df.columns and (
            "setpoint" in brick_key.lower() or "sp" in brick_key.lower()
        ):
            df[csv_col] = 0.5
    return df


def run_fdd_pipeline(
    config: AnalystConfig | None = None,
) -> tuple[
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, str],
    list[dict[str, Any]],
    list[str],
]:
    """
    Run FDD on all heat pumps. Returns (summary, result_by_eq, column_map, rules, flag_cols).
    """
    cfg = config or default_analyst_config()
    heat_pumps_csv = cfg.heat_pumps_csv
    brick_ttl = cfg.brick_ttl
    rules_root = cfg.rules_root
    rolling_window = cfg.rolling_window

    try:
        from open_fdd.engine.brick_resolver import (
            resolve_from_ttl,
            get_equipment_types_from_ttl,
        )
        from open_fdd.engine.runner import RuleRunner, load_rules_from_dir
    except ImportError:
        raise ImportError("open-fdd not installed. pip install open-fdd[brick]")

    if not heat_pumps_csv.exists():
        raise FileNotFoundError(f"Run pipeline first. Missing {heat_pumps_csv}")

    rules_dir = rules_root
    if not rules_dir.exists():
        try:
            import open_fdd
            rules_dir = Path(open_fdd.__file__).parent / "rules"
        except ImportError:
            raise ImportError("open-fdd not installed")

    big = pd.read_csv(heat_pumps_csv)
    big["timestamp"] = pd.to_datetime(big["timestamp"])
    column_map = resolve_from_ttl(str(brick_ttl))
    equipment_types = get_equipment_types_from_ttl(str(brick_ttl))
    all_rules = load_rules_from_dir(rules_dir)
    rules = _filter_rules_by_equipment(all_rules, equipment_types)
    runner = RuleRunner(rules=rules)
    flag_cols = ["hp_discharge_cold_flag", "bad_sensor_flag", "flatline_flag"]

    all_results = []
    result_by_eq: dict[str, pd.DataFrame] = {}
    for eq_id in sorted(big["equipment_id"].unique()):
        df_one = big[big["equipment_id"] == eq_id].drop(columns=["equipment_id"])
        if len(df_one) < 10:
            continue
        df_one = _add_synthetic_columns(df_one, column_map)
        res = runner.run(
            df_one,
            timestamp_col="timestamp",
            rolling_window=rolling_window,
            column_map=column_map,
            params={"units": "imperial"},
            skip_missing_columns=True,
        )
        result_by_eq[eq_id] = res
        counts = {c: int(res[c].sum()) for c in flag_cols if c in res.columns}
        for c in flag_cols:
            if c not in counts:
                counts[c] = 0
        all_results.append({"equipment_id": eq_id, "rows": len(res), **counts})

    summary = pd.DataFrame(all_results)
    return summary, result_by_eq, column_map, rules, flag_cols


def run_fdd_on_equipment(
    df: pd.DataFrame,
    rules_dir: Path,
    config: AnalystConfig | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Run open-fdd rules, return (result_df, fault_counts)."""
    cfg = config or default_analyst_config()

    try:
        from open_fdd.engine.runner import RuleRunner
        from open_fdd.engine.brick_resolver import (
            resolve_from_ttl,
            get_equipment_types_from_ttl,
        )
    except ImportError:
        return df, {"error": "open-fdd not installed"}

    column_map = resolve_from_ttl(str(cfg.brick_ttl))
    get_equipment_types_from_ttl(str(cfg.brick_ttl))

    runner = RuleRunner(rules_path=str(rules_dir))
    result = runner.run(
        df,
        timestamp_col="timestamp",
        rolling_window=cfg.rolling_window,
        column_map=column_map,
        params={"units": "imperial"},
        skip_missing_columns=True,
    )
    flag_cols = [c for c in result.columns if c.endswith("_flag")]
    counts = {c: int(result[c].sum()) for c in flag_cols}
    return result, counts


def main(config: AnalystConfig | None = None) -> None:
    """Run FDD on all equipment, write report."""
    cfg = config or default_analyst_config()

    try:
        summary, _, _, _, flag_cols = run_fdd_pipeline(config=cfg)
    except (FileNotFoundError, ImportError) as e:
        print(e)
        return

    if len(summary) == 0:
        print("No FDD results.")
        return
    print(summary.to_string())

    cfg.reports_root.mkdir(parents=True, exist_ok=True)
    summary.to_csv(cfg.reports_root / "fault_summary.csv", index=False)
    print(f"Fault summary saved: {cfg.reports_root / 'fault_summary.csv'}")

    report_path = cfg.reports_root / "heat_pump_report.txt"
    with open(report_path, "w") as f:
        f.write("Sun Prairie Creekside Elementary — Heat Pump FDD Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(summary.to_string())
        f.write("\n\n")
        for col in flag_cols:
            total = summary[col].sum()
            if total > 0:
                f.write(
                    f"\n{col}: {int(total)} total fault samples across equipment\n"
                )
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
