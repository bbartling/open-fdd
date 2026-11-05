#!/usr/bin/env python3
"""Build the NF-app SQL rule packs from the Open-FDD SQL pack (sql/fdd).

Writes, for the hook's two SQL engines:

  nf-app/rules/pack-postgres.json   rendered Postgres SQL (PGlite runs it as is)
  nf-app/rules/pack-sqlite.json     the same rules translated to SQLite (sql.js)

Both files have the shape

  { "poll_seconds": 300,
    "dialect": "postgres" | "sqlite",
    "helpers_sql": "<fdd.* helper functions; empty for sqlite, see helper_functions>",
    "helper_functions": [...],              # sqlite only: implemented in JS by engines.js
    "contract": { table: [ {name, type} ] },  # type = double | text | timestamp
    "rules": { rule_id: { "sql", "output_columns" } },
    "skipped": { rule_id: reason },         # sqlite only: rules we refuse to translate
    "notes": { rule_id: [text] } }          # sqlite only: documented semantic caveats

SQLite storage convention (engines.js): every timestamp column is REAL epoch seconds.

Translation = deterministic generic rewrites (below). A rule is never silently
altered: after rewriting, any Postgres-only construct left in the text, or any
statement SQLite cannot prepare, puts the rule in `skipped` with the reason.
Rewrites that are exact for the shipped rules but not in general carry a note.

Usage:
  python scripts/nf/build_sql_pack.py            # (re)write the JSON files
  python scripts/nf/build_sql_pack.py --check    # exit 1 when they are stale (CI)
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql" / "fdd"
OUT_DIR = ROOT / "nf-app" / "rules"
POLL_SECONDS = 300

sys.path.insert(0, str(SQL_DIR))
from render_rule import render  # noqa: E402  (shared renderer, not copied)

# fdd.* helpers implemented in JS (nf-app/hooks/lib/engines.js) for sqlite: name -> arity.
HELPER_FUNCTIONS = {
    "fdd_try_double": 1,
    "fdd_norm_unit": 1,
    "fdd_quantity_for_sql_role": 1,
    "fdd_unit_declares_quantity": 2,
    "fdd_is_expected_constant_sql_role": 1,
    "fdd_sweep_assessable_sql_role": 2,
    "fdd_mask_sweep_val": 3,
}

# Relations the rules read that input_contract.sql does not define (SV-* rules).
EXTRA_TABLES = {
    "authorized_series": [("site_id", "text"), ("equipment_id", "text"), ("role", "text"), ("unit", "text")],
    "equipment": [("building_id", "text"), ("equipment_id", "text")],
}

# history columns the SV-* rules read (h.ra_h ...) but input_contract.sql does not declare:
# a gap in the shipped SQL pack, added here so those rules can run (typed NULL unless supplied).
EXTRA_HISTORY_COLUMNS = ["ra_h", "zone_rh", "ma_h", "sa_h"]


class Untranslatable(Exception):
    pass


# --------------------------------------------------------------------------- contract

def _col_type(sql_type):
    t = sql_type.strip().lower()
    if t.startswith("timestamp"):
        return "timestamp"
    if t.startswith("double") or t in ("float", "real", "numeric"):
        return "double"
    if t.startswith("varchar") or t == "text":
        return "text"
    raise ValueError(f"unmapped contract type {sql_type!r}")


def parse_contract():
    text = (SQL_DIR / "input_contract.sql").read_text(encoding="utf-8")
    tables = {}
    for m in re.finditer(r"CREATE TEMP TABLE (\w+)\((.*?)\);", text, re.S | re.I):
        cols = []
        for part in m.group(2).split(","):
            name, _, typ = part.strip().partition(" ")
            cols.append({"name": name.strip('"'), "type": _col_type(typ)})
        tables[m.group(1)] = cols
    have = {c["name"] for c in tables["history"]}
    tables["history"] += [{"name": n, "type": "double"} for n in EXTRA_HISTORY_COLUMNS if n not in have]
    for name, cols in EXTRA_TABLES.items():
        tables[name] = [{"name": n, "type": t} for n, t in cols]
    return tables


# --------------------------------------------------------------------------- text helpers

def match_paren(s, i):
    """Index of the ')' matching the '(' at s[i]; single-quoted strings are skipped."""
    assert s[i] == "("
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "'":
            j = s.index("'", j + 1)
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise Untranslatable("unbalanced parentheses")


def split_top(s, sep):
    """Split on a single-character separator at paren depth 0."""
    out, depth, cur, j = [], 0, [], 0
    while j < len(s):
        c = s[j]
        if c == "'":
            k = s.index("'", j + 1)
            cur.append(s[j:k + 1])
            j = k + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        j += 1
    out.append("".join(cur))
    return out


def rewrite_calls(s, name, fn):
    """Replace every `name( ... )` call (case-insensitive, whole word) by fn(inner, rest) -> (text, consumed).

    fn gets the call's inner text and the text after the closing paren; it returns
    (replacement, number of characters of `rest` it consumed).
    """
    pat = re.compile(r"\b" + name + r"\s*\(", re.I)
    out, pos = [], 0
    while True:
        m = pat.search(s, pos)
        if not m:
            out.append(s[pos:])
            return "".join(out)
        open_i = m.end() - 1
        close_i = match_paren(s, open_i)
        inner = s[open_i + 1:close_i]
        repl, consumed = fn(inner, s[close_i + 1:])
        out.append(s[pos:m.start()])
        out.append(repl)
        pos = close_i + 1 + consumed


# --------------------------------------------------------------------------- sqlite rewrites

def strip_comments(sql):
    return "\n".join(re.sub(r"--[^\n']*$", "", ln).rstrip() for ln in sql.splitlines() if not ln.lstrip().startswith("--")
                     ).strip() + "\n"


def rw_extract_epoch(sql):
    """EXTRACT(EPOCH FROM (a - b)) -> (a - b): timestamps are REAL epoch seconds."""
    def fn(inner, rest):
        m = re.match(r"\s*EPOCH\s+FROM\s+(.*)$", inner, re.S | re.I)
        if not m:
            raise Untranslatable("EXTRACT of a field other than EPOCH")
        return "(" + m.group(1).strip() + ")", 0
    return rewrite_calls(sql, "EXTRACT", fn)


def rw_date_trunc(sql):
    def fn(inner, rest):
        unit, expr = split_top(inner, ",")
        unit = unit.strip().strip("'").lower()
        step = {"hour": 3600, "minute": 60, "day": 86400}.get(unit)
        if step is None:
            raise Untranslatable(f"DATE_TRUNC unit {unit!r}")
        return f"(floor(({expr.strip()}) / {step}.0) * {step}.0)", 0
    return rewrite_calls(sql, "DATE_TRUNC", fn)


def rw_to_char(sql):
    def fn(inner, rest):
        expr, fmt = split_top(inner, ",")
        m = re.match(r"^\s*(.*?)\s+AT\s+TIME\s+ZONE\s+'UTC'\s*$", expr, re.S | re.I)
        if fmt.strip() != "'YYYY-MM'" or not m:
            raise Untranslatable("to_char other than (ts AT TIME ZONE 'UTC', 'YYYY-MM')")
        return f"strftime('%Y-%m', {m.group(1)}, 'unixepoch')", 0
    return rewrite_calls(sql, "to_char", fn)


def rw_stddev_window(sql, notes):
    """STDDEV_SAMP(x) OVER (w) -> sqrt((sum(x*x) - sum(x)^2/n) / (n-1)) over the same window.

    sql.js has no windowed custom aggregates, so the sample standard deviation is
    built from windowed SUM/COUNT. Not numerically identical for near-constant data
    (cancellation ~1e-7 absolute at flow-scale values); the result is clamped at 0.
    """
    def fn(inner, rest):
        m = re.match(r"\s*OVER\s*\(", rest, re.I)
        if not m:
            raise Untranslatable("STDDEV_SAMP without a window")
        wopen = m.end() - 1
        wclose = match_paren(rest, wopen)
        w = rest[wopen:wclose + 1]
        x = inner.strip()
        n = f"COUNT({x}) OVER {w}"
        sx = f"SUM({x}) OVER {w}"
        sxx = f"SUM(({x}) * ({x})) OVER {w}"
        expr = f"(CASE WHEN {n} > 1 THEN sqrt(max(0.0, ({sxx} - {sx} * {sx} / {n}) / ({n} - 1))) END)"
        return expr, wclose + 1
    out = rewrite_calls(sql, "STDDEV_SAMP", fn)
    if out != sql:
        notes.append("STDDEV_SAMP window rebuilt from windowed SUM/COUNT (clamped at 0): equal within ~1e-6 for "
                     "real data, not bit-identical for near-constant windows.")
    return out


def rw_nan(sql, notes):
    """`x = CAST('NaN' AS DOUBLE PRECISION)` -> 0: SQLite cannot store NaN (it becomes NULL)."""
    pat = re.compile(r"[\w.]+\s*=\s*CAST\(\s*'NaN'\s+AS\s+DOUBLE\s+PRECISION\s*\)", re.I)
    out = pat.sub("0", sql)
    if out != sql:
        notes.append("NaN readings cannot exist in SQLite (stored as NULL), so the NaN branch of the range check "
                     "is dropped. JSON inputs from NF carry no NaN; the PGlite engine does flag a literal NaN.")
    return out


def rw_pg_casts(sql):
    sql = re.sub(r"\bNULL::double\s+precision", "NULL", sql, flags=re.I)
    sql = re.sub(r"\bcount\(\*\)::int\b", "count(*)", sql, flags=re.I)
    return sql


def rw_cast(sql):
    """CAST(x AS <pg type>) -> SQLite. INT rounds (Postgres) instead of truncating (SQLite)."""
    def fn(inner, rest):
        inner = rw_cast(inner)
        parts = re.split(r"\s+AS\s+", inner, flags=re.I)
        if len(parts) < 2:
            raise Untranslatable("CAST without AS")
        typ = parts[-1].strip().lower()
        expr = " AS ".join(parts[:-1])
        if typ == "double precision":
            return f"CAST({expr} AS REAL)", 0
        if typ == "int":
            return f"CAST(round({expr}) AS INTEGER)", 0
        if typ == "varchar":
            return f"CAST({expr} AS TEXT)", 0
        if typ == "timestamptz":
            return f"({expr})", 0
        raise Untranslatable(f"CAST to {typ}")
    return rewrite_calls(sql, "CAST", fn)


FORBIDDEN = [
    (r"::", "'::' cast left"), (r"\bEXTRACT\s*\(", "EXTRACT"), (r"\bINTERVAL\b", "INTERVAL"),
    (r"AT\s+TIME\s+ZONE", "AT TIME ZONE"), (r"\bfdd\.", "fdd.* helper"), (r"timestamptz", "timestamptz"),
    (r"\bDATE_TRUNC\b", "DATE_TRUNC"), (r"\bSTDDEV", "STDDEV"), (r"'NaN'", "NaN literal"),
    (r"\bTO_CHAR\b", "to_char"), (r"\bILIKE\b", "ILIKE"), (r"\bDISTINCT\s+ON\b", "DISTINCT ON"),
    (r"\bGENERATE_SERIES\b", "generate_series"), (r"\bLATERAL\b", "LATERAL"), (r"\bposition\s*\(", "position()"),
    (r"\bDOUBLE\s+PRECISION\b", "DOUBLE PRECISION"), (r"\bVARCHAR\b", "VARCHAR"),
]


def to_sqlite(pg_sql):
    """Returns (sqlite_sql, notes). Raises Untranslatable."""
    notes = []
    s = strip_comments(pg_sql)
    s = rw_nan(s, notes)
    s = re.sub(r"\bfdd\.(\w+)", r"fdd_\1", s)
    s = rw_extract_epoch(s)
    s = rw_date_trunc(s)
    s = rw_to_char(s)
    s = rw_stddev_window(s, notes)
    s = rw_pg_casts(s)
    s = rw_cast(s)
    for pat, what in FORBIDDEN:
        if re.search(pat, s, re.I):
            raise Untranslatable(f"Postgres-only construct left after rewriting: {what}")
    for m in re.finditer(r"\bfdd_(\w+)", s):
        if "fdd_" + m.group(1) not in HELPER_FUNCTIONS:
            raise Untranslatable(f"helper fdd.{m.group(1)} has no JS implementation")
    return s, notes


# --------------------------------------------------------------------------- build

def sqlite_prepare_check(sql, contract):
    """Prepare `sql` on an empty SQLite DB. Returns (error text | None, result column names | None).

    Skipped (None, None) when this Python's SQLite is too old for window functions + FILTER (3.30),
    so the output never depends on a half-capable build machine.
    """
    if sqlite3.sqlite_version_info < (3, 30, 0):
        return None, None
    db = sqlite3.connect(":memory:")
    for name, arity in HELPER_FUNCTIONS.items():
        db.create_function(name, arity, lambda *a: None)
    for table, cols in contract.items():
        decl = ", ".join(f'"{c["name"]}" {"TEXT" if c["type"] == "text" else "REAL"}' for c in cols)
        db.execute(f"CREATE TABLE {table} ({decl})")
    try:
        cur = db.execute(sql)
        return None, [d[0] for d in cur.description]
    except sqlite3.Error as exc:
        return str(exc), None
    finally:
        db.close()


def build():
    catalog = json.loads((SQL_DIR / "tuning_catalog.json").read_text(encoding="utf-8"))["rules"]
    contract = parse_contract()
    helpers = (SQL_DIR / "postgres" / "postgres_helpers.sql").read_text(encoding="utf-8")
    pg_rules, lite_rules, skipped, notes, column_fixes = {}, {}, {}, {}, {}
    for r in catalog:
        rid = r["rule_id"]
        pg = render(rid, POLL_SECONDS)
        cols = list(r["output_columns"])
        lite, lite_cols = None, None
        try:
            lite, n = to_sqlite(pg)
            err, lite_cols = sqlite_prepare_check(lite, contract)
            if err:
                raise Untranslatable("SQLite cannot prepare the translation: " + err)
            if n:
                notes[rid] = n
        except Untranslatable as exc:
            skipped[rid] = str(exc)
        # tuning_catalog.json's output_columns is sometimes incomplete; the SELECT list is the truth.
        if lite_cols is not None and sorted(lite_cols) != sorted(cols):
            column_fixes[rid] = {"catalog": cols, "actual": lite_cols}
            cols = lite_cols
        pg_rules[rid] = {"sql": pg, "output_columns": cols}
        if rid not in skipped:
            lite_rules[rid] = {"sql": lite, "output_columns": cols}
    head = {"poll_seconds": POLL_SECONDS}
    pg_pack = {**head, "dialect": "postgres", "helpers_sql": helpers, "contract": contract, "rules": pg_rules}
    lite_pack = {**head, "dialect": "sqlite", "helpers_sql": "", "helper_functions": sorted(HELPER_FUNCTIONS),
                 "contract": contract, "rules": lite_rules, "skipped": skipped, "notes": notes}
    if column_fixes:
        print(f"note: tuning_catalog.json output_columns incomplete for {len(column_fixes)} rules "
              f"(using the SELECT list): {', '.join(sorted(column_fixes))}", file=sys.stderr)
    return {"pack-postgres.json": pg_pack, "pack-sqlite.json": lite_pack}


def dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if the JSON files are stale")
    args = ap.parse_args()
    packs = build()
    stale = []
    for name, obj in packs.items():
        text = dump(obj)
        path = OUT_DIR / name
        if args.check:
            current = path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.exists() else None
            if current != text:
                stale.append(name)
        else:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(ROOT)} ({len(text) // 1024} KB, {len(obj['rules'])} rules)")
    lite = packs["pack-sqlite.json"]
    print(f"sqlite: {len(lite['rules'])} translated, {len(lite['skipped'])} skipped")
    for rid, why in lite["skipped"].items():
        print(f"  skipped {rid}: {why}")
    if args.check and stale:
        print("STALE: " + ", ".join(stale) + " (run: python scripts/nf/build_sql_pack.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
