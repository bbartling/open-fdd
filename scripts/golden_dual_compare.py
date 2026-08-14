#!/usr/bin/env python3
"""Run shared oracle fixtures on pandas; optionally compare DataFusion hours.

Does not claim full 59/59 parity. FC7 remains sql_screening (not duration_parity). Fixtures with
datafusion_compare=pending are pandas-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "crates" / "fdd_rules" / "fixtures" / "oracle"


def load_history(path: Path):
    import pandas as pd

    df = pd.read_csv(path)
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    df.index = pd.to_datetime(df[ts_col], utc=True)
    return df.sort_index()


def apply_columns(df, columns_csv: Path):
    import pandas as pd

    if not columns_csv.is_file():
        return df
    cmap = pd.read_csv(columns_csv)
    mapping = {
        str(r["col"]): str(r["point_role"])
        for _, r in cmap.iterrows()
        if pd.notna(r.get("col")) and pd.notna(r.get("point_role"))
    }
    return df.rename(columns=mapping)


def run_fixture(path: Path) -> dict:
    from open_fdd.rules import run_rule

    meta = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    rule_id = meta["pandas_rule_id"]
    hist = path / "history_wide.csv"
    import pandas as pd

    if meta.get("expect_missing_roles") and not hist.is_file():
        df = pd.DataFrame(index=pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True))
    else:
        df = apply_columns(load_history(hist), path / "columns.csv")
    df.attrs["equipment_id"] = meta.get("equipment_id", "EQ_1")
    default_type = "VAV" if meta.get("expect_missing_roles") else "AHU"
    df.attrs["equipment_type"] = meta.get("equipment_type", default_type)
    result = run_rule(
        rule_id,
        df,
        params=meta.get("params") or {},
        poll_seconds=float(meta.get("poll_seconds", 300)),
        require_operational_gates=bool(meta.get("require_operational_gates", True)),
    )
    out = {
        "path": str(path.relative_to(ROOT)),
        "rule_id": rule_id,
        "status": result.status,
        "fault_hours": result.fault_hours,
        "datafusion_compare": meta.get("datafusion_compare", "pending"),
    }
    if meta.get("expect_status"):
        if result.status != meta["expect_status"]:
            raise SystemExit(
                f"FAIL {path}: status={result.status} want {meta['expect_status']}"
            )
    if meta.get("expect_missing_roles"):
        if result.status != "SKIPPED_MISSING_ROLES":
            raise SystemExit(f"FAIL {path}: expected SKIPPED_MISSING_ROLES got {result.status}")
    if meta.get("fault_hours") is not None:
        tol = float(meta.get("fault_hours_tol", 0.1))
        got = float(result.fault_hours or 0)
        if abs(got - float(meta["fault_hours"])) > tol:
            raise SystemExit(f"FAIL {path}: hours={got} want {meta['fault_hours']}±{tol}")
    if meta.get("any_fault") is True and not (result.fault_hours or 0) > 0:
        raise SystemExit(f"FAIL {path}: expected fault hours")
    if meta.get("any_fault") is False and (result.fault_hours or 0) > 0:
        raise SystemExit(f"FAIL {path}: unexpected fault hours {result.fault_hours}")
    print(f"OK pandas {rule_id} {path.name} status={result.status} hours={result.fault_hours}")
    return out


def main() -> int:
    fixtures = sorted(ORACLE.glob("*/*/expected.json"))
    if not fixtures:
        print("FAIL: no expected.json goldens", file=sys.stderr)
        return 1
    n = 0
    for exp in fixtures:
        run_fixture(exp.parent)
        n += 1
    print(f"OK: golden_dual_compare pandas {n} fixtures (DataFusion pending unless marked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
