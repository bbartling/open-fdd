#!/usr/bin/env python3
"""Embed shipped PostgreSQL into the public rule cookbooks.

Rewrites docs/rules/sql-analytics-cookbook.md from sql/analytics/registry.json
and refreshes the shipped-SQL section of
docs/rules/cookbook/sql-cookbook.md from sql/fdd/postgres/rules/.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_MD = ROOT / "docs" / "rules" / "sql-analytics-cookbook.md"
FDD_MD = ROOT / "docs" / "rules" / "cookbook" / "sql-cookbook.md"
REGISTRY = ROOT / "sql" / "analytics" / "registry.json"
QUERY_DIR = ROOT / "sql" / "analytics" / "postgres" / "queries"
RULE_DIR = ROOT / "sql" / "fdd" / "postgres" / "rules"
HELPER = ROOT / "sql" / "fdd" / "postgres" / "postgres_helpers.sql"

START = "<!-- shipped-sql:start -->"
END = "<!-- shipped-sql:end -->"
POINTER = (
    "The sketches under each rule explain the check. "
    "The SQL the product runs is in [Shipped SQL files](#shipped-sql-files)."
)


def fence(sql: str, raw: bool) -> str:
    body = sql.strip() + "\n"
    block = f"```sql\n{body}```\n"
    if raw:
        return "{% raw %}\n" + block + "{% endraw %}\n"
    return block


def analytics_page() -> str:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    queries = registry["queries"]
    listed = {q["sql_path"] for q in queries}
    extras = sorted(
        p
        for p in QUERY_DIR.glob("*.sql")
        if f"sql/analytics/postgres/queries/{p.name}" not in listed
    )

    lines = [
        "---",
        "title: SQL analytics cookbook",
        "parent: Rule Cookbook",
        "nav_order: 4",
        "permalink: /rules/sql-analytics-cookbook/",
        "---",
        "",
        "# SQL analytics cookbook",
        "",
        "Overview, RCx, and plant-health analytics are PostgreSQL on the time-series database. "
        "Rust binds `$1` to the site. The operator UI calls `/api/analytics/*`. "
        "Every query under `sql/analytics/postgres/queries/` is copied below.",
        "",
        "| Query | File |",
        "| --- | --- |",
    ]
    for query in queries:
        qid = query["query_id"]
        path = query["sql_path"]
        lines.append(f"| `{qid}` | [`{Path(path).name}`](#{qid}) |")
    lines.append("")
    for query in queries:
        qid = query["query_id"]
        path = query["sql_path"]
        sql = (ROOT / path).read_text(encoding="utf-8")
        aliases = query.get("aliases") or []
        alias = ""
        if aliases:
            alias = " Also used as " + ", ".join(f"`{a}`" for a in aliases) + "."
        lines.append(f"## {qid}")
        lines.append("")
        lines.append(f"`{path}`.{alias}")
        lines.append("")
        lines.append(fence(sql, raw=False).rstrip())
        lines.append("")
    if extras:
        lines.append("## Other query files")
        lines.append("")
        for path in extras:
            rel = path.relative_to(ROOT).as_posix()
            lines.append(f"### {path.name}")
            lines.append("")
            lines.append(f"`{rel}`")
            lines.append("")
            lines.append(fence(path.read_text(encoding="utf-8"), raw=False).rstrip())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def shipped_section() -> str:
    rules = sorted(RULE_DIR.glob("*.sql"))
    parts = [
        START,
        "",
        "## Shipped SQL files",
        "",
        "These are the PostgreSQL files the product runs, copied from "
        "`sql/fdd/postgres/rules/` plus `postgres_helpers.sql`. "
        "Tokens in double braces, such as FLATLINE_ROWS, are fill-in parameters.",
        "",
        "| File |",
        "| --- |",
    ]
    names = [p.name for p in rules] + [HELPER.name]
    for name in names:
        parts.append(f"| [`{name}`](#{name.replace('.', '')}) |")
    parts.append("")
    for path in rules:
        rel = path.relative_to(ROOT).as_posix()
        parts.append(f"### {path.name}")
        parts.append("")
        parts.append(f"`{rel}`")
        parts.append("")
        parts.append(fence(path.read_text(encoding="utf-8"), raw=True).rstrip())
        parts.append("")
    rel = HELPER.relative_to(ROOT).as_posix()
    parts.append(f"### {HELPER.name}")
    parts.append("")
    parts.append(f"`{rel}`")
    parts.append("")
    parts.append(fence(HELPER.read_text(encoding="utf-8"), raw=True).rstrip())
    parts.append("")
    parts.append(END)
    return "\n".join(parts) + "\n"


def update_fdd(section: str) -> None:
    text = FDD_MD.read_text(encoding="utf-8")
    if START in text and END in text:
        pre, rest = text.split(START, 1)
        _, post = rest.split(END, 1)
        text = pre.rstrip() + "\n\n" + section + post.lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + section
    if POINTER not in text:
        needle = "**Updated:**"
        if needle not in text:
            raise SystemExit("datafusion cookbook intro marker missing")
        text = text.replace(needle, POINTER + "\n\n" + needle, 1)
    toc_line = "17. [Shipped SQL files](#shipped-sql-files)\n"
    if toc_line not in text:
        old = "16. [Framework & parity docs](#framework--parity-docs)\n"
        if old not in text:
            raise SystemExit("datafusion cookbook TOC marker missing")
        text = text.replace(old, old + toc_line, 1)
    FDD_MD.write_text(text, encoding="utf-8")


def main() -> None:
    ANALYTICS_MD.write_text(analytics_page(), encoding="utf-8")
    update_fdd(shipped_section())
    print(f"wrote {ANALYTICS_MD.relative_to(ROOT)}")
    print(f"updated {FDD_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
