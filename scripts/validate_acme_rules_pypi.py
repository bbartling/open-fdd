#!/usr/bin/env python3
"""Compile and smoke-sweep Acme expression rules via ``open_fdd.playground`` (PyPI parity)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    from open_fdd.playground.sandbox import compile_evaluate, lint_python, sweep_rule

    acme_files = sorted(RULES.glob("acme_*.py"))
    if not acme_files:
        print("no acme_*.py rules found", file=sys.stderr)
        return 1

    rows = [
        {
            "row": i,
            "ts_ms": 1_700_000_000_000 + i * 60_000,
            "ts": "2024-06-01 08:00:00",
            "temp": 72.0,
            "temp_rolling_avg": 72.0,
            "value_kind": "temp",
            "value_column": "test",
        }
        for i in range(72)
    ]
    cfg = {
        "bounds_low": 65,
        "bounds_high": 80,
        "flatline_tolerance": 0.5,
        "temp_unit": "imperial",
    }

    failed = 0
    for path in acme_files:
        code = path.read_text(encoding="utf-8")
        lint = lint_python(code, require_evaluate=True, strict_imports=True)
        if not lint["ok"]:
            only_missing_eval = all(
                i.get("severity") == "error" and "evaluate" in str(i.get("message", ""))
                for i in lint.get("issues", [])
            )
            if only_missing_eval and lint.get("issues"):
                print(f"SKIP {path.name} (dataframe script, no evaluate)")
                continue
            print(f"FAIL {path.name}: lint errors", file=sys.stderr)
            for issue in lint.get("issues", []):
                if issue.get("severity") == "error":
                    print(f"  {issue.get('message')}", file=sys.stderr)
            failed += 1
            continue
        try:
            compile_evaluate(code)
            sweep_rule(code, cfg, rows[-10:], capture_print=False)
            print(f"OK  {path.name}")
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
