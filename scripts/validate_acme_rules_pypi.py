#!/usr/bin/env python3
"""Compile and smoke-run Acme Arrow rules via ``open_fdd.arrow_runtime`` (PyPI parity)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pyarrow as pa

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "workspace" / "data" / "rules_py"


def _assert_wheel_import() -> None:
    """Fail CI smoke when PYTHONPATH forces a repo checkout over the installed wheel."""
    import open_fdd

    mod = Path(getattr(open_fdd, "__file__", "") or "").resolve()
    repo = REPO.resolve()
    if mod.is_relative_to(repo):
        raise SystemExit(
            f"open_fdd loaded from repo ({mod}), not site-packages — unset PYTHONPATH for wheel smoke"
        )


def main() -> int:
    if os.environ.get("OFDD_WHEEL_SMOKE", "").strip().lower() in {"1", "true", "yes"}:
        _assert_wheel_import()
    from open_fdd.arrow_runtime import run_arrow_rule
    from open_fdd.playground.sandbox import lint_python

    acme_files = sorted(RULES.glob("acme_*.py"))
    if not acme_files:
        print("no acme_*.py rules found", file=sys.stderr)
        return 1

    table = pa.table(
        {
            "ts": ["2024-06-01 08:00:00"] * 72,
            "ts_ms": [1_700_000_000_000 + i * 60_000 for i in range(72)],
            "temp": [72.0] * 72,
            "temp_rolling_avg": [72.0] * 72,
            "SAT": [72.0] * 72,
            "RAT": [68.0] * 72,
            "OAT": [55.0] * 72,
            "value_kind": ["temp"] * 72,
            "value_column": ["test"] * 72,
        }
    )
    cfg = {
        "bounds_low": 65,
        "bounds_high": 80,
        "flatline_tolerance": 0.5,
        "temp_unit": "imperial",
    }

    failed = 0
    for path in acme_files:
        code = path.read_text(encoding="utf-8")
        lint = lint_python(code, require_evaluate=False, strict_imports=True)
        if not lint["ok"]:
            only_no_arrow = all(
                i.get("severity") == "error" and "apply_faults_arrow" in str(i.get("message", ""))
                for i in lint.get("issues", [])
            )
            if only_no_arrow and lint.get("issues"):
                print(f"SKIP {path.name} (script mode, no apply_faults_arrow)")
                continue
            print(f"FAIL {path.name}: lint errors", file=sys.stderr)
            for issue in lint.get("issues", []):
                if issue.get("severity") == "error":
                    print(f"  {issue.get('message')}", file=sys.stderr)
            failed += 1
            continue
        try:
            result = run_arrow_rule(code, table, cfg, rule_id=path.stem)
            if result.errors:
                raise RuntimeError("; ".join(result.errors))
            print(f"OK  {path.name}")
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
