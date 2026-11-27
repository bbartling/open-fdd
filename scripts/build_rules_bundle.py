#!/usr/bin/env python3
"""Build the pinnable rules bundle ``dist/open-fdd-rules-<version>.zip`` plus ``.zip.sha256`` (#1806). Stdlib only.

    python scripts/build_rules_bundle.py                    # version from VERSION
    python scripts/build_rules_bundle.py --version 5.0.22   # or v5.0.22 (a tag)
    python scripts/build_rules_bundle.py --check            # two fresh builds are byte-identical, manifest is complete,
                                                            # and an existing dist zip of that version matches

Bundle layout (every text file LF, UTF-8):

    rules-manifest.json        per rule: id, title, equipment kinds, inputs (roles-file role, unit, required),
                               confirm_min, output columns, dialect notes, parity status; "files": sha256 + size of
                               every other entry
    rules/postgres/<ID>.sql    rule SQL rendered at the shipped defaults (nf-app/rules/pack-postgres.json); PostgreSQL,
                               TimescaleDB and DuckDB run these files unchanged
    rules/sqlite/<ID>.sql      the SQLite translation (nf-app/rules/pack-sqlite.json)
    helpers/postgres.sql       fdd.* helper functions (sql/fdd/postgres/postgres_helpers.sql)
    helpers/duckdb.sql         the same helpers as DuckDB macros (sql/fdd/duckdb/duckdb_helpers.sql, #1645)
    schema/core.sql            fdd.point, fdd.rule_result, fdd.rule_config (sql/fdd/schema/core.sql, unchanged)
    schema/core.duckdb.sql     the same tables for DuckDB (jsonb -> JSON, no identity, no partial index)
    schema/input_sample.sql    fdd.input_sample reference table (the column signature of input_contract.json "sources")
    schema/inputs.sql          the tables the rules read: history, weather, sensor_history, ... (input_contract.sql)
    roles/openfdd-roles.json   the canonical role vocabulary the input names and units come from (unchanged bytes)
    templates/...              the unrendered templates and their renderer at their repo paths, for hosts that
                               re-render with other parameters: python templates/sql/fdd/render_rule.py FC1 --params '{}'

Input names and units come from the canonical role vocabulary ``roles/openfdd-roles.json`` (223P-derived role ids,
matched on ``legacy_keys``); the build fails when a contract role has no roles-file entry. The zip has sorted entries,
fixed timestamps and fixed attributes, so the same sources give the same sha256 with the same zlib build.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "nf"))
import docs_units  # noqa: E402  (stdlib-only shared parity facts)

PACK_PG = ROOT / "nf-app" / "rules" / "pack-postgres.json"
PACK_SQLITE = ROOT / "nf-app" / "rules" / "pack-sqlite.json"
CATALOG = ROOT / "nf-app" / "static" / "fdd-catalog.json"
CONTRACT = ROOT / "sql" / "fdd" / "input_contract.json"
CONTRACT_SQL = ROOT / "sql" / "fdd" / "input_contract.sql"
ROLES = ROOT / "roles" / "openfdd-roles.json"
CORE_SQL = ROOT / "sql" / "fdd" / "schema" / "core.sql"
PG_HELPERS = ROOT / "sql" / "fdd" / "postgres" / "postgres_helpers.sql"
DUCK_HELPERS = ROOT / "sql" / "fdd" / "duckdb" / "duckdb_helpers.sql"
VERSION_FILE = ROOT / "VERSION"
DIST = ROOT / "dist"
# What sql/fdd/render_rule.py reads, shipped at the same relative paths under templates/.
TEMPLATE_FILES = ["sql/fdd/render_rule.py", "sql/fdd/tuning_catalog.json", "sql/fdd/runtime_defaults.json",
                  "sql/fdd/role_map.json", "open_fdd/rules/sensor_sweep_catalog.py",
                  "open_fdd/data/sensor_sweep_roles.json", "open_fdd/data/sensor_sweep_limits.json"]
TEMPLATE_GLOB = "sql/fdd/postgres/rules/*.sql"

MANIFEST_VERSION = 2
CONFIRM_MIN_DEFAULT = 15
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
# input_contract.json scale -> what the rule SQL column holds
SQL_SCALE = {"fraction": "0-1", "boolean": "0/1", "percent_rh": "%RH 0-100", "text": "text"}
# core.sql -> DuckDB: each substitution must apply, so a core schema change fails the build instead of shipping drift.
CORE_DUCKDB_SUBS = [
    (r"jsonb_typeof\((\w+)\) = 'object'", r"json_type(\1) = 'OBJECT'"),
    (r"\bjsonb\b", "JSON"),
    (r" GENERATED ALWAYS AS IDENTITY", ""),
    (r"CREATE UNIQUE INDEX IF NOT EXISTS rule_config_one_active [^\n]*\n", ""),
]
SQL_TYPE = {"text": "text", "timestamp": "timestamptz", "double": "double precision"}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_version(arg: str | None) -> str:
    v = (arg or _text(VERSION_FILE)).strip()
    v = v[1:] if v.startswith("v") else v
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.-]+)?", v):
        raise SystemExit(f"bad version {v!r}")
    return v


def core_duckdb(core: str) -> str:
    out = core
    for pat, rep in CORE_DUCKDB_SUBS:
        out, n = re.subn(pat, rep, out)
        if n == 0:
            raise SystemExit(f"core.sql -> DuckDB: pattern {pat!r} no longer matches; update CORE_DUCKDB_SUBS")
    head = ("-- Generated by scripts/build_rules_bundle.py from schema/core.sql for DuckDB: jsonb -> JSON, no identity column,\n"
            "-- no partial unique index (enforce one active rule_config revision per scope in the application).\n")
    return head + out


def input_sample_sql(contract: dict) -> str:
    src = contract["sources"]["input_sample"]
    cols = ",\n".join(f"  {name:<10} {SQL_TYPE[c['type']]} NOT NULL" for name, c in src["columns"].items())
    return ("-- Generated by scripts/build_rules_bundle.py from sql/fdd/input_contract.json (sources.input_sample).\n"
            "-- Reference store for a host without its own sample store. The contract is the column signature: a host may\n"
            "-- instead expose a VIEW fdd.input_sample with these columns over its own historian (NF does).\n"
            f"-- {src['doc']}\n"
            "CREATE SCHEMA IF NOT EXISTS fdd;\n"
            f"CREATE TABLE IF NOT EXISTS fdd.input_sample (\n{cols},\n  PRIMARY KEY (site_id, point_key, ts)\n);\n")


def role_inputs(contract: dict, roles_doc: dict) -> dict[str, dict]:
    """Contract role key -> its roles-file role (223P-derived id, unit as the roles file spells it, SQL scale)."""
    by_key: dict[str, list[dict]] = {}
    for r in roles_doc["roles"]:
        for key in r.get("legacy_keys") or []:
            by_key.setdefault(key, []).append(r)
    units = roles_doc["units"]
    out, errs = {}, []
    for key, spec in sorted(contract["roles"].items()):
        hits = by_key.get(key, [])
        if len(hits) != 1:
            errs.append(f"{key}: {len(hits)} roles-file entries list it in legacy_keys (need exactly 1)")
            continue
        r = hits[0]
        scale = spec["scale"]
        sql_scale = scale[3:] if scale.startswith("si:") else SQL_SCALE[scale]
        # unit: the QUDT local name (wire token, #1807); unit_display: the Haystack symbol, display only
        unit = r["unit"].split(":", 1)[1] if r.get("unit") else None
        if unit is not None and unit != units[r["unit"]]["wire"]:
            errs.append(f"{key}: QUDT local name {unit} != roles-file wire token {units[r['unit']]['wire']}")
        display = units[r["unit"]]["haystack"] if r.get("unit") else None
        entry = {"role": r["role"], "unit": unit, "unit_display": display, "value_type": r["value_type"],
                 "range": r.get("range"), "haystack": {"classes": r["haystack"].get("classes", []),
                                                       "markers": r["haystack"].get("markers", [])},
                 "sql_scale": sql_scale}
        if r.get("unit") == "unit:PERCENT" and scale == "fraction":
            entry["to_sql"] = {"multiplier": 0.01, "note": "roles file is percent 0-100; the rule SQL reads 0-1"}
        out[key] = entry
    if errs:
        raise SystemExit("roles/openfdd-roles.json does not cover the input contract:\n  " + "\n  ".join(errs))
    return out


DIALECTS = {
    "postgresql": "PostgreSQL 14+. Run helpers/postgres.sql once, SET TimeZone = 'UTC', then each rules/postgres/<ID>.sql "
                  "over the input tables of schema/inputs.sql.",
    "timescaledb": "Same SQL as PostgreSQL; no time_bucket, hypertables or continuous aggregates. Timescale only stores "
                   "fdd.input_sample and fdd.rule_result (schema/core.sql); the host builds the input tables from them.",
    "duckdb": "Run helpers/duckdb.sql (macros; plpgsql does not parse) and SET TimeZone = 'UTC', then rules/postgres/<ID>.sql "
              "unchanged. Needs only built-in extensions (icu, json); runs offline with autoinstall/autoload off. "
              "Schema: schema/core.duckdb.sql.",
    "sqlite": "Use rules/sqlite/<ID>.sql. The host registers the scalar UDFs listed in sqlite_udfs (reference: "
              "nf-app/hooks/lib/engines.js). Timestamps are numeric; follow the per-rule notes.",
}


def _sql_file(sql: str) -> str:
    return sql.replace("\r\n", "\n").rstrip("\n") + "\n"


def build_manifest(version: str) -> tuple[dict, dict[str, str]]:
    pg, lite = _json(PACK_PG), _json(PACK_SQLITE)
    contract, roles_doc = _json(CONTRACT), _json(ROLES)
    catalog = {r["id"]: r for r in _json(CATALOG)["rules"]}
    known, other, no_twin = docs_units.read_parity()
    if set(pg["rules"]) != set(catalog):
        raise SystemExit(f"pack and catalog disagree: {sorted(set(pg['rules']) ^ set(catalog))}")
    inputs = role_inputs(contract, roles_doc)

    files: dict[str, str] = {}
    rules, other_confirm = [], {}
    for rid in sorted(pg["rules"]):
        prule, cat = pg["rules"][rid], catalog[rid]
        if "{{" in prule["sql"]:
            raise SystemExit(f"{rid}: pack SQL still has a template placeholder")
        confirm_min = cat["confirm_seconds"] / 60
        confirm_min = int(confirm_min) if confirm_min == int(confirm_min) else round(confirm_min, 6)
        if confirm_min != CONFIRM_MIN_DEFAULT:
            other_confirm[rid] = confirm_min
        rule_inputs = []
        for need, keys in (("required", cat["required_roles"]), ("optional", cat["optional_roles"])):
            for key in keys:
                if need == "optional" and key in cat["required_roles"]:
                    continue                                  # listed twice in the catalog: required wins
                if key not in inputs:
                    raise SystemExit(f"{rid}: input {key!r} has no roles-file entry (roles/openfdd-roles.json)")
                i = inputs[key]
                rule_inputs.append({"role": i["role"], "legacy_key": key, "unit": i["unit"],
                                    "unit_display": i["unit_display"], "value_type": i["value_type"], "required": need == "required"})
        pg_path = f"rules/postgres/{rid}.sql"
        files[pg_path] = _sql_file(prule["sql"])
        sqlite_rule = lite["rules"].get(rid)
        if sqlite_rule:
            sqlite_path = f"rules/sqlite/{rid}.sql"
            files[sqlite_path] = _sql_file(sqlite_rule["sql"])
            sqlite_note = {"file": sqlite_path, "udfs": "fdd_" in sqlite_rule["sql"]}
            if rid in lite.get("notes", {}):
                sqlite_note["notes"] = lite["notes"][rid]
        else:
            sqlite_note = {"file": None, "notes": [lite.get("skipped", {}).get(rid, "not translated")]}
        uses_helpers = "fdd." in prule["sql"]
        parity = {"status": docs_units.parity_status(rid, known, no_twin)}
        if rid in known:
            parity["reason"] = known[rid]
        elif rid in other:
            parity.update(scope=other[rid][0], reason=other[rid][1])
        rules.append({
            "rule_id": rid,
            "title": cat["description"],
            "equipment_kinds": cat["equipment_kinds"],
            "inputs": rule_inputs,
            "confirm_min": confirm_min,
            "confirm_min_tunable": "confirm_seconds" in cat.get("parameters", {}),
            "output_columns": prule["output_columns"],
            "template": f"templates/sql/fdd/postgres/rules/{cat['sql_file']}",
            "dialects": {
                "postgresql": {"file": pg_path, "helpers": uses_helpers},
                "timescaledb": {"file": pg_path, "helpers": uses_helpers},
                "duckdb": {"file": pg_path, "helpers": uses_helpers},
                "sqlite": sqlite_note,
            },
            "parity": parity,
        })

    files["helpers/postgres.sql"] = _text(PG_HELPERS)
    files["helpers/duckdb.sql"] = _text(DUCK_HELPERS)
    core = _text(CORE_SQL)
    files["schema/core.sql"] = core
    files["schema/core.duckdb.sql"] = core_duckdb(core)
    files["schema/input_sample.sql"] = input_sample_sql(contract)
    files["schema/inputs.sql"] = _text(CONTRACT_SQL)
    for rel in TEMPLATE_FILES + sorted(p.relative_to(ROOT).as_posix() for p in ROOT.glob(TEMPLATE_GLOB)):
        files[f"templates/{rel}"] = _text(ROOT / rel)
    # The canonical role vocabulary itself, byte for byte (its sha256 is in "files" like every other entry).
    files["roles/openfdd-roles.json"] = ROLES.read_bytes().decode("utf-8")
    for r in rules:
        if r["template"] not in files:
            raise SystemExit(f"{r['rule_id']}: template {r['template']} is not in the bundle")

    manifest = {
        "bundle": "open-fdd-rules",
        "version": version,
        "manifest_version": MANIFEST_VERSION,
        "rule_count": len(rules),
        "sql": "rules/* is rendered at the shipped defaults (the SQL the NF app runs); no placeholders. templates/ holds "
               "the unrendered templates and render_rule.py. Values are SI; rules never convert units. Always "
               "SET TimeZone = 'UTC'.",
        "roles_vocabulary": {"file": "roles/openfdd-roles.json", "version": roles_doc["version"],
                             "doc": "Input role ids and units are the roles file's: unit is the QUDT local name (the wire token), "
                                    "unit_display the Haystack symbol (display only); legacy_key is the input_contract.json "
                                    "column the rule SQL reads; sql_scale is that column's scale (apply to_sql at ingest)."},
        "confirm_min": {"default": CONFIRM_MIN_DEFAULT,
                        "doc": "Minutes a condition must hold before it counts as a fault. Each rule's value is the "
                               "default baked into its rendered SQL (unchanged); rules_with_other_default lists those "
                               "not 15.",
                        "rules_with_other_default": other_confirm},
        "dialects": DIALECTS,
        "sqlite_udfs": lite["helper_functions"],
        "schema": {"core": "schema/core.sql", "core_duckdb": "schema/core.duckdb.sql",
                   "input_sample": "schema/input_sample.sql", "inputs": "schema/inputs.sql",
                   "helpers": {"postgresql": "helpers/postgres.sql", "timescaledb": "helpers/postgres.sql",
                               "duckdb": "helpers/duckdb.sql"}},
        "input_tables": pg["contract"],
        "inputs": inputs,
        "rules": rules,
        "files": {name: {"sha256": hashlib.sha256(files[name].encode("utf-8")).hexdigest(),
                         "bytes": len(files[name].encode("utf-8"))} for name in sorted(files)},
    }
    files["rules-manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    return manifest, files


def validate(manifest: dict) -> list[str]:
    """Coverage invariants the tests and --check assert."""
    errs = []
    pack_ids = set(_json(PACK_PG)["rules"])
    ids = [r["rule_id"] for r in manifest["rules"]]
    if set(ids) != pack_ids or len(ids) != len(pack_ids):
        errs.append(f"manifest rules != pack rules: {sorted(set(ids) ^ pack_ids)}")
    roles = {r["role"]: r for r in _json(ROLES)["roles"]}
    for r in manifest["rules"]:
        for i in r["inputs"]:
            ref = roles.get(i["role"])
            if ref is None or i["legacy_key"] not in (ref.get("legacy_keys") or []):
                errs.append(f"{r['rule_id']}: input {i['legacy_key']} -> {i['role']} is not in roles/openfdd-roles.json")
            elif (f"unit:{i['unit']}" if i["unit"] else None) != ref.get("unit"):
                errs.append(f"{r['rule_id']}: numeric input {i['role']} unit differs from the roles file")
    return errs


def zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zf.writestr(info, files[name].encode("utf-8"), compresslevel=9)
    return buf.getvalue()


def build(version: str) -> tuple[dict, dict[str, str], bytes]:
    manifest, files = build_manifest(version)
    errs = validate(manifest)
    if errs:
        raise SystemExit("\n".join(errs))
    return manifest, files, zip_bytes(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", help="bundle version or tag (default: VERSION file)")
    ap.add_argument("--out", type=Path, default=DIST, help="output directory (default: dist/)")
    ap.add_argument("--check", action="store_true", help="verify reproducibility and coverage; write nothing")
    args = ap.parse_args(argv)
    version = read_version(args.version)
    name = f"open-fdd-rules-{version}.zip"
    manifest, files, data = build(version)
    sha = hashlib.sha256(data).hexdigest()
    if args.check:
        _, _, data2 = build(version)
        if data2 != data:
            raise SystemExit("two fresh builds differ: the bundle is not reproducible")
        existing = args.out / name
        if existing.exists():
            with zipfile.ZipFile(existing) as zf:
                old = {n: zf.read(n).decode("utf-8") for n in zf.namelist()}
            if old != files:
                drift = sorted(n for n in set(old) | set(files) if old.get(n) != files.get(n))
                raise SystemExit(f"{existing} is stale; differs in: {drift[:10]}")
            if existing.read_bytes() != data:
                print(f"note: {existing} has the same contents but different zip bytes (another zlib build)")
        print(f"ok: {name} {len(data)} bytes, {manifest['rule_count']} rules, sha256 {sha}")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / name).write_bytes(data)
    (args.out / f"{name}.sha256").write_bytes(f"{sha}  {name}\n".encode("ascii"))
    print(f"wrote {args.out / name} ({len(data)} bytes, {manifest['rule_count']} rules)\nsha256 {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
