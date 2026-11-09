#!/usr/bin/env python3
"""Generate the Rule Cookbook (docs/rules/*.md) from the code, so the docs cannot drift.

    python3 scripts/nf/gen_cookbook.py            # write the five pages
    python3 scripts/nf/gen_cookbook.py --check    # exit 1 if any committed page is stale

Sources (all read, nothing hand-copied):
  nf-app/static/fdd-catalog.json        rule ids, kinds, roles, defaults (built from sql/fdd/registry.yaml)
  sql/fdd/tuning_catalog.json           parameter labels, limits, steps, SI units, output columns, SQL file names
  sql/fdd/role_map.json                 SQL history column -> Haystack role
  nf-app/rules/pack-postgres.json       the PostgreSQL SQL of every rule, rendered at its defaults
  open_fdd/rules/cookbook_catalog.py    the pandas twin of each rule (real function source via inspect)
  tests/parity/test_parity.py           KNOWN_DIVERGENT (with reasons) and NO_TWIN, read with ast

Pages: docs/rules/index.md, sql-cookbook.md, pandas-cookbook.md, parity.md (and docs/fdd-rules.md keeps its own
generator, scripts/nf/gen_rule_docs.py). Needs pandas + numpy + pyyaml (the pandas cookbook imports open_fdd.rules).
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CATALOG = ROOT / "nf-app" / "static" / "fdd-catalog.json"
TUNING = ROOT / "sql" / "fdd" / "tuning_catalog.json"
ROLE_MAP = ROOT / "sql" / "fdd" / "role_map.json"
PACK = ROOT / "nf-app" / "rules" / "pack-postgres.json"
PARITY_TEST = ROOT / "tests" / "parity" / "test_parity.py"
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


def fmt(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def anchor(rule_id: str) -> str:
    return rule_id.lower()


def liquid_safe(block: str) -> str:
    """Wrap a fenced block in raw tags when it contains Liquid delimiters."""
    if "{{" in block or "{%" in block:
        return "{% raw %}\n" + block + "\n{% endraw %}"
    return block


def code_block(lang: str, text: str) -> str:
    text = text.replace("\r\n", "\n").rstrip("\n")
    fence = "````" if "```" in text else "```"
    return liquid_safe(f"{fence}{lang}\n{text}\n{fence}")


def details(summary: str, body: str) -> str:
    return f'<details markdown="1">\n<summary>{summary}</summary>\n\n{body}\n\n</details>'


def unit_for_role(name: str) -> str:
    """SI unit of a role, from its Haystack-style or SQL-style name. Roles are SI by contract."""
    n = name.lower().replace("_", "-")
    if "co2" in n:
        return "ppm"
    if n.endswith("-kwh") or n == "kwh" or "energy" in n:
        return "kWh"
    if n.endswith("-kw") or "power" in n:
        return "kW"
    if "amps" in n or "current" in n:
        return "A"
    if "request" in n:
        return "count"
    if "humidity" in n or n.endswith("-h") or n.endswith("-rh") or n == "zone-rh":
        return "%"
    if "static" in n or n.endswith("-dp") or n.endswith("-dp-sp") or "differential-pressure" in n or "pressure" in n:
        return "Pa"
    if "flow" in n:
        return "L/s"
    if any(k in n for k in ("status", "enabled", "available", "satisfied", "occ-mode", "occupancy", "occupied", "proof")):
        return "0/1"
    if any(k in n for k in ("cmd", "damper", "valve", "pct", "position", "speed")):
        return "%"
    if any(k in n for k in ("temp", "dewpoint", "wetbulb", "wet-bulb")) or n in {"sat", "mat", "rat", "oa-t", "zone-t", "web-oa-t", "web-wb-t", "web-oa-dp"}:
        return "°C"
    if n.endswith("-t") or n.endswith("-sp") or n.endswith("-leave-t"):
        return "°C"
    return ""


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
    pack = json.loads(PACK.read_text(encoding="utf-8"))["rules"]
    role_map = json.loads(ROLE_MAP.read_text(encoding="utf-8"))
    rules = sorted(cat["rules"], key=lambda r: r["id"])
    from open_fdd.rules.cookbook_catalog import RULES_BY_ID  # noqa: E402 - needs sys.path set above
    twins = {r["id"]: RULES_BY_ID[PANDAS_ID.get(r["id"], r["id"])] for r in rules if PANDAS_ID.get(r["id"], r["id"]) in RULES_BY_ID}
    known, no_twin = read_parity()
    return {"cat": cat, "tuning": tuning, "pack": pack, "role_map": role_map, "rules": rules, "twins": twins,
            "known": known, "no_twin": no_twin}


def read_parity() -> tuple[dict, set]:
    """KNOWN_DIVERGENT / NO_TWIN from tests/parity/test_parity.py, read with ast (no pytest import)."""
    tree = ast.parse(PARITY_TEST.read_text(encoding="utf-8"))
    env: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"_EDGE", "_PROOF", "_WX", "_GATE", "KNOWN_DIVERGENT", "NO_TWIN"}:
                env[name] = eval(compile(ast.Expression(node.value), str(PARITY_TEST), "eval"), {"__builtins__": {}}, env)  # noqa: S307
    return env["KNOWN_DIVERGENT"], set(env["NO_TWIN"])


def kind_legend(cat: dict) -> str:
    rows = ["| Kind | Haystack equipment it matches |", "|---|---|"]
    for k, v in cat["equipment_kinds"].items():
        rows.append(f"| `{k}` | {', '.join(f'`{x}`' for x in v)} |")
    return "\n".join(rows)


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
# SQL cookbook
# --------------------------------------------------------------------------------------------------------------------


def roles_table(d: dict, r: dict) -> str:
    roles = d["cat"]["roles"]
    rows = ["| Role (SQL column) | Haystack role | NF class | SI unit | Needed |", "|---|---|---|---|---|"]
    req = r.get("required_roles") or []
    opt = [x for x in (r.get("optional_roles") or []) if x not in req]
    for role, need in [(x, "required") for x in req] + [(x, "optional") for x in opt]:
        info = roles.get(role, {})
        hs = d["role_map"].get(role) or info.get("name") or ""
        cls = ", ".join(f"`{c}`" for c in info.get("classes") or []) or "-"
        unit = unit_for_role(hs) or unit_for_role(role) or "-"
        rows.append(f"| `{role}` | {cell(hs) or '-'} | {cls} | {unit} | {need} |")
    return "\n".join(rows)


def sql_params_table(tun: dict) -> str:
    params = tun.get("parameters") or {}
    if not params:
        return "_This rule has no tunable parameters._"
    rows = ["| Parameter | Label | Default | Min | Max | Step | SI unit |", "|---|---|---:|---:|---:|---:|---|"]
    info = False
    for k in sorted(params):
        p = params[k]
        unit = UNIT_LABEL.get(p.get("unit", ""), p.get("unit", ""))
        mark = ""
        if not p.get("effect_in_sql", True):
            mark = " †"
            info = True
        rows.append(f"| `{k}`{mark} | {cell(p.get('label', ''))} | {fmt(p['default'])} | {fmt(p['min'])} | {fmt(p['max'])} | {fmt(p['step'])} | {cell(unit)} |")
    if info:
        rows.append("")
        rows.append("† informational: this control has no effect in the SQL template.")
    return "\n".join(rows)


def render_sql(d: dict) -> str:
    n = len(d["rules"])
    out = [f"""---
title: SQL cookbook
parent: Rule Cookbook
nav_order: 1
---

# SQL cookbook

<!-- GENERATED by scripts/nf/gen_cookbook.py from the rule pack, the tuning catalog and the registry. Do not edit by hand. -->

**{n} PostgreSQL rules**, the production FDD engine. Each section is one rule: what it needs, what you can tune, what it returns and the
**exact SQL the app runs**, rendered at the rule's default parameters. Everything is **SI**: °C, Δ°C, Pa, L/s, kW, kWh, % (see
[Units](../units.html)). The [pandas cookbook](pandas-cookbook.html) has the same rules as Python and [parity](parity.html) says where the two
agree.

How the SQL runs: the FDD hook feeds one scoped, SI, wide `history` table (one column per role, one row per equipment per timestamp) to the rule and
reads one row per equipment back. Rules never convert units. A fault must hold for the rule's confirm time before it counts, and a gap longer than one
hour is unknown rather than fault or ok. More in [sql/fdd/README.md]({GH}/sql/fdd/README.md).

Jump to a rule with its id, for example `sql-cookbook.html#fc1`.
"""]
    out.append("## Rules by equipment\n")
    for key, title, _blurb, members in grouped(d):
        links = " · ".join(f"[{r['id']}](#{anchor(r['id'])})" for r in members)
        out.append(f"**{title}** ({len(members)}): {links}\n")
    out.append("\n---\n")
    for key, title, blurb, members in grouped(d):
        out.append(f"\n## {title} {{#group-{key}}}\n\n{blurb}\n")
        for r in members:
            rid = r["id"]
            tun = d["tuning"][rid]
            sql = d["pack"][rid]["sql"].replace("\r\n", "\n").rstrip("\n")
            cols = d["pack"][rid].get("output_columns") or tun.get("output_columns") or []
            kinds = ", ".join(f"`{k}`" for k in r.get("equipment_kinds") or []) or "any equipment"
            twin = d["twins"].get(rid)
            twin_txt = f"[pandas twin](pandas-cookbook.html#{anchor(rid)})" if twin else "SQL only (no pandas twin)"
            status = "SQL only" if rid not in d["twins"] else ("match" if rid not in d["known"] else "known divergence")
            out.append(f"\n### {rid} {{#{anchor(rid)}}}\n")
            out.append(f"{r.get('description', '')}\n")
            out.append(f"**Priority** {r.get('priority', '')} · **Equipment** {kinds} · **Confirm** {confirm_text(r)} · "
                       f"**Parity** [{status}](parity.html#{anchor(rid)}) · {twin_txt}\n")
            out.append("**Inputs**\n\n" + roles_table(d, r) + "\n")
            out.append("**Parameters**\n\n" + sql_params_table(tun) + "\n")
            out.append("**Output columns**: " + (", ".join(f"`{c}`" for c in cols) or "none") + "\n")
            out.append(details(f"SQL at defaults ({len(sql.splitlines())} lines) · "
                               f"<a href=\"{GH}/sql/fdd/postgres/rules/{tun['sql_file']}\">template file</a>", code_block("sql", sql)) + "\n")
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------------------------------------
# pandas cookbook
# --------------------------------------------------------------------------------------------------------------------


def pandas_params_table(rule) -> str:
    if not rule.params:
        return "_No tunable parameters._"
    rows = ["| Parameter | Label | Default | Min | Max | Step | Unit |", "|---|---|---:|---:|---:|---:|---|"]
    for p in sorted(rule.params, key=lambda x: x.key):
        rows.append(f"| `{p.key}` | {cell(p.label)} | {fmt(p.default)} | {fmt(p.min)} | {fmt(p.max)} | {fmt(p.step)} | {cell(p.unit)} |")
    return "\n".join(rows)


# (base, amplitude) per unit for the generated example frame; sensors wiggle so no series is a flatline.
EXAMPLE_VALUE = {"°C": (21.0, 2.0), "%": (50.0, 20.0), "Pa": (250.0, 40.0), "L/s": (100.0, 25.0), "kW": (12.0, 3.0), "kWh": (50.0, 10.0),
                 "ppm": (600.0, 150.0), "A": (15.0, 3.0), "count": (1.0, 1.0), "0/1": (1.0, 0.0)}

# Hand-written examples that really trip the fault (verified by gen_cookbook.py on every run).
HAND_EXAMPLES = {
    "FC1": ('{"duct-static-pressure": 150.0, "duct-static-pressure-sp": 250.0, "fan-cmd": 100.0}', "AHU-1", "AHU",
            "Duct static (Pa) sits 100 Pa under its setpoint while the fan runs: low static at full fan."),
    "ECON-1": ('{"fan-cmd": 100.0, "outside-air-damper": 0.0, "outside-air-temp": 16.0}', "AHU-1", "AHU",
               "Outside air is 16 °C (above the 12.8 °C economizer limit) yet the OA damper is shut."),
    "CHW-1": ('{"chilled-water-supply-temp": 6.5, "chilled-water-return-temp": 7.5, "chiller-status": 1.0}', "CHILLER-1", "CHILLER",
              "Chilled-water ΔT is 1 Δ°C, below the 2.2 Δ°C minimum while the chiller runs: low-ΔT syndrome."),
}


# Extra columns a rule needs beyond its required roles to get past its operational gate / optional-input checks.
EXTRA_ROLES = {
    "CHW-NOLOAD-1": ["chiller-status", "building-zone-load-satisfied"],
    "CW-APR-1": ["web-outside-air-wetbulb", "tower-fan-cmd", "chiller-status"],
    "CW-FAN-1": ["web-outside-air-wetbulb", "tower-fan-cmd", "chiller-status"],
    "CW-OPT-1": ["web-outside-air-wetbulb", "chiller-status"],
    "ECON-3": ["web-outside-air-temp", "web-outside-air-humidity"], "ECON-6": ["web-outside-air-temp"],
    "ECON-7": ["web-outside-air-temp", "web-outside-air-humidity", "cooling-valve"], "MECH-OAT-1": ["web-outside-air-temp", "chiller-status"],
    "PID-HUNT-1": ["cooling-valve"], "SCHED-247": ["fan-status"], "TRIM-3": ["pump-status"], "TRIM-4": ["pump-status"],
    "VAV-1": ["occ-mode"],
    "SV-RANGE": ["zone-air-temp", "outside-air-temp", "duct-static-pressure"], "SV-FLATLINE": ["zone-air-temp", "outside-air-temp"],
    "SV-SPIKE": ["zone-air-temp", "outside-air-temp"], "SV-STALE": ["zone-air-temp", "outside-air-temp"],
    "SV-RATE": ["zone-air-temp", "outside-air-temp"],
}


def example_code(rule, equip_id: str | None = None, equip_type: str | None = None) -> tuple[str, str]:
    """(source, kind note) of a minimal runnable example for a pandas rule."""
    rid = rule.id
    kind = (rule.equipment_kinds[0] if rule.equipment_kinds else "ahu")
    if rid in HAND_EXAMPLES:
        frame, eid, etype, note = HAND_EXAMPLES[rid]
        cols = frame
    else:
        eid = f"{kind.upper()}-1"
        etype = kind.upper()
        note = ""
        items = []
        roles = list(rule.required_roles) + [x for x in EXTRA_ROLES.get(rid, []) if x not in rule.required_roles]
        for role in roles:
            base, amp = EXAMPLE_VALUE.get(unit_for_role(role), (1.0, 0.0))
            wob = f" + {amp:g} * wave" if amp else ""
            items.append(f'    "{role}": {base:g}{wob},')
        cols = "{\n" + "\n".join(items) + "\n}" if items else "{}"
        extra = [x for x in EXTRA_ROLES.get(rid, []) if x not in rule.required_roles]
        note = "Illustrative SI values for the rule's inputs; swap in your own series (they are not tuned to trip this rule)."
        if extra:
            note += " " + ", ".join(f"`{x}`" for x in extra) + (" is" if len(extra) == 1 else " are") + " not required but lets the rule get past its operational gate or optional-input checks."
    src = [
        "import numpy as np",
        "import pandas as pd",
        "import open_fdd",
        "from open_fdd.rules import run_rule",
        "",
        "# one day on a 5-minute grid, UTC timestamps, every value SI (degC, Pa, L/s, kW, %, 0-1)",
        'idx = pd.date_range("2026-01-05", periods=288, freq="5min", tz="UTC", name="timestamp_utc")',
        "wave = np.sin(np.linspace(0, 2 * np.pi, len(idx)))",
        f"df = pd.DataFrame({cols}, index=idx)" if rid in HAND_EXAMPLES else f"df = pd.DataFrame({cols}, index=idx)",
        f'df.attrs.update(equipment_id="{eid}", equipment_type="{etype}")',
        *(['df.attrs["role_units"] = {c: "°C" if "temp" in c else "Pa" for c in df.columns}  # sensor sweeps assess a series only when its declared unit is SI']
          if rule.sensor_sweep else []),
        "",
        f'result = run_rule("{rid}", df, params={{"confirm_min": {fmt(round(float(rule.confirm_seconds) / 60.0, 6))}}})',
        "print(result.status, result.fault_hours)",
    ]
    if rid in HAND_EXAMPLES:
        # constant series frame: no wave needed
        src = [s for s in src if not s.startswith("wave =")]
    return "\n".join(src), note


def pandas_source(rule) -> str:
    return inspect.getsource(rule.compute).rstrip("\n")


def render_pandas(d: dict) -> str:
    twins = d["twins"]
    sql_only = [r for r in d["rules"] if r["id"] not in twins]
    n = len(twins)
    out = [f"""---
title: Pandas cookbook
parent: Rule Cookbook
nav_order: 2
---

# Pandas cookbook

<!-- GENERATED by scripts/nf/gen_cookbook.py from open_fdd/rules/cookbook_catalog.py. Do not edit by hand. -->

**{n} rules as pandas functions**: the oracle twin of the [SQL cookbook](sql-cookbook.html). Use them in notebooks, for CSV and RCx studies, and as
the reference the SQL is tested against ([parity](parity.html)). The code shown for each rule is the real function from
[`open_fdd/rules/cookbook_catalog.py`]({GH}/open_fdd/rules/cookbook_catalog.py), pulled with `inspect.getsource`. The
{len(sql_only)} rules without a twin are marked **SQL only**.

**Conventions**

- Input is a `DataFrame` with a UTC `DatetimeIndex` and one **Haystack-role column per signal** (`duct-static-pressure`,
  `outside-air-temp`, ...). Everything is **SI**: °C, Δ°C, Pa, L/s, kW, kWh; commands and positions are fractions (0-1), statuses 0/1, humidity %RH (0-100) (`sql/fdd/input_contract.json`). The rules never convert units or guess a scale; convert at
  ingest.
- `run_rule(rule_id, df, params=..., poll_seconds=300)` returns a result with `status` (`PASS`, `FAULT`, `SKIPPED_MISSING_ROLES`, ...),
  `fault_hours`, `confirmed_fault` and `raw_fault` masks. Set `df.attrs["equipment_id"]` and `df.attrs["equipment_type"]` (`AHU`, `VAV`, `CHILLER`, ...).
- A rule function returns the **raw** boolean fault mask; the runner applies the operational gate (equipment on) and the confirm delay (`confirm_min`).
- Parameter keys match the SQL catalog, so a tuned value can be carried between the two.

Jump to a rule with its id, for example `pandas-cookbook.html#fc1`.
"""]
    out.append("## Rules by equipment\n")
    for key, title, _blurb, members in grouped(d):
        links = " · ".join(f"[{r['id']}](#{anchor(r['id'])})" for r in members)
        out.append(f"**{title}** ({len(members)}): {links}\n")
    out.append("\n---\n")
    for key, title, blurb, members in grouped(d):
        out.append(f"\n## {title} {{#group-{key}}}\n\n{blurb}\n")
        for r in members:
            rid = r["id"]
            rule = twins.get(rid)
            out.append(f"\n### {rid} {{#{anchor(rid)}}}\n")
            if rule is None:
                out.append(f"{r.get('description', '')}\n")
                out.append(f"**SQL only.** No pandas twin: this rule is an aggregate or utility analytic. See the [SQL version](sql-cookbook.html#{anchor(rid)}) "
                           f"and [parity](parity.html#{anchor(rid)}).\n")
                continue
            kinds = ", ".join(f"`{k}`" for k in rule.equipment_kinds) or "any equipment"
            out.append(f"{rule.summary or rule.title}\n")
            out.append(f"**{cell(rule.title)}** · **Family** {rule.family} · **Equipment** {kinds} · **Confirm** {fmt(round(rule.confirm_seconds / 60.0, 6))} min · "
                       f"[SQL version](sql-cookbook.html#{anchor(rid)}) · [parity](parity.html#{anchor(rid)})\n")
            if rule.equation and rule.equation.strip() != (rule.summary or "").strip():
                out.append(f"**Equation**: {rule.equation.strip()}\n")
            req = ", ".join(f"`{x}`" for x in rule.required_roles) or "none"
            opt = ", ".join(f"`{x}`" for x in rule.optional_roles) or "none"
            out.append(f"**Required roles**: {req}  \n**Optional roles**: {opt}\n")
            out.append("**Parameters (SI defaults)**\n\n" + pandas_params_table(rule) + "\n")
            src = pandas_source(rule)
            fn = rule.compute.__name__
            out.append(details(f"Source: <code>{fn}</code> ({len(src.splitlines())} lines)", code_block("python", src)) + "\n")
            code, note = example_code(rule)
            out.append(details("Minimal runnable example", (note + "\n\n" if note else "") + code_block("python", code)) + "\n")
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------------------------------------
# parity
# --------------------------------------------------------------------------------------------------------------------

NO_TWIN_WHY = "Aggregate or utility analytic: it has no pandas function in `open_fdd.rules`, so there is nothing to compare."


def param_default_differences(d: dict) -> list[tuple[str, str, float, float]]:
    out = []
    for r in d["rules"]:
        tw = d["twins"].get(r["id"])
        if tw is None:
            continue
        tun = d["tuning"][r["id"]]["parameters"]
        for p in tw.params:
            q = tun.get(p.key)
            if q and abs(float(p.default) - float(q["default"])) > 1e-4 * max(1.0, abs(float(q["default"]))):
                out.append((r["id"], p.key, float(p.default), float(q["default"])))
    return out


def render_parity(d: dict) -> str:
    twins, known, no_twin = d["twins"], d["known"], d["no_twin"]
    total = len(d["rules"])
    matched = [r["id"] for r in d["rules"] if r["id"] in twins and r["id"] not in known]
    reasons: dict[str, list[str]] = {}
    for rid in sorted(known):
        reasons.setdefault(known[rid], []).append(rid)
    out = [f"""---
title: Parity
parent: Rule Cookbook
nav_order: 3
---

# Parity: pandas == SQL

<!-- GENERATED by scripts/nf/gen_cookbook.py from tests/parity/test_parity.py. Do not edit by hand. -->

Is the SQL rule the same as its pandas twin? This page answers that for every one of the {total} rules, straight from the parity test
([`tests/parity/test_parity.py`]({GH}/tests/parity/test_parity.py)), so it changes when the test changes.

| | Rules |
|---|---:|
| SQL rules | **{total}** |
| With a pandas twin | **{len(twins)}** |
| Match on the synthetic suite | **{len(matched)}** |
| Known divergence (documented below) | **{len(known)}** |
| SQL only (no twin) | **{len(no_twin)}** |

## What "match" means

The suite builds a deterministic SI dataset (`AHU-1` mostly healthy, `AHU-2` with injected fault windows; three days on a 5-minute grid) and runs
it through the SQL pack on PGlite (real PostgreSQL) and SQLite, and through the pandas rules. A rule **matches** when its confirmed fault hours agree
to 1e-6 h on every equipment. The two SQL engines must agree with each other on all {total} rules. The test fails in both directions: a rule that starts
to diverge, or one that starts to match, has to be moved in the table below, so this page cannot go stale. Matching on this dataset is strong
evidence, not a proof for every possible input.

## Why {len(known)} of {len(twins)} differ

**Not units.** Every value on both sides is SI and the threshold equations were checked to use the same constants. The differences are in **how the rule
decides the equipment is "on" (the gate), how it proves cooling or heating (the proof), how weather is joined, or how many samples it holds after a mode
change**. Two rules differ for their own reasons: `SV-RATE` is a different algorithm and `TRIM-4` treats missing inputs differently.

"""]
    for reason, ids in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        out.append(f"- **{len(ids)} {'rule' if len(ids) == 1 else 'rules'}**: {reason}. ({', '.join(f'`{i}`' for i in ids)})")
    out.append(f"""
Closing a gap means making one side adopt the other's definition (for example, SQL adopting the pandas mechanical-proof order) and removing the
rule from `KNOWN_DIVERGENT`. Until then the SQL result is the production result and the pandas twin is the notebook reference; read the reason column
before comparing numbers between them. Other known differences: [`sql/fdd/KNOWN_DIFFERENCES.md`]({GH}/sql/fdd/KNOWN_DIFFERENCES.md).

## Status of every rule
""")
    out.append("| Rule | Status | Detail |\n|---|---|---|")
    for r in d["rules"]:
        rid = r["id"]
        if rid not in twins:
            status, detail = "SQL only", NO_TWIN_WHY
        elif rid in known:
            status, detail = "Known divergence", known[rid]
        else:
            status, detail = "Match", "Same confirmed fault hours as the SQL on the synthetic suite."
        out.append(f"| <a id=\"{anchor(rid)}\"></a>[{rid}](sql-cookbook.html#{anchor(rid)}) | {status} | {cell(detail)} |")
    diffs = param_default_differences(d)
    out.append("\n## Parameter default differences\n")
    if diffs:
        out.append("Shared parameter keys whose SI default differs between the pandas rule and the SQL catalog (none of them is a unit problem). "
                   "`test_pandas_defaults_equal_sql_catalog` pins temperature, flow and pressure defaults; these are fraction/hour/signal-span keys outside that check.\n")
        out.append("| Rule | Parameter | pandas default | SQL default |\n|---|---|---:|---:|")
        for rid, key, a, b in diffs:
            out.append(f"| [{rid}](sql-cookbook.html#{anchor(rid)}) | `{key}` | {fmt(a)} | {fmt(b)} |")
    else:
        out.append("None: every shared parameter key has the same default on both sides.")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------------------------------------------------


def render_index(d: dict) -> str:
    total, ntw = len(d["rules"]), len(d["twins"])
    matched = [r for r in d["rules"] if r["id"] in d["twins"] and r["id"] not in d["known"]]
    out = [f"""---
title: Rule Cookbook
nav_order: 5
has_children: true
permalink: /rules/
---

# Rule Cookbook

<!-- GENERATED by scripts/nf/gen_cookbook.py. Do not edit by hand. -->

The Open-FDD rule library, written out in full: **{total} SQL rules** that run in production and **{ntw} pandas twins** for notebooks and
verification, all in **SI units**. Every page here is generated from the same code that ships, so it cannot drift: CI fails when it is stale.

| Page | What is in it | Rules |
|---|---|---:|
| [SQL cookbook](sql-cookbook.html) | Each rule's inputs, tunable parameters with SI limits, output columns and the exact PostgreSQL at its defaults | {total} |
| [Pandas cookbook](pandas-cookbook.html) | The same rules as Python: the real function source, SI defaults, and a runnable example | {ntw} |
| [Parity](parity.html) | Does pandas equal SQL, rule by rule, and why {len(d['known'])} differ | {total} |
| [FDD rules catalog](../fdd-rules.html) | One-table summary of every rule and its default | {total} |

## How to read a rule

Each rule section answers the same questions:

1. **What it flags**: one sentence, then priority (P0 is core) and the equipment kinds it applies to.
2. **Inputs**: the roles (points) it needs. A rule runs only when every *required* role is bound in your Haystack model; *optional* roles refine it.
   The Haystack role and NF class tell you what to tag; see [Modeling](../modeling.html).
3. **Parameters**: key, default, min, max, step and unit. These are the sliders in the app. `confirm_min` is how long the condition must hold before it
   counts as a fault.
4. **Output columns**: what the rule returns, one row per equipment.
5. **The code**: the exact SQL (collapsed) or the real pandas function, so you can read, copy or port it.

## SI units

Everything is SI, with no exceptions: temperature **°C**, temperature differences **Δ°C** (no 32-degree offset), pressure **Pa**, flow **L/s**, power **kW**,
energy **kWh**, concentration **ppm**. Every command and position (fan, pump and tower commands, valve and damper positions) is a **fraction (0-1)**,
every status is **0/1**, and humidity is **%RH (0-100)**: one declared scale per column, from `sql/fdd/input_contract.json`. Rules never convert units and never
guess a scale by magnitude. Points are converted once at ingest (a `%` point is divided by 100, a command point with no unit is skipped, not guessed), and back
to the user's display system only in the UI. Sensor-validation rules (`SV-*`) assess a series only when its declared unit is the SI unit of its
quantity. See [Units](../units.html).

## Equipment kinds

A rule's **equipment kinds** are Open-FDD kinds; each matches these Haystack equipment (a rule with no kinds applies to any equipment).

{kind_legend(d["cat"])}

## Rules by equipment

| Group | Rules | Count |
|---|---|---:|"""]
    for key, title, _b, members in grouped(d):
        links = ", ".join(f"[{r['id']}](sql-cookbook.html#{anchor(r['id'])})" for r in members)
        out.append(f"| [{title}](sql-cookbook.html#group-{key}) | {links} | {len(members)} |")
    out.append(f"""
## At a glance

- **{total}** SQL rules, **{ntw}** pandas twins, **{len(d['no_twin'])}** SQL-only analytics.
- **{len(matched)} of {ntw}** twins match the SQL exactly on the synthetic parity suite; **{len(d['known'])}** differ in gating, proof or weather join, never in units. Details in [Parity](parity.html).
- Source of truth: [`sql/fdd/`]({GH}/sql/fdd) (SQL + tuning), [`nf-app/rules/pack-postgres.json`]({GH}/nf-app/rules/pack-postgres.json) (the pack the app runs),
  [`open_fdd/rules/`]({GH}/open_fdd/rules) (pandas).
- Regenerate with `python3 scripts/nf/gen_cookbook.py` (`--check` fails when a page is stale).
""")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------------------------------


def verify_examples(d: dict) -> list[str]:
    """Run every generated pandas example; hand-written ones must also trip the fault. Returns problems."""
    import warnings
    problems = []
    for rid, rule in d["twins"].items():
        code, _ = example_code(rule)
        ns: dict = {}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                exec(compile(code.replace("print(result.status, result.fault_hours)", "pass"), f"<example {rid}>", "exec"), ns)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{rid}: example raised {type(exc).__name__}: {exc}")
            continue
        status = ns["result"].status
        if rule.id in HAND_EXAMPLES and status != "FAULT":
            problems.append(f"{rid}: hand example returned {status}, expected FAULT")
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
        "index.md": render_index(d),
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
