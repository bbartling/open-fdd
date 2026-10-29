#!/usr/bin/env python3
"""Regenerate CI ip goldens and require semantic match with committed files (#1284 W0c)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GOLDENS = ROOT / "tests" / "fixtures" / "si_cutover" / "ip_goldens"


def _row_key(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("rule_id", "")),
        str(row.get("equipment_id", "")),
        str(row.get("utc_day", "")),
        str(row.get("pair_status", "")),
        str(row.get("reason", "")),
    )


def _sorted_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return sorted(list(rows or []), key=_row_key)


def _computed_daily(rows: list[dict[str, Any]] | None) -> dict[tuple, dict[str, float]]:
    out: dict[tuple, dict[str, float]] = {}
    for row in rows or []:
        if row.get("pair_status") != "computed" or not row.get("utc_day"):
            continue
        key = (
            str(row.get("rule_id", "")),
            str(row.get("equipment_id", "")),
            str(row.get("utc_day", "")),
        )
        out[key] = {
            "fault_seconds": float(row.get("fault_seconds", 0)),
            "covered_seconds": float(row.get("covered_seconds", 0)),
        }
    return out


def golden_semantic_diff(committed: dict[str, Any], regen: dict[str, Any]) -> list[str]:
    from scripts.stress.si_cutover.parity_chain import fault_seconds_equal

    errors: list[str] = []
    for key in (
        "schema",
        "schema_version",
        "building_id",
        "equipment_id",
        "equipment_type",
        "poll_seconds",
        "pandas_rules_attempted",
    ):
        if committed.get(key) != regen.get(key):
            errors.append(f"{key}: committed={committed.get(key)!r} regen={regen.get(key)!r}")

    for label, rows_key in (
        ("pandas_fdd_daily", "pandas_fdd_daily"),
        ("pandas_si_daily", "pandas_si_daily"),
    ):
        a = _computed_daily(committed.get(rows_key))
        b = _computed_daily(regen.get(rows_key))
        if set(a) != set(b):
            errors.append(f"{label} computed key set mismatch")
            continue
        for key, vals_a in a.items():
            vals_b = b[key]
            if not fault_seconds_equal(vals_a["fault_seconds"], vals_b["fault_seconds"]):
                errors.append(
                    f"{label} fault_seconds {key}: committed={vals_a['fault_seconds']} "
                    f"regen={vals_b['fault_seconds']}"
                )

    p2_a = _sorted_rows(committed.get("p2_si_pairs"))
    p2_b = _sorted_rows(regen.get("p2_si_pairs"))
    if len(p2_a) != len(p2_b):
        errors.append("p2_si_pairs length mismatch")
    else:
        for ra, rb in zip(p2_a, p2_b, strict=True):
            if str(ra.get("rule_id")) != str(rb.get("rule_id")):
                errors.append("p2_si_pairs rule_id mismatch")
                break
            if str(ra.get("utc_day")) != str(rb.get("utc_day")):
                errors.append("p2_si_pairs utc_day mismatch")
                break
            if str(ra.get("sql_si_status")) != str(rb.get("sql_si_status")):
                errors.append("p2_si_pairs sql_si_status mismatch")
                break

    sql_a = { _row_key(r): r for r in committed.get("sql_fdd_daily") or [] }
    sql_b = { _row_key(r): r for r in regen.get("sql_fdd_daily") or [] }
    if set(sql_a) != set(sql_b):
        missing = sorted(set(sql_a) - set(sql_b))[:3]
        extra = sorted(set(sql_b) - set(sql_a))[:3]
        errors.append(f"sql_fdd_daily key set mismatch missing={missing} extra={extra}")
    for key, row_a in sql_a.items():
        row_b = sql_b.get(key)
        if row_b is None:
            continue
        if str(row_a.get("status", "")) != str(row_b.get("status", "")):
            errors.append(f"sql status {key}: {row_a.get('status')} vs {row_b.get('status')}")
        if not fault_seconds_equal(
            row_a.get("fault_seconds", 0), row_b.get("fault_seconds", 0)
        ):
            errors.append(
                f"sql fault_seconds {key}: committed={row_a.get('fault_seconds')} "
                f"regen={row_b.get('fault_seconds')}"
            )
    return errors


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        print("FAIL ip_goldens: OPENFDD_DATABASE_URL required for regeneration check", file=sys.stderr)
        return 1
    from scripts.stress.si_cutover.ci_fixtures_lib import emit_all_goldens

    with tempfile.TemporaryDirectory(prefix="ip-goldens-regen-") as tmp:
        tmp_dir = Path(tmp)
        emit_all_goldens(tmp_dir, database_url=url)
        committed = sorted(GOLDENS.glob("*.json"))
        generated = sorted(tmp_dir.glob("*.json"))
        if [p.name for p in committed] != [p.name for p in generated]:
            print(
                "FAIL ip_goldens: file set mismatch\n"
                f"  committed: {[p.name for p in committed]}\n"
                f"  generated: {[p.name for p in generated]}",
                file=sys.stderr,
            )
            return 1
        for path in committed:
            committed_doc = json.loads(path.read_text(encoding="utf-8"))
            regen_doc = json.loads((tmp_dir / path.name).read_text(encoding="utf-8"))
            diffs = golden_semantic_diff(committed_doc, regen_doc)
            if diffs:
                print(
                    f"FAIL ip_goldens: {path.name} semantic drift: "
                    + "; ".join(diffs[:5]),
                    file=sys.stderr,
                )
                return 1
    print(f"PASS ip_goldens frozen ({len(committed)} files semantic match)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
