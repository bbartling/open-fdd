#!/usr/bin/env python3
"""Generate the Rule Cookbook pages (docs/rules/*.md) from the code, so the docs cannot drift.

    python3 scripts/nf/gen_cookbook.py            # write the three pages
    python3 scripts/nf/gen_cookbook.py --check    # exit 1 if any committed page is stale

Pages: sql-cookbook.md, pandas-cookbook.md, parity.md. (docs/rules/index.md, the rule catalog, is gen_rule_docs.py.)
Per rule, the Inputs, Parameters and Outputs tables carry SI units, accepted declared units, expected range and parity status.
Sources (all read, nothing hand-copied): see docs_units.py, plus
  nf-app/static/fdd-catalog.json        rule ids, kinds, roles, defaults (built from sql/fdd/registry.yaml)
  open_fdd/rules/cookbook_catalog.py    the pandas twin of each rule
No SQL or pandas source is pasted: each entry links to its file. Needs pandas + numpy + pyyaml (imports open_fdd.rules).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_units import (INPUT_HEADER, PARAM_HEADER, Contract, cell, fmt, imperial_note, output_rows, param_rows,  # noqa: E402
                        parity_status, read_parity, units_convention)

CATALOG = ROOT / "nf-app" / "static" / "fdd-catalog.json"
TUNING = ROOT / "sql" / "fdd" / "tuning_catalog.json"
PACK = ROOT / "nf-app" / "rules" / "pack-postgres.json"
OUT_DIR = ROOT / "docs" / "rules"

GH = "https://github.com/bbartling/open-fdd/blob/master"
PANDAS_ID = {"FC13-SAT-HIGH": "FC13"}  # SQL rule id -> pandas rule id where they differ (same as tests/parity/harness.py)

GROUPS = [
    ("ahu", "Air handling units", "AHU / RTU / MAU / DOAS: duct static, supply air, economizer, mixing and mode faults."),
    ("vav", "VAV terminals", "VAV boxes and other zone terminals: comfort, airflow, reheat and damper faults."),
    ("fcu", "Fan coil and zone equipment", "Fan coils, unit ventilators and other `zone_other` equipment."),
    ("plant", "Chillers and plants", "Chillers, chilled water and condenser water plants, cooling towers."),
    ("boiler", "Boilers", "Boiler plants."),
    ("heatpump", "Heat pumps", "Heat pumps."),
    ("meter", "Meters and utilities", "Energy and demand meters, utility bill analytics."),
    ("sensors", "Sensor validation and control loops", "Range, flatline, spike, stale and rate checks on every modeled sensor; PID hunting."),
    ("weather", "Weather", "Web weather versus the site's own outside air sensor."),
    ("general", "General", "Rules that apply to any equipment: runtime, comfort and elapsed-time analytics."),
]

UNIT_LABEL = {
    "frac": "fraction (0-1)",
    "degC": "°C", "degC_delta": "Δ°C", "degC_delta_per_h": "Δ°C/h", "pct": "%", "frac": "fraction (0-1)",
    "min": "min", "sec": "s", "h": "h", "L_per_s": "L/s", "Pa": "Pa", "kWh": "kWh", "ppm": "ppm",
    "bool": "0/1", "count": "count", "x": "× (scale)", "unit": "signal units", "%": "%",
}
SI_UNITS = {"°C", "Δ°C", "Δ°C/h", "%", "% out", "%/h", "fraction (0-1)", "min", "s", "sec", "h", "L/s", "Pa", "kWh", "kW", "ppm",
            "0/1", "count", "× (scale)", "x", "signal units", "eng", "cyc/h", "Δ°C/Δ°C", "A", ""}

# --------------------------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------------------------


def anchor(rule_id: str) -> str:
    return rule_id.lower()


def group_of(rule: dict) -> str:
    rid = rule["id"]
    kinds = rule.get("equipment_kinds") or []
    if rid.startswith("SV-") or rid == "PID-HUNT-1":
        return "sensors"
    if rid in ("OAT-METEO", "WX-1"):
        return "weather"
    if rid.startswith("FCU-"):
        return "fcu"
    if rid.startswith("UTIL-"):
        return "meter"
    first = kinds[0] if kinds else ""
    return {"ahu": "ahu", "vav": "vav", "chiller": "plant", "boiler": "boiler", "heatpump": "heatpump",
            "meter": "meter", "weather": "weather"}.get(first, "general")


# --------------------------------------------------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------------------------------------------------


def load() -> dict:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    tuning = {r["rule_id"]: r for r in json.loads(TUNING.read_text(encoding="utf-8"))["rules"]}
    rules = sorted(cat["rules"], key=lambda r: r["id"])
    from open_fdd.rules.cookbook_catalog import RULES_BY_ID  # noqa: E402 - needs sys.path set above
    twins = {r["id"]: RULES_BY_ID[PANDAS_ID.get(r["id"], r["id"])] for r in rules if PANDAS_ID.get(r["id"], r["id"]) in RULES_BY_ID}
    pack = json.loads(PACK.read_text(encoding="utf-8"))["rules"]  # the columns each rendered SQL really returns
    known, other, no_twin = read_parity()
    return {"cat": cat, "tuning": tuning, "pack": pack, "rules": rules, "twins": twins, "known": known, "other": other,
            "no_twin": no_twin, "contract": Contract()}


def grouped(d: dict) -> list[tuple[str, str, str, list[dict]]]:
    out = []
    for key, title, blurb in GROUPS:
        members = [r for r in d["rules"] if group_of(r) == key]
        if members:
            out.append((key, title, blurb, members))
    return out


def confirm_text(r: dict) -> str:
    c = r.get("confirm_seconds") or 0
    if not c:
        return "immediate"
    return f"{c // 60} min" if c % 60 == 0 else f"{c} s"


# --------------------------------------------------------------------------------------------------------------------
# shared entry pieces
# --------------------------------------------------------------------------------------------------------------------


def toc(d: dict) -> list[str]:
    out = ["## Rules by equipment\n"]
    for _key, title, _blurb, members in grouped(d):
        links = " · ".join(f"[{r['id']}](#{anchor(r['id'])})" for r in members)
        out.append(f"**{title}** ({len(members)}): {links}\n")
    return out


def parity_line(d: dict, rid: str) -> str:
    status = parity_status(rid, d["known"], d["no_twin"])
    text = f"**Parity** [{status}](parity.html#{anchor(rid)})"
    if status == "known divergence":
        text += f": {d['known'][rid]}"
    elif rid in d["other"]:
        scope, why = d["other"][rid]
        text += f"; differs only on {scope.replace('_', '-')} data: {why}"
    return text


def inputs_table(d: dict, required: list[str], optional: list[str]) -> str:
    rows = list(INPUT_HEADER)
    seen = set()
    for names, need in ((required, "required"), (optional, "optional")):
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            rows.append(d["contract"].input_row(n, need))
    return "\n".join(rows)


def scales_of(d: dict, names: list[str]) -> set[str]:
    roles = (d["contract"].sql_role(n) for n in names)
    return {d["contract"].scale(r) for r in roles if r}


def params_block(rows: list[str], info: bool) -> str:
    out = list(PARAM_HEADER) + rows
    if info:
        out += ["", "† informational: this control has no effect in the SQL template."]
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------------
# SQL cookbook
# --------------------------------------------------------------------------------------------------------------------


def render_sql(d: dict) -> str:
    n = len(d["rules"])
    out = [f"""---
title: SQL cookbook
parent: Rules
nav_order: 1
---

# SQL cookbook

<!-- GENERATED by scripts/nf/gen_cookbook.py from the registry, input contract, tuning catalog and unit tables. Do not edit by hand. -->

**{n} PostgreSQL rules**: the production engine. Each entry gives the inputs, parameters and outputs with their units, the
parity status and a link to the SQL file. Python twins are in the [pandas cookbook](pandas-cookbook.html). To run a rule
on your own database see [Using SQL rules outside Open-FDD](borrowing-sql.html).

How a rule runs: the FDD hook passes one scoped, SI, wide `history` table (one column per role, one row per equipment and
timestamp) and reads one row per equipment back. A fault must hold for its confirm time. A gap longer than one hour is
unknown, not fault and not ok. `fault_hours` counts confirmed fault time. More in [sql/fdd/README.md]({GH}/sql/fdd/README.md).

""" + units_convention()]
    out += toc(d)
    out.append("\n---\n")
    for key, title, blurb, members in grouped(d):
        out.append(f"\n## {title} {{#group-{key}}}\n\n{blurb}\n")
        for r in members:
            rid = r["id"]
            tun = d["tuning"][rid]
            cols = d["pack"][rid].get("output_columns") or tun.get("output_columns") or []
            kinds = ", ".join(f"`{k}`" for k in r.get("equipment_kinds") or []) or "any equipment"
            twin = d["twins"].get(rid)
            twin_txt = f"[pandas twin](pandas-cookbook.html#{anchor(rid)})" if twin else "SQL only"
            req = r.get("required_roles") or []
            opt = [x for x in (r.get("optional_roles") or []) if x not in req]
            prow, has_delta, info = param_rows(tun.get("parameters") or {})
            out.append(f"\n### {rid} {{#{anchor(rid)}}}\n")
            out.append(f"{r.get('description', '')}\n")
            out.append(f"**Priority** {r.get('priority', '')} · **Equipment** {kinds} · **Confirm** {confirm_text(r)} · "
                       f"[SQL file]({GH}/sql/fdd/postgres/rules/{tun['sql_file']}) · {twin_txt}\n")
            out.append("**Inputs**\n\n" + inputs_table(d, req, opt) + "\n")
            out.append("**Parameters**\n\n" + (params_block(prow, info) if prow else "_None._") + "\n")
            out.append("**Outputs**\n\n" + "\n".join(output_rows(cols)) + "\n")
            out.append(parity_line(d, rid) + "\n")
            note = imperial_note(has_delta, scales_of(d, req + opt))
            if note:
                out.append(note + "\n")
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------------------------------------
# pandas cookbook
# --------------------------------------------------------------------------------------------------------------------


def pandas_param_rows(rule) -> tuple[list[str], bool]:
    rows, has_delta = [], False
    for p in sorted(rule.params, key=lambda x: x.key):
        unit = UNIT_LABEL.get(p.unit, p.unit)
        has_delta = has_delta or unit.startswith("Δ")
        rows.append(f"| `{p.key}` | {cell(p.label)} | {fmt(p.default)} | {fmt(p.min)} | {fmt(p.max)} | {cell(unit)} |")
    return rows, has_delta


# Hand-written examples that really trip the fault (verified by gen_cookbook.py on every run).
HAND_EXAMPLES = {
    "FC1": ('{"duct-static-pressure": 150.0, "duct-static-pressure-sp": 250.0, "fan-cmd": 1.0}', "equip-1", "AHU",
            "Duct static (Pa) sits 100 Pa under its setpoint while the fan runs: low static at full fan."),
}


def example_code(rule) -> tuple[str, str]:
    """(source, note) of a minimal runnable example for a pandas rule in HAND_EXAMPLES."""
    frame, eid, etype, note = HAND_EXAMPLES[rule.id]
    src = [
        "import pandas as pd",
        "from open_fdd.rules import run_rule",
        "",
        "# one day on a 5-minute grid, UTC timestamps, every value SI (°C, Pa, L/s, kW; commands 0-1)",
        'idx = pd.date_range("2026-01-05", periods=288, freq="5min", tz="UTC", name="timestamp_utc")',
        f"df = pd.DataFrame({frame}, index=idx)",
        f'df.attrs.update(equipment_id="{eid}", equipment_type="{etype}")',
        "",
        f'result = run_rule("{rule.id}", df, params={{"confirm_min": {fmt(round(float(rule.confirm_seconds) / 60.0, 6))}}})',
        "print(result.status, result.fault_hours)",
    ]
    return "\n".join(src), note


def render_pandas(d: dict) -> str:
    twins = d["twins"]
    sql_only = [r for r in d["rules"] if r["id"] not in twins]
    n = len(twins)
    quick, quick_note = example_code(twins["FC1"])
    out = [f"""---
title: Pandas cookbook
parent: Rules
nav_order: 2
---

# Pandas cookbook

<!-- GENERATED by scripts/nf/gen_cookbook.py from open_fdd/rules/cookbook_catalog.py and the unit tables. Do not edit by hand. -->

**{n} rules as pandas functions**: the reference twin of the [SQL cookbook](sql-cookbook.html), for notebooks, CSV studies and
the parity tests ([parity](parity.html)). The function behind each rule is in
[`open_fdd/rules/cookbook_catalog.py`]({GH}/open_fdd/rules/cookbook_catalog.py). The {len(sql_only)} rules without a twin are marked **SQL only**.

**Conventions**

- Input is a `DataFrame` with a UTC `DatetimeIndex` and one Haystack-role column per signal, all in SI (table below).
  The rules never convert units or guess a scale.
- `run_rule(rule_id, df, params=..., poll_seconds=300)` returns `status` (`PASS`, `FAULT`, `SKIPPED_MISSING_ROLES`, ...),
  `fault_hours` (h), and the `raw_fault` and `confirmed_fault` boolean masks. Set `df.attrs["equipment_id"]` and `df.attrs["equipment_type"]`.
- The runner applies the operational gate and the confirm delay (`confirm_min`, minutes). Parameter keys match the SQL catalog.

```python
{quick}
```

{quick_note}

""" + units_convention()]
    out += toc(d)
    out.append("\n---\n")
    for key, title, blurb, members in grouped(d):
        out.append(f"\n## {title} {{#group-{key}}}\n\n{blurb}\n")
        for r in members:
            rid = r["id"]
            rule = twins.get(rid)
            out.append(f"\n### {rid} {{#{anchor(rid)}}}\n")
            if rule is None:
                out.append(f"{r.get('description', '')}\n")
                out.append(f"**SQL only.** No pandas twin: an aggregate or utility analytic. See the [SQL entry](sql-cookbook.html#{anchor(rid)}) "
                           f"and [parity](parity.html#{anchor(rid)}).\n")
                continue
            kinds = ", ".join(f"`{k}`" for k in rule.equipment_kinds) or "any equipment"
            out.append(f"{rule.summary or rule.title}\n")
            out.append(f"**{cell(rule.title)}** · **Family** {rule.family} · **Equipment** {kinds} · **Confirm** {fmt(round(rule.confirm_seconds / 60.0, 6))} min · "
                       f"function `{rule.compute.__name__}` · [SQL entry](sql-cookbook.html#{anchor(rid)})\n")
            if rule.equation and rule.equation.strip() != (rule.summary or "").strip():
                out.append(f"**Equation**: {rule.equation.strip()}\n")
            req = list(rule.required_roles)
            opt = [x for x in rule.optional_roles if x not in req]
            prow, has_delta = pandas_param_rows(rule)
            cols = d["pack"][rid].get("output_columns") or d["tuning"][rid].get("output_columns") or []
            out.append("**Inputs**\n\n" + inputs_table(d, req, opt) + "\n")
            out.append("**Parameters**\n\n" + ("\n".join(PARAM_HEADER + prow) if prow else "_None._") + "\n")
            out.append("**Outputs** (the same as the SQL twin)\n\n" + "\n".join(output_rows(cols)) + "\n")
            out.append(parity_line(d, rid) + "\n")
            note = imperial_note(has_delta, scales_of(d, req + opt))
            if note:
                out.append(note + "\n")
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------------------------------------
# parity
# --------------------------------------------------------------------------------------------------------------------


def render_parity(d: dict) -> str:
    twins, known, no_twin = d["twins"], d["known"], d["no_twin"]
    total = len(d["rules"])
    matched = [r for r in d["rules"] if r["id"] in twins and r["id"] not in known]
    out = [f"""---
title: Parity
parent: Rules
nav_order: 4
---

# Parity

<!-- GENERATED by scripts/nf/gen_cookbook.py from tests/parity/test_parity.py and open_fdd/data/parity_known_differences.json. Do not edit by hand. -->

SQL is the production result; pandas is the reference. The strict suite ([tests/parity]({GH}/tests/parity/)) runs a seeded two-equipment,
three-day SI dataset through PostgreSQL SQL (PGlite), SQLite and pandas and pins the match and known-divergence sets. A pass is
evidence for that dataset, not proof for every input. Run it with `python -m pytest tests/parity -q`.

| | Rules |
|---|---:|
| SQL rules | **{total}** |
| With a pandas twin | **{len(twins)}** |
| Match on the synthetic suite | **{len(matched)}** |
| Known divergence | **{len(known)}** |
| SQL only (no twin) | **{len(no_twin)}** |

**Units.** Parity is checked in SI. Imperial input is converted to SI at ingest, so SQL on imperial input equals SQL on SI input by
construction; `to_imperial` / `from_imperial` in the [harness](parity-harness.html) round-trip the dataset to 1e-9. There is no separate
per-rule imperial parity run.

## Per rule

| Rule | pandas SI vs SQL SI | Note |
|---|---|---|
"""]
    for r in d["rules"]:
        rid = r["id"]
        status = parity_status(rid, known, no_twin)
        if status == "SQL only":
            note = "aggregate or utility analytic, no pandas function"
        elif status == "known divergence":
            note = known[rid]
        elif rid in d["other"]:
            scope, why = d["other"][rid]
            note = f"match; differs only on {scope.replace('_', '-')} data: {why}"
        else:
            note = ""
        out.append(f'| <a id="{anchor(rid)}"></a>[{rid}](sql-cookbook.html#{anchor(rid)}) | {status} | {cell(note)} |\n')
    out.append(f"""
Known differences: [KNOWN_DIFFERENCES.md]({GH}/sql/fdd/KNOWN_DIFFERENCES.md). Wider SI stress run: `python tests/parity/stress.py --equips 8 --days 7`.

## Change a rule

1. SQL: edit `sql/fdd/postgres/rules/<rule>.sql`, then `sql/fdd/registry.yaml` and `sql/fdd/tuning_catalog.json`. New roles go in `role_map.json` and `input_contract.json`. See [Writing SQL rules](../sql-rules.html).
2. pandas: add the function in `open_fdd/rules/` and register it in `cookbook_catalog.py`. Keep role names, SI units, defaults, confirm time and gating the same as SQL.
3. Add the fault, healthy, missing-input and boundary cases to the parity dataset.
4. If the two intentionally differ, add the rule and a reason to `open_fdd/data/parity_known_differences.json`.
5. Regenerate: `python scripts/nf/gen_rule_docs.py && python scripts/nf/gen_cookbook.py`.

Use the [parity harness](parity-harness.html) to run the same proof on your own database.
""")
    return "".join(out)


# --------------------------------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------------------------------


def verify_examples(d: dict) -> list[str]:
    """Run every hand-written pandas example; each must really trip the fault. Returns problems."""
    import warnings
    problems = []
    for rid in HAND_EXAMPLES:
        rule = d["twins"][rid]
        code, _ = example_code(rule)
        ns: dict = {}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                exec(compile(code.replace("print(result.status, result.fault_hours)", "pass"), f"<example {rid}>", "exec"), ns)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{rid}: example raised {type(exc).__name__}: {exc}")
            continue
        if ns["result"].status != "FAULT":
            problems.append(f"{rid}: hand example returned {ns['result'].status}, expected FAULT")
    return problems


IMPERIAL = re.compile(r"°F|\bdegF\b|\bcfm\b|\bgpm\b|\bpsi\b|\bin\.?\s?w\.?c\b|inH2O|\bBtu|\btons?\b", re.I)


def imperial_leftovers(d: dict) -> list[str]:
    """Anything that is not SI in a parameter unit, label, role or rule text. The docs are SI-only, so this fails the build."""
    bad = []
    for rid, tun in d["tuning"].items():
        for k, p in (tun.get("parameters") or {}).items():
            if UNIT_LABEL.get(p.get("unit", ""), p.get("unit", "")) not in SI_UNITS or IMPERIAL.search(p.get("label", "") + k):
                bad.append(f"SQL {rid}.{k}: unit {p.get('unit')!r}, label {p.get('label')!r}")
    for rid, rule in d["twins"].items():
        for p in rule.params:
            if UNIT_LABEL.get(p.unit, p.unit) not in SI_UNITS or IMPERIAL.search(p.label + p.key):
                bad.append(f"pandas {rid}.{p.key}: unit {p.unit!r}, label {p.label!r}")
        if IMPERIAL.search(rule.title + " " + rule.equation + " " + rule.summary):
            bad.append(f"pandas {rid}: imperial text in title/equation/summary")
    return bad


def render_all() -> dict[str, str]:
    d = load()
    leftovers = imperial_leftovers(d)
    if leftovers:
        raise SystemExit("non-SI values in the rule catalogs (fix the catalog, not the docs):\n  " + "\n  ".join(leftovers))
    problems = verify_examples(d)
    if problems:
        raise SystemExit("pandas examples are broken:\n  " + "\n  ".join(problems))
    return {
        "sql-cookbook.md": render_sql(d),
        "pandas-cookbook.md": render_pandas(d),
        "parity.md": render_parity(d),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any generated page is stale")
    args = ap.parse_args()
    pages = render_all()
    stale = []
    for name, text in pages.items():
        path = OUT_DIR / name
        if args.check:
            cur = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else ""
            if cur != text:
                stale.append(f"docs/rules/{name}")
        else:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote docs/rules/{name} ({len(text.splitlines())} lines)")
    if args.check:
        if stale:
            print("stale: " + ", ".join(stale) + " (run python3 scripts/nf/gen_cookbook.py)", file=sys.stderr)
            return 1
        print(f"docs/rules/*.md is up to date ({len(pages)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
