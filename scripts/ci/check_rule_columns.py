#!/usr/bin/env python3
"""T1405-3 — registry column contract for Timescale FDD rules.

Every bare history column a rule reads in its primary ``FROM history`` SELECT
must appear in ``required_roles`` or ``optional_roles`` (plus structural
``equipment_id`` / ``timestamp_utc``).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("FAIL: PyYAML required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "sql" / "fdd" / "registry.yaml"
RULES_DIR = ROOT / "sql" / "fdd" / "postgres" / "rules"

SQL_KEYWORDS = frozenset(
    """
    select from where and or case when then else end as with join on not null is
    coalesce cast int bigint double precision extract epoch lead lag over partition
    by order rows unbounded preceding sum count distinct filter exists true false
    between in inner left cross lateral values returning group having limit offset
    union all any some into double int8 float8 text varchar boolean bool asc desc
    """.split()
)

STRUCTURAL = frozenset({"equipment_id", "timestamp_utc"})


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def history_role_reads(sql: str) -> set[str]:
    roles: set[str] = set()
    lower = sql.lower()
    for match in re.finditer(r"\bfrom\s+history\b(?!\w)", lower):
        pos = match.start()
        chunk = sql[:pos]
        sel = chunk.rfind("SELECT")
        if sel < 0:
            continue
        select_part = sql[sel + 6 : pos].strip()
        select_part = re.sub(r"--[^\n]*", "", select_part)
        for item in split_top_level_commas(select_part):
            item = item.strip()
            if not item:
                continue
            alias = re.search(r"\bas\s+([a-z][a-z0-9_]*)\s*$", item, re.I)
            if alias:
                expr = item[: alias.start()].strip()
                if re.fullmatch(r"[a-z][a-z0-9_]*", expr, re.I):
                    roles.add(expr.lower())
                continue
            if re.fullmatch(r"[a-z][a-z0-9_]*", item, re.I):
                roles.add(item.lower())
    return roles


def declared_roles(rule: dict) -> set[str]:
    out = set(STRUCTURAL)
    out.update(str(r).lower() for r in rule.get("required_roles") or [])
    out.update(str(r).lower() for r in rule.get("optional_roles") or [])
    return out


def sql_history_roles_for_rule(rule: dict) -> set[str]:
    sql_file = rule.get("sql_file")
    if not sql_file:
        return set()
    path = RULES_DIR / str(sql_file)
    if not path.is_file():
        return set()
    return history_role_reads(path.read_text(encoding="utf-8"))


def check_registry() -> None:
    if not REGISTRY.is_file():
        fail(f"missing {REGISTRY.relative_to(ROOT)}")
    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    rules = doc.get("rules")
    if not isinstance(rules, list):
        fail("registry.yaml rules must be a list")

    violations: list[str] = []
    for rule in rules:
        rule_id = rule.get("rule_id")
        sql_file = rule.get("sql_file")
        if not rule_id or not sql_file:
            fail("registry entry missing rule_id or sql_file")
        path = RULES_DIR / str(sql_file)
        if not path.is_file():
            violations.append(f"{rule_id}: missing SQL file {path.relative_to(ROOT)}")
            continue
        sql = path.read_text(encoding="utf-8")
        declared = declared_roles(rule)
        for col in sorted(history_role_reads(sql) - declared):
            violations.append(f"{rule_id}: history column `{col}` not in required_roles or optional_roles")

    if violations:
        for line in violations:
            print(line, file=sys.stderr)
        fail(f"{len(violations)} rule column contract violation(s)")

    print(f"PASS rule column contract ({len(rules)} rules)")


def self_test() -> None:
    sample = """
    WITH h AS (
      SELECT equipment_id, timestamp_utc, hw_supply_t, hw_reset_request_sum
      FROM history
    )
    SELECT * FROM h
    """
    got = history_role_reads(sample)
    want = {"equipment_id", "timestamp_utc", "hw_supply_t", "hw_reset_request_sum"}
    if got != want:
        fail(f"self-test history_role_reads: got {sorted(got)} want {sorted(want)}")

    from unit_contract_lib import validate_registry_role_declarations_diff

    trim3 = {
        "rule_id": "TRIM-3",
        "sql_file": "trim3_hwst.sql",
        "required_roles": ["hw_supply_t"],
        "optional_roles": ["pump_status", "chiller_status", "chw_flow", "chw_pump_cmd"],
    }
    master = {"rules": [trim3]}
    bad_optional = {
        "rules": [
            {
                **trim3,
                "optional_roles": trim3["optional_roles"] + ["totally_fake_role"],
            }
        ]
    }
    try:
        validate_registry_role_declarations_diff(master, bad_optional)
    except AssertionError as exc:
        if "totally_fake_role" not in str(exc):
            fail(f"self-test expected unjustified optional_roles failure, got: {exc}")
    else:
        fail("self-test: unjustified optional_roles addition must fail registry diff guard")

    bad_required = {
        "rules": [{**trim3, "required_roles": ["hw_supply_t", "chw_flow"]}]
    }
    try:
        validate_registry_role_declarations_diff(master, bad_required)
    except AssertionError as exc:
        if "required_roles changed" not in str(exc):
            fail(f"self-test expected required_roles failure, got: {exc}")
    else:
        fail("self-test: required_roles change must fail registry diff guard")

    print("PASS check_rule_columns self-test")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test()
        return
    check_registry()


if __name__ == "__main__":
    main()
