#!/usr/bin/env python3
"""Enforce SI product processing with narrow source/display/migration boundaries."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOTS = (
    "crates/fdd_core/src",
    "crates/fdd_tsdb/src",
    "crates/fdd_rules/src",
    "edge/src",
    "services/central/src",
    "open_fdd/analytics",
    "open_fdd/rules",
    "open_fdd/reporting",
    "open_fdd/units",
    "tools/wattlab_export/app",
    "frontend/web/src",
    "sql/fdd/postgres/rules",
    "sql/fdd/warehouse/rules",
    "sql_rules",
    "sql/analytics/postgres/queries",
)
SOURCE_SUFFIXES = {".rs", ".py", ".sql", ".ts", ".tsx"}
FORBIDDEN = (
    (re.compile(r"\bTEMPERATURE_ROLES\b"), "active temperature role conversion helper"),
    (re.compile(r"\bmetric_select_list\b"), "query-time SI/IP select conversion"),
    (re.compile(r"\bAdmitBuilder\b|\badmitted_on_sample\b|\badmitted_sample::apply_binds"), "query-time sample admission helper"),
    (re.compile(r"\bunit_system_from_session\b"), "session unit_system processing conversion"),
    (re.compile(r"\b(?:fahrenheit_to_celsius|delta_f_to_delta_c|celsius_to_fahrenheit|delta_c_to_delta_f)\s*\("), "temperature conversion outside an approved source/display/migration boundary"),
)
CONVERSION_BOUNDARIES = {
    "open_fdd/units/convert.py",  # declared-source and display conversion primitives
    "open_fdd/analytics/report_storage.py",  # user-selected report display conversion
    "services/central/src/providers/poller.rs",  # normalize declared source values only for SI validation
    "services/central/src/si_cutover_admin.rs",  # token-gated one-time saved-data migration
    "services/central/src/rcx_row_fixtures.rs",  # fixed-IP unit test fixtures
    "services/central/src/ingest_queue/writer_fence.rs",  # fixed-IP writer contract fixtures
}
CANONICAL_BOUNDARIES = {
    "crates/fdd_tsdb/src/ingest_si.rs",  # declared source unit -> SI write boundary
    "crates/fdd_tsdb/src/si_cutover.rs",  # token-gated historical storage migration
    "services/central/src/si_cutover_admin.rs",
}
CATALOGS = (
    "sql/fdd/registry.yaml",
    "sql_rules/registry.yaml",
    "sql/fdd/tuning_catalog.json",
    "sql/fdd/oracle_catalog.json",
)
LEGACY_PARAMETER_KEY = re.compile(r"(?:^|[._])[^.]*_[fF]$")
LEGACY_SQL_PARAMETER = re.compile(r"\{\{\s*[A-Za-z_]\w*_[fF]\s*\}\}")
MIGRATION_PATH = "services/central/src/si_cutover_admin.rs"
MIGRATION_CHW_LINES = (
    re.compile(r'^const\s+SESSION_CHW_LEGACY:\s*&str\s*=\s*"chw_leave_max_f";\s*$'),
    re.compile(r'^let n = v\.as_f64\(\)\.ok_or\("chw_leave_max_f must be numeric"\)\?;\s*$'),
)


def check_text(path: str, text: str) -> list[str]:
    errors: list[str] = []
    source = _without_rust_test_modules(text) if path.endswith(".rs") else text
    if path.endswith(".sql") and LEGACY_SQL_PARAMETER.search(source):
        errors.append(f"{path}: SQL parameter placeholders must use SI names")
    for pattern, label in FORBIDDEN:
        if pattern.search(source):
            if pattern.pattern.startswith(r"\b(?:fahrenheit_to_celsius") and path in CONVERSION_BOUNDARIES:
                continue
            errors.append(f"{path}: {label} remains")
    if re.search(r"\.\s*convert_to_canonical\s*\(", source) and path not in CANONICAL_BOUNDARIES:
        errors.append(f"{path}: canonical-unit conversion must remain at ingest or the token-gated migration boundary")
    if "imperial-f-v1" in source:
        errors.append(f"{path}: legacy storage ABI string is retired from product code")
    legacy_chw = [line.strip() for line in source.splitlines() if "chw_leave_max_f" in line]
    if path == MIGRATION_PATH:
        bad = [line for line in legacy_chw if not any(pattern.fullmatch(line) for pattern in MIGRATION_CHW_LINES)]
        if len(legacy_chw) != len(MIGRATION_CHW_LINES) or bad:
            errors.append(f"{path}: legacy CHW field must appear only in the exact one-time migration code")
    elif legacy_chw:
        errors.append(f"{path}: legacy CHW field is allowed only in cutover migration or test assertions")
    return errors


def _without_rust_test_modules(text: str) -> str:
    """Blank cfg(test) module bodies so tests do not define product boundaries."""
    pattern = re.compile(r"#\[cfg\(test\)\]\s*mod\s+[A-Za-z_][A-Za-z0-9_]*\s*\{")
    while match := pattern.search(text):
        open_brace = text.find("{", match.start(), match.end())
        i = _rust_matching_brace(text, open_brace)
        if i is None:
            # Fail closed: keep the source visible to policy checks if parsing fails.
            return text
        i += 1
        text = text[: match.start()] + " " * (i - match.start()) + text[i:]
    return text


def _rust_matching_brace(text: str, open_brace: int) -> int | None:
    """Find a Rust module's closing brace while skipping strings and comments."""
    depth = 0
    i = open_brace
    block_depth = 0
    while i < len(text):
        if block_depth:
            if text.startswith("/*", i):
                block_depth += 1
                i += 2
            elif text.startswith("*/", i):
                block_depth -= 1
                i += 2
            else:
                i += 1
            continue
        if text.startswith("//", i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", i):
            block_depth = 1
            i += 2
            continue
        raw_start = re.match(r"(?:b)?r(#+)?\"", text[i:])
        if raw_start:
            hashes = raw_start.group(1) or ""
            end_token = '"' + hashes
            end = text.find(end_token, i + raw_start.end())
            if end < 0:
                return None
            i = end + len(end_token)
            continue
        if text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                return None
            continue
        if text[i] == "'":
            # Skip a char literal only when a closing quote is found before whitespace.
            j = i + 1
            if j < len(text) and text[j] == "\\":
                j += 2
            else:
                j += 1
            if j < len(text) and text[j] == "'":
                i = j + 1
                continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _parameter_keys(path: str, body: object) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if path.endswith("registry.yaml"):
        try:
            import yaml
        except ImportError:
            return [(path, "PyYAML required for parameter-key scan")]
        doc = yaml.safe_load(str(body)) or {}
        rules = doc.get("rules") or []
        for rule in rules:
            rid = str(rule.get("rule_id") or "")
            for key in (rule.get("parameters") or {}):
                if LEGACY_PARAMETER_KEY.search(str(key)):
                    found.append((rid, str(key)))
    elif path.endswith("tuning_catalog.json"):
        for rule in body if isinstance(body, list) else []:
            for key in (rule.get("parameters") or {}):
                if LEGACY_PARAMETER_KEY.search(str(key)):
                    found.append((str(rule.get("rule_id") or ""), str(key)))
    else:
        for rule in body if isinstance(body, list) else []:
            for param in rule.get("params") or []:
                key = str(param.get("key") or "")
                if LEGACY_PARAMETER_KEY.search(key):
                    found.append((str(rule.get("id") or ""), key))
    return found


def scan(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for rel_root in PRODUCT_ROOTS:
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
                continue
            if path.name.endswith("_test.rs"):
                continue
            rel = path.relative_to(root).as_posix()
            errors.extend(check_text(rel, path.read_text(encoding="utf-8")))
    for rel in CATALOGS:
        path = root / rel
        if not path.is_file():
            continue
        if rel.endswith(".json"):
            body = json.loads(path.read_text(encoding="utf-8"))
        else:
            body = path.read_text(encoding="utf-8")
        for rule, key in _parameter_keys(rel, body):
            if key == "PyYAML required for parameter-key scan":
                errors.append(key)
            else:
                errors.append(f"{rel} {rule}.{key}: active parameter keys must use SI names")
    return errors


def self_test() -> None:
    migration = 'const SESSION_CHW_LEGACY: &str = "chw_leave_max_f";\nlet n = v.as_f64().ok_or("chw_leave_max_f must be numeric")?;\n'
    assert not check_text(MIGRATION_PATH, migration)
    assert check_text("services/central/src/sql_pack.rs", migration)
    assert check_text("services/central/src/new_module.rs", "fn c(v: f64) -> f64 { fahrenheit_to_celsius(v) }\n")
    assert check_text("sql/fdd/rules/new_rule.sql", "WHERE zone_t < {{COMFORT_LOW_F}}\n")
    assert not check_text("services/central/src/providers/poller.rs", "let check = fahrenheit_to_celsius(raw);\n")
    assert not check_text("open_fdd/analytics/report_storage.py", "return delta_f_to_delta_c(threshold)\n")
    assert check_text("edge/src/fdd/session_config.rs", 'fn f() { let x = "chw_leave_max_f"; }')
    assert check_text("services/central/src/timescale_product.rs", "const TEMPERATURE_ROLES: &[&str] = &[];")
    assert _parameter_keys("sql/fdd/tuning_catalog.json", [{"rule_id": "TEST", "parameters": {"comfort_low_f": {}}}]) == [("TEST", "comfort_low_f")]
    assert _parameter_keys("sql/fdd/oracle_catalog.json", [{"id": "TEST", "params": [{"key": "delta_f"}]}]) == [("TEST", "delta_f")]
    rust = '#[cfg(test)] mod test { const S: &str = "}"; /* { } */ }\nfn active() { fahrenheit_to_celsius(1.0); }'
    stripped = _without_rust_test_modules(rust)
    assert "const S" not in stripped and "fn active" in stripped
    assert check_text("services/central/src/active.rs", stripped)
    print("PASS no-imperial guard fixtures: module discovery, parameter names, and approved boundaries")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test()
    errors = scan()
    if errors:
        print("FAIL SI-first product guard:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("PASS active product source and catalogs use SI processing contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
