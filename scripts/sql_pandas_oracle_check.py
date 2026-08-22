#!/usr/bin/env python3
"""CI-only pandas oracle vs committed expectations (Wave 0).

Installs/uses the real ``open_fdd.rules`` package — does not reimplement masks.
Does not import removed Vibe19 modules. Python is never a product runtime dependency.

DataFusion side remains in ``crates/fdd_rules`` tests; this job fails loudly if
the oracle package or required seed fixtures are missing.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "sql_rules" / "generated" / "parity_inventory.yaml"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_inventory():
    try:
        import yaml
    except ImportError:
        fail("PyYAML required")
    if not INVENTORY.is_file():
        fail("parity_inventory.yaml missing — generate first")
    return yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))


def _remove_checkout_import_paths() -> None:
    """Prevent the checkout from shadowing an externally installed oracle."""
    for raw in list(sys.path):
        try:
            resolved = Path(raw or ".").resolve()
        except OSError:
            continue
        if resolved in {ROOT, ROOT / "scripts"}:
            sys.path.remove(raw)


def _assert_external_module(module_path: Path) -> None:
    try:
        module_path.relative_to(ROOT)
    except ValueError:
        pass
    else:
        fail(f"external oracle resolved inside checkout: {module_path}")

    if not any(part in {"site-packages", "dist-packages"} for part in module_path.parts):
        fail(f"external oracle is not installed from site/dist-packages: {module_path}")


def import_oracle(require_external: bool = False):
    if require_external:
        _remove_checkout_import_paths()
    try:
        import open_fdd.rules as rules_module  # type: ignore
        from open_fdd.rules import RULES_BY_ID, run_rule  # type: ignore
        from open_fdd.rules.cookbook_catalog import RULES  # type: ignore
    except ImportError as e:
        fail(
            "open_fdd.rules oracle not importable — CI must pip install "
            f"open-fdd[oracle] (or editable .[oracle]). Import error: {e}"
        )

    module_file = getattr(rules_module, "__file__", None)
    if not module_file:
        fail("open_fdd.rules has no importable module file")
    module_path = Path(module_file).resolve()
    try:
        package_version = importlib.metadata.version("open-fdd")
    except importlib.metadata.PackageNotFoundError:
        package_version = "unknown"

    if require_external:
        _assert_external_module(module_path)

    print(f"oracle package version={package_version} module={module_path}")

    if len(RULES) < 62:
        fail(f"canonical RULES shrunk: {len(RULES)} < 59")
    if "SV-SLEW" not in RULES_BY_ID:
        fail("RULES_BY_ID missing SV-SLEW alias")
    if "SV-RATE" not in RULES_BY_ID:
        fail("RULES_BY_ID missing SV-RATE")
    if RULES_BY_ID["SV-SLEW"] is not RULES_BY_ID["SV-RATE"]:
        fail("SV-SLEW must alias SV-RATE")
    return RULES_BY_ID, run_rule


def load_history_csv(path: Path):
    import pandas as pd

    df = pd.read_csv(path)
    if "timestamp_utc" in df.columns:
        ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    elif "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True)
    else:
        fail(f"{path}: need timestamp_utc or timestamp column")
    df = df.copy()
    df.index = ts
    df.index.name = "timestamp"
    return df.sort_index()


def apply_role_map(df, columns_csv: Path):
    """Rename CSV columns to cookbook roles using columns.csv (col,point_role)."""
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


def run_seeds(run_rule, inventory) -> int:
    import pandas as pd

    n = 0
    for concept in inventory.get("concepts") or []:
        if concept.get("kind") != "diagnostic":
            continue
        pandas_id = concept.get("pandas_id")
        for fx in concept.get("proof_fixtures") or []:
            if not fx.get("oracle_seed"):
                continue
            path = ROOT / fx["path"]
            hist = path / "history_wide.csv"
            expected_path = path / "expected.json"
            meta = json.loads(expected_path.read_text(encoding="utf-8"))
            rule_id = meta.get("pandas_rule_id") or pandas_id
            if not rule_id:
                fail(f"{fx['path']}: no pandas_rule_id")

            if meta.get("expect_missing_roles"):
                df = load_history_csv(hist) if hist.is_file() else pd.DataFrame(
                    index=pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True)
                )
                df = apply_role_map(df, path / "columns.csv")
                df.attrs["equipment_id"] = meta.get("equipment_id", "EQ_1")
                df.attrs["equipment_type"] = meta.get("equipment_type", "VAV")
                result = run_rule(rule_id, df, poll_seconds=float(meta.get("poll_seconds", 300)))
                status = getattr(result, "status", "")
                missing = list(getattr(result, "missing_roles", None) or [])
                if status != "SKIPPED_MISSING_ROLES" and not missing:
                    fail(
                        f"{fx['path']}: expected SKIPPED_MISSING_ROLES for {rule_id}, "
                        f"got status={status!r} missing={missing!r}"
                    )
                print(f"OK seed missing-role {rule_id} @ {fx['path']} missing={missing}")
                n += 1
                continue

            df = load_history_csv(hist)
            df = apply_role_map(df, path / "columns.csv")
            df.attrs["equipment_id"] = meta.get("equipment_id", "AHU_1")
            params = meta.get("params") or {}
            result = run_rule(
                rule_id,
                df,
                params=params,
                poll_seconds=float(meta.get("poll_seconds", 300)),
            )
            fault_hours = float(getattr(result, "fault_hours", 0.0) or 0.0)
            expect_hours = meta.get("fault_hours")
            expect_any = meta.get("any_fault")
            if expect_hours is not None:
                tol = float(meta.get("fault_hours_tol", 0.05))
                if abs(fault_hours - float(expect_hours)) > tol:
                    fail(
                        f"{fx['path']}: pandas {rule_id} fault_hours={fault_hours} "
                        f"want {expect_hours} ±{tol}"
                    )
            if expect_any is True and fault_hours <= 0:
                fail(f"{fx['path']}: expected any fault for {rule_id}")
            if expect_any is False and fault_hours > 0:
                fail(f"{fx['path']}: expected no fault for {rule_id}, got {fault_hours}")
            print(
                f"OK seed {rule_id} @ {fx['path']} fault_hours={fault_hours} "
                f"(df_compare={meta.get('datafusion_compare', 'rust_test')})"
            )
            n += 1
    if n < 3:
        fail(f"ran {n} seeds; need >=3")
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--require-package",
        action="store_true",
        default=True,
        help="fail if open_fdd.rules cannot be imported (default)",
    )
    ap.add_argument(
        "--require-external-oracle",
        action="store_true",
        help="require open_fdd.rules to come from an installed site/dist-packages path outside this checkout",
    )
    args = ap.parse_args()
    _ = args.require_package

    inv = load_inventory()
    _, run_rule = import_oracle(require_external=args.require_external_oracle)
    n = run_seeds(run_rule, inv)
    print(f"OK: sql_pandas_oracle_check ({n} seed fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
