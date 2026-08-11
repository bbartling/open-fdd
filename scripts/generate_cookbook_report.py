#!/usr/bin/env python3
"""Generate docs/rules/cookbook/generated-parity-report.md from the inventory."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "sql_rules" / "generated" / "parity_inventory.yaml"
OUT = ROOT / "docs" / "rules" / "cookbook" / "generated-parity-report.md"


def render(inv: dict) -> str:
    counts = inv["counts"]
    lines = [
        "---",
        "title: Generated parity report",
        "parent: Rule Cookbook",
        "nav_order: 7",
        "---",
        "",
        "# Generated parity report",
        "",
        "Auto-generated from `sql_rules/generated/parity_inventory.yaml`.",
        "Do not edit by hand. Run `python3 scripts/generate_cookbook_report.py`.",
        "",
        inv["count_explanation"],
        "",
        f"- Pandas diagnostics: **{counts['pandas_diagnostics']}**",
        f"- SQL analytics: **{counts['sql_analytics']}**",
        f"- SQL registry: **{counts['sql_registry']}**",
        f"- Building 100 cartesian: {counts['building_100_cartesian']}",
        "",
        "## Difference classes",
        "",
        "| Class | Count |",
        "| --- | ---: |",
    ]
    for k, v in sorted((inv.get("difference_class_counts") or {}).items()):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "## Matrix",
        "",
        "| rule_id | title | pandas | SQL | parity | class |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in inv.get("matrix") or []:
        lines.append(
            "| `{id}` | {title} | `{pd}` | `{sql}` | `{par}` | `{cls}` |".format(
                id=row["rule_id"],
                title=(row.get("title") or "").replace("|", "/"),
                pd=row.get("pandas_implementation") or "—",
                sql=row.get("datafusion_sql_implementation") or "—",
                par=row.get("parity_status"),
                cls=row.get("difference_class"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    inv = yaml.safe_load(INV.read_text(encoding="utf-8"))
    text = render(inv)
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print("FAIL: generated-parity-report.md is stale", flush=True)
            return 1
        print("OK: generated-parity-report.md")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
