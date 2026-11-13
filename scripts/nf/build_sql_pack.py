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
    "rules": { rule_id: { "sql", "output_columns", "timeline_sql", "timeline_reason" } },
    "skipped": { rule_id: reason },         # sqlite only: rules we refuse to translate
    "notes": { rule_id: [text] } }          # sqlite only: documented semantic caveats

SQLite storage convention (engines.js): every timestamp column is REAL epoch seconds.

timeline_sql (5.0.3): per rule, a per-timestamp variant of `sql` that returns assessed intervals.
  Most rules use (equipment_id, ts_epoch, confirmed, held_seconds); sensor sweeps add
  series_id and sensor_role between equipment_id and ts_epoch. ts_epoch is epoch seconds (double), confirmed is 1/0
  exactly as the rule's own confirmed flag, and held_seconds is the credited forward interval. SV gap
  segments start when max_silence_hours expires and hold exactly the remaining gap duration. It is `null`
  (with timeline_reason) for rules that have no per-row confirmed flag. Summing confirmed * held_seconds /
  3600 by the rule's output grain equals fault_hours.

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
import render_rule  # noqa: E402
from render_rule import render  # noqa: E402  (shared renderer, not copied)
from input_contract import load_contract  # noqa: E402

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

class Untranslatable(Exception):
    pass


# --------------------------------------------------------------------------- contract

def parse_contract():
    """Return the scratch contract for the NF pack from its canonical source."""
    return load_contract()


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


# --------------------------------------------------------------------------- timeline (per-timestamp confirmed flag; SV adds sensor_role)

TIMELINE_COLUMNS = ["equipment_id", "ts_epoch", "confirmed", "held_seconds"]
ROLE_TIMELINE_COLUMNS = ["equipment_id", "series_id", "sensor_role", "ts_epoch", "confirmed", "held_seconds"]


class NoTimeline(Exception):
    pass


def parse_ctes(sql):
    """`WITH a AS (...), b AS (...) <main>` -> ([(name, open_i, close_i)], index where <main> starts). Comments must be stripped."""
    m = re.match(r"\s*WITH\s+", sql, re.I)
    if not m:
        raise NoTimeline("no per-row confirmed flag (a plain aggregate, no CTE chain)")
    pos, ctes = m.end(), []
    head = re.compile(r"\s*(\w+)\s+AS\s*\(", re.I)
    while True:
        h = head.match(sql, pos)
        if not h:
            raise NoTimeline("cannot parse the CTE list")
        open_i = h.end() - 1
        close_i = match_paren(sql, open_i)
        ctes.append((h.group(1).lower(), open_i, close_i))
        pos = close_i + 1
        c = re.compile(r"\s*,").match(sql, pos)
        if not c:
            return ctes, pos
        pos = c.end()


_TS = "CAST(EXTRACT(EPOCH FROM {t}) AS DOUBLE PRECISION) AS ts_epoch"


def select_list(body):
    """The top-level select list of `SELECT ... FROM ...` (nested parentheses blanked, so window clauses do not count)."""
    flat = body
    while True:
        nxt = re.sub(r"\([^()]*\)", "()", flat)
        if nxt == flat:
            break
        flat = nxt
    m = re.search(r"\bFROM\b", flat)
    return flat[:m.start()] if m else flat


def build_timeline_pg(pg_sql):
    """Postgres timeline SQL for one rendered rule, or raises NoTimeline(reason).

    Per-sensor SV rules expose series_id and sensor_role, and preserve silence-tail intervals exactly.
    """
    s = strip_comments(pg_sql)
    try:
        ctes, main = parse_ctes(s)
    except (ValueError, Untranslatable) as exc:
        raise NoTimeline(f"cannot parse the rule: {exc}")
    names = [c[0] for c in ctes]
    tail = s[main:]
    order = "ORDER BY equipment_id, timestamp_utc"
    if "final" in names:
        i = names.index("final")
        _, o, c = ctes[i]
        body = s[o + 1:c]
        if not (re.search(r"\bheld_seconds\b", body) and re.search(r"\bconfirmed\b", body)):
            raise NoTimeline("final CTE has no held_seconds / confirmed")
        if re.search(r"\bsensor_role\b", select_list(body)) and re.search(r"\bsegment_epoch\b", select_list(body)):
            head = s[:o + 1] + body + ")"
            after = names[i + 1:]
            if after and after != ["scored"]:
                raise NoTimeline("unexpected CTEs after role final: " + ", ".join(after))
            final_fields = select_list(body)
            has_series = bool(re.search(r"\bseries_id\b", final_fields))
            series = "series_id, " if has_series else ""
            series_order = "series_id, " if has_series else ""
            sel = (f"SELECT equipment_id, {series}sensor_role, CAST(segment_epoch AS DOUBLE PRECISION) AS ts_epoch, "
                   "confirmed, held_seconds FROM final WHERE held_seconds > 0 "
                   f"ORDER BY equipment_id, {series_order}sensor_role, segment_epoch")
            return head + "\n" + sel + "\n"
        if not re.search(r"\btimestamp_utc\b", select_list(body)):
            body, n = re.subn(r"\bequipment_id,", "equipment_id,\n    timestamp_utc,", body, count=1)
            if n != 1:
                raise NoTimeline("cannot add timestamp_utc to the final CTE")
        head = s[:o + 1] + body + ")"
        after = names[i + 1:]
        if not after:
            sel = f"SELECT equipment_id, {_TS.format(t='timestamp_utc')}, confirmed, held_seconds FROM final {order}"
            return head + "\n" + sel + "\n"
        if after == ["cov"]:
            gate = re.search(r"WHEN\s+(\S+)\s*<\s*0\.5\s+THEN\s+SUM", tail)
            thr = re.search(r"MAX\(c\.cov_pct\)\s*<\s*(\S+)\s+THEN\s+0\.0", tail)
            if not (gate and thr and "FROM final f" in tail and "LEFT JOIN cov c" in tail):
                raise NoTimeline("coverage-gated rule with an unrecognised final SELECT")
            tween = s[c + 1:main].rstrip()
            sel = (f"SELECT f.equipment_id, {_TS.format(t='f.timestamp_utc')},\n"
                   f"  CASE WHEN {gate.group(1)} < 0.5 THEN f.confirmed WHEN c.cov_pct < {thr.group(1)} THEN 0 ELSE f.confirmed END AS confirmed,\n"
                   f"  f.held_seconds\n"
                   f"FROM final f LEFT JOIN cov c ON f.equipment_id = c.equipment_id ORDER BY f.equipment_id, f.timestamp_utc")
            return head + tween + "\n" + sel + "\n"
        raise NoTimeline("unexpected CTEs after final: " + ", ".join(after))
    if names and names[-1] == "ranked" and re.search(r"\bFROM\s+ranked\b", tail):
        m = re.search(r"raw_fault\s*=\s*1\s+AND\s+streak_elapsed\s*>=\s*(\S+)\s+THEN\s+held_seconds", tail)
        if m:
            head = s[:main].rstrip()
            sel = (f"SELECT equipment_id, {_TS.format(t='timestamp_utc')},\n"
                   f"  CASE WHEN raw_fault = 1 AND streak_elapsed >= {m.group(1)} THEN 1 ELSE 0 END AS confirmed, held_seconds\n"
                   f"FROM ranked {order}")
            return head + "\n" + sel + "\n"
    raise NoTimeline("no per-row confirmed flag (the rule aggregates a ratio, count or window statistic)")


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


def role_limit_templates(pg_rules):
    """Templates of the five sweep rules for persisted role-limit overrides (#1589; Full edition, Timescale engine):
    the rule and timeline SQL with the per-role limit fragment left as a sentinel, the numbers the fragment references,
    the canonical -> SQL role names, and the shipped limits + allowlists the hook merges overrides onto. Filled with the
    shipped limits each template must give the pack SQL byte for byte (checked here; the JS twin in role-limits.test.mjs)."""
    shipped = json.loads((ROOT / "open_fdd" / "data" / "sensor_sweep_limits.json").read_text(encoding="utf-8"))
    allow = json.loads((ROOT / "open_fdd" / "data" / "sensor_sweep_roles.json").read_text(encoding="utf-8"))
    limits = render_rule.sweep_catalog.load_role_limits(shipped)
    rules = {}
    for rid in render_rule.FRAGMENT_KEYS:
        t = render_rule.render_template(rid, POLL_SECONDS)
        tl = None
        if pg_rules[rid]["timeline_sql"]:
            tl = build_timeline_pg(t["sql"])
        for name, tmpl, want in (("sql", t["sql"], pg_rules[rid]["sql"]), ("timeline_sql", tl, pg_rules[rid]["timeline_sql"])):
            got = render_rule.fill_template(tmpl, rid, t["values"], t["sql_roles"], limits) if tmpl else None
            if got != want:
                raise SystemExit(f"role-limit template of {rid} {name} does not reproduce the pack SQL")
        rules[rid] = {"sql": t["sql"], "timeline_sql": tl, "fragment": t["fragment"], "sql_roles": t["sql_roles"], "values": t["values"]}
    return {"version": 1, "rule_config_id": "SV-LIMITS", "shipped": shipped, "allowlists": allow, "rules": rules}




def rule_tuning_templates(catalog, pg_rules):
    """Rule-level parameter templates for all rules (5.0.17; Full edition, Timescale engine).
    Keeps numeric {{PLACEHOLDER}} tokens unexpanded (and role-limit fragments as __OFDD_SV_*__ sentinels
    on sweep rules) so shared/rule-tuning.js can re-render any rule from persisted fdd.rule_config overrides.
    Verifies byte-identical reproduction of pack SQL and timeline_sql under default parameters."""
    runtime_defaults = json.loads((SQL_DIR / "runtime_defaults.json").read_text(encoding="utf-8"))
    sweep_roles = json.loads(render_rule.SWEEP_ROLE_SOURCE.read_text(encoding="utf-8"))
    role_map = json.loads(render_rule.ROLE_MAP_SOURCE.read_text(encoding="utf-8"))
    inverse = {name: role for role, name in role_map.items()}
    shipped = json.loads((ROOT / "open_fdd" / "data" / "sensor_sweep_limits.json").read_text(encoding="utf-8"))
    limits = render_rule.sweep_catalog.load_role_limits(shipped)
    rules = {}
    for r in catalog:
        rid = r["rule_id"]
        sql = (SQL_DIR / "postgres" / "rules" / r["sql_file"]).read_text(encoding="utf-8")
        if "{{ASSESSABLE_ROLES}}" in sql:
            names = sweep_roles[rid]
            allowed = ", ".join("'" + inverse[name].replace("'", "''") + "'" for name in names)
            sql = sql.replace("{{ASSESSABLE_ROLES}}", allowed)
            fkey = render_rule.FRAGMENT_KEYS[rid]
            sql = sql.replace("{{" + fkey + "}}", render_rule.sentinel(fkey))
        tl = build_timeline_pg(sql) if pg_rules[rid]["timeline_sql"] else None
        controls = {}
        for k, d in r["parameters"].items():
            if not d.get("effect_in_sql", True):
                continue
            item = {
                "key": k,
                "kind": d["kind"],
                "label": d["label"],
                "min": d["min"],
                "max": d["max"],
                "step": d["step"],
                "unit": d["unit"],
                "default": d["default"],
                "sql_placeholder": d["sql_placeholder"],
            }
            if d.get("description"):
                item["description"] = d["description"]
            controls[k] = item
        # Roundtrip check against pg_rules[rid] with defaults + shipped limits
        vals = dict(runtime_defaults)
        for k, d in r["parameters"].items():
            if k != "confirm_min":
                vals[d["sql_placeholder"]] = d["default"]
        vals["MODE_DELAY_MIN"] = max(vals.get("MODE_DELAY_MIN", 0), vals.get("STARTUP_DELAY_MIN", 0))
        vals["POLL_SECONDS"] = POLL_SECONDS
        confirm_min = r["parameters"]["confirm_min"]["default"]
        vals["CONFIRM_SECONDS"] = confirm_min * 60
        vals["CONFIRM_ROWS"] = max(1, -(-int(vals["CONFIRM_SECONDS"]) // POLL_SECONDS))
        import math
        vals["CONFIRM_ROWS"] = max(1, math.ceil(vals["CONFIRM_SECONDS"] / POLL_SECONDS))
        for k, v in list(vals.items()):
            if k.endswith("_HOURS") and v > 0:
                p = k[:-6]
                vals[p + "_SECONDS"] = round(v * 3600)
                rows = max(6 if p == "FIXED_FLOW" else 1, math.ceil(v * 3600 / POLL_SECONDS))
                vals[p + "_ROWS"] = rows
                vals[p + "_ROWS_PRECEDING"] = rows - 1
                vals[p + "_MIN_PERIODS"] = max(3, rows // 2)
        for p in ("MODE_DELAY", "STARTUP_DELAY"):
            rows = max(1, math.ceil(vals.get(p + "_MIN", 0) * 60 / POLL_SECONDS))
            vals[p + "_ROWS"] = rows
            vals[p + "_ROWS_PRECEDING"] = rows - 1
        if "WEB_CADENCE_SECONDS" in vals and "WEB_ASOF_MARGIN_SECONDS" in vals:
            vals["WEB_ASOF_BOUND_SECONDS"] = round(vals["WEB_CADENCE_SECONDS"] + vals["WEB_ASOF_MARGIN_SECONDS"])
        def _fill_tmpl(tmpl_text):
            if tmpl_text is None:
                return None
            out = tmpl_text
            if rid in render_rule.FRAGMENT_KEYS:
                fkey = render_rule.FRAGMENT_KEYS[rid]
                frag = render_rule._sweep_fragments({"rule_id": rid}, limits, inverse, set(sweep_roles[rid]))[fkey]
                out = out.replace(render_rule.sentinel(fkey), frag)
            return render_rule._PLACEHOLDER.sub(lambda m: render_rule._format_value(vals[m[1]]), out)
        if _fill_tmpl(sql) != pg_rules[rid]["sql"]:
            raise SystemExit(f"rule_tuning_templates sql mismatch for {rid}")
        if _fill_tmpl(tl) != pg_rules[rid]["timeline_sql"]:
            raise SystemExit(f"rule_tuning_templates timeline_sql mismatch for {rid}")
        rules[rid] = {"sql": sql, "timeline_sql": tl, "controls": controls}
    return {"version": 1, "runtime_defaults": runtime_defaults, "rules": rules}

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
        tl_pg, tl_lite, tl_reason = None, None, ""
        try:
            tl_pg = build_timeline_pg(pg)
            if rid not in skipped:
                try:
                    tl_lite, _ = to_sqlite(tl_pg)
                    err, tl_cols = sqlite_prepare_check(tl_lite, contract)
                    if err:
                        raise Untranslatable("SQLite cannot prepare the timeline: " + err)
                    want_tl_cols = ROLE_TIMELINE_COLUMNS if "series_id" in cols else TIMELINE_COLUMNS
                    if tl_cols is not None and tl_cols != want_tl_cols:
                        raise Untranslatable(f"timeline columns {tl_cols}")
                except Untranslatable as exc:
                    tl_lite, tl_reason = None, f"sqlite: {exc}"
        except NoTimeline as exc:
            tl_reason = str(exc)
        pg_rules[rid] = {"sql": pg, "output_columns": cols, "timeline_sql": tl_pg,
                         "timeline_reason": "" if tl_pg else tl_reason}
        if rid not in skipped:
            lite_rules[rid] = {"sql": lite, "output_columns": cols, "timeline_sql": tl_lite,
                               "timeline_reason": "" if tl_lite else tl_reason}
    head = {"poll_seconds": POLL_SECONDS}
    pg_pack = {**head, "dialect": "postgres", "helpers_sql": helpers, "contract": contract, "rules": pg_rules,
               "role_limit_templates": role_limit_templates(pg_rules),
               "rule_tuning_templates": rule_tuning_templates(catalog, pg_rules)}
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
    for nm, pk in packs.items():
        n = sum(1 for r in pk["rules"].values() if r["timeline_sql"])
        print(f"{nm}: timeline_sql on {n} of {len(pk['rules'])} rules")
    for rid, why in lite["skipped"].items():
        print(f"  skipped {rid}: {why}")
    if args.check and stale:
        print("STALE: " + ", ".join(stale) + " (run: python scripts/nf/build_sql_pack.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
