"""Shared, data-driven unit and parity facts for the generated rule docs (stdlib only).

Used by gen_rule_docs.py and gen_cookbook.py. Nothing here is hand-copied into a page: every unit name, accepted
spelling, range and parity status is read from

    sql/fdd/input_contract.json            role -> scale (si:<unit>, fraction, boolean, percent_rh, text)
    sql/fdd/role_map.json                  SQL role -> Haystack role
    sql/fdd/tuning_catalog.json            parameter units and kinds, output columns
    open_fdd/data/units.json               quantity -> SI unit, imperial display, accepted declared units
    open_fdd/data/sensor_sweep_limits.json plausible physical range per Haystack role
    open_fdd/data/parity_known_differences.json  known SQL/pandas differences with reasons
    tests/parity/test_parity.py            NO_TWIN (read with ast)
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "sql" / "fdd" / "input_contract.json"
ROLE_MAP = ROOT / "sql" / "fdd" / "role_map.json"
TUNING = ROOT / "sql" / "fdd" / "tuning_catalog.json"
UNITS = ROOT / "open_fdd" / "data" / "units.json"
SWEEP = ROOT / "open_fdd" / "data" / "sensor_sweep_limits.json"
KNOWN_DIFFS = ROOT / "open_fdd" / "data" / "parity_known_differences.json"
PARITY_TEST = ROOT / "tests" / "parity" / "test_parity.py"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def fmt(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


# --------------------------------------------------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------------------------------------------------

_units = _load(UNITS)
_Q = _units["quantities"]

# Contract scale -> (quantity label, units.json quantity key, SI unit shown, extra accepted spellings not in units.json)
SCALES = {
    "si:degC": ("Temperature", "temperature", None, ""),
    "si:Pa": ("Pressure", "pressure_air", None, ""),
    "si:L/s": ("Flow", "flow_air", None, ""),
    "si:kW": ("Power", "power", None, ""),
    "si:kWh": ("Energy", "energy", None, ""),
    "si:ppm": ("Concentration", "concentration", None, ""),
    "si:A": ("Current", None, "A", "none (declare A)"),
    "si:count": ("Count", None, "count", "none"),
    "fraction": ("Command or position", "fraction", "0-1", "%, ratio"),
    "boolean": ("Status", "boolean", "0/1", "bool"),
    "percent_rh": ("Relative humidity", "humidity", "%RH (0-100)", "none"),
    "text": ("Text", None, "text", "none"),
}


# units.json quantity key -> the ``quantity`` its alias entries use
ALIAS_QUANTITY = {"pressure_air": "pressure", "pressure_water": "pressure", "flow_air": "flow", "flow_water": "flow",
                  "humidity": "percent"}


def accepted_units(quantity_key: str | None) -> str:
    """Declared units, other than the SI unit itself, that convert at ingest (units.json aliases)."""
    if quantity_key is None:
        return ""
    family = ALIAS_QUANTITY.get(quantity_key, quantity_key)
    names: list[str] = []
    for a in _units["aliases"]:
        if a["quantity"] != family:
            continue
        if a["to_si"] == {"mul": 1, "add": 0} and family != "temperature":
            continue  # the SI unit itself
        first = a["names"][0]
        if first == "°C":
            continue
        names.append(first)
    return ", ".join(names)


def scale_info(scale: str) -> dict:
    """quantity, si unit, accepted declared units and default range of one contract scale."""
    label, qkey, si, extra = SCALES[scale]
    if si is None:
        si = _Q[qkey]["si"]
    accepted = accepted_units(qkey) or extra
    if qkey in ("fraction", "boolean", "humidity"):
        accepted = extra
    return {"quantity": label, "si": si, "accepted": accepted or "none"}


_SCALE_RANGE = {"fraction": "0 to 1", "boolean": "0 or 1", "percent_rh": "0 to 100"}


# Haystack role names the pandas twins use that differ from the SQL contract's role_map name.
PANDAS_ALIASES = {"cw-fan-cmd": "tower_fan_cmd", "cooling-available": "clg_available"}
# Roles only a pandas twin reads (no SQL column): the scale follows from the suffix.
PANDAS_ONLY_SCALE = {"-cmd": "fraction", "-status": "boolean"}


class Contract:
    """Role -> scale, Haystack name and expected range, all from the shipped data files."""

    def __init__(self) -> None:
        self.roles = _load(CONTRACT)["roles"]
        self.role_map = _load(ROLE_MAP)
        self.haystack_to_sql = {v: k for k, v in self.role_map.items()}
        sweep = _load(SWEEP)
        self.sweep = {r["role"]: r for r in sweep["roles"]}

    def scale(self, sql_role: str | None) -> str:
        return self.roles[sql_role]["scale"]

    def sql_role(self, name: str) -> str | None:
        """SQL contract role for either an SQL role or a Haystack role name."""
        if name in self.roles:
            return name
        if name in self.haystack_to_sql:
            return self.haystack_to_sql[name]
        if name in PANDAS_ALIASES:
            return PANDAS_ALIASES[name]
        return name.replace("-", "_") if name.replace("-", "_") in self.roles else None

    def range_text(self, sql_role: str) -> str:
        scale = self.scale(sql_role)
        if scale in _SCALE_RANGE:
            return _SCALE_RANGE[scale]
        hs = self.role_map.get(sql_role, "")
        lim = self.sweep.get(hs)
        if lim:
            return f"{fmt(round(lim['lo'], 2))} to {fmt(round(lim['hi'], 2))}"
        return "-"

    def input_row(self, name: str, need: str) -> str:
        """One row of a per-rule Inputs table for a role given by SQL or Haystack name."""
        sql = self.sql_role(name)
        if sql is None:
            scale = next((v for k, v in PANDAS_ONLY_SCALE.items() if name.endswith(k)), None)
            if scale is None:
                raise SystemExit(f"role {name!r} is not in sql/fdd/input_contract.json or role_map.json")
            info = scale_info(scale)
            return (f"| - | `{name}` | {info['quantity']} | {cell(info['si'])} | {cell(info['accepted'])} | "
                    f"{_SCALE_RANGE[scale]} | {need} (pandas only) |")
        info = scale_info(self.scale(sql))
        hs = self.role_map.get(sql) or sql.replace("_", "-")
        return (f"| `{sql}` | `{hs}` | {info['quantity']} | {cell(info['si'])} | {cell(info['accepted'])} | "
                f"{self.range_text(sql)} | {need} |")


INPUT_HEADER = ["| Role (SQL column) | Haystack role | Quantity | SI unit | Also accepted (converted at ingest) | Expected range | Needed |",
                "|---|---|---|---|---|---:|---|"]

# tuning-catalog parameter unit -> label (SI), with the quantity "kind" deciding temperature differences.
PARAM_UNIT = {
    "degC": "°C", "degC_delta": "Δ°C", "degC_delta_per_h": "Δ°C/h", "pct": "%", "%": "%", "frac": "fraction (0-1)",
    "min": "min", "sec": "s", "h": "h", "L_per_s": "L/s", "Pa": "Pa", "kWh": "kWh", "ppm": "ppm", "bool": "0/1",
    "count": "count", "x": "x (ratio)", "unit": "signal units",
}


def _check_unit_names() -> None:
    """The unit names the docs print must be the ones units.json (the ingest table) declares."""
    expect = {"°C": _Q["temperature"]["si"], "Δ°C": _Q["temperature_delta"]["si"], "Δ°C/h": _Q["temperature_rate"]["si"],
              "Pa": _Q["pressure_air"]["si"], "L/s": _Q["flow_air"]["si"], "kWh": _Q["energy"]["si"],
              "ppm": _Q["concentration"]["si"], "%": _Q["percent"]["si"]}
    for label, si in expect.items():
        if label != si:
            raise SystemExit(f"docs unit {label!r} differs from sql/fdd or units.json unit {si!r}")


_check_unit_names()


def param_unit(p: dict) -> tuple[str, bool]:
    """(SI unit label, is_temperature_difference) of one tuning-catalog parameter."""
    unit = p.get("unit", "")
    label = PARAM_UNIT.get(unit)
    if label is None:
        raise SystemExit(f"parameter unit {unit!r} has no docs label (add it to docs_units.PARAM_UNIT)")
    delta = p.get("kind") == "temperature_difference" or unit in ("degC_delta", "degC_delta_per_h")
    if delta and unit == "degC":
        label = "Δ°C"
    return label, delta


PARAM_HEADER = ["| Parameter | Label | Default | Min | Max | SI unit |", "|---|---|---:|---:|---:|---|"]


def param_rows(params: dict) -> tuple[list[str], bool, bool]:
    rows, has_delta, info = [], False, False
    for k in sorted(params):
        p = params[k]
        unit, delta = param_unit(p)
        has_delta = has_delta or delta
        mark = ""
        if not p.get("effect_in_sql", True):
            mark, info = " †", True
        rows.append(f"| `{k}`{mark} | {cell(p.get('label', ''))} | {fmt(p['default'])} | {fmt(p['min'])} | {fmt(p['max'])} | {cell(unit)} |")
    return rows, has_delta, info


# output column -> (unit, meaning)
OUTPUT_COLUMNS = {
    "equipment_id": ("-", "equipment the row describes"),
    "fault_hours": ("h", "confirmed fault time"),
    "fault_pct": ("%", "fault_hours as a share of covered_hours"),
    "fault_samples": ("count", "samples in fault"),
    "fan_runtime_hours": ("h", "fan running time"),
    "total_hours": ("h", "assessed time"),
    "avg_zone_temp": ("°C", "mean zone temperature"),
    "min_zone_temp": ("°C", "lowest zone temperature"),
    "max_zone_temp": ("°C", "highest zone temperature"),
    "comfort_pct": ("%", "share of assessed time inside the comfort band"),
    "series_id": ("-", "assessed sensor series"),
    "sensor_role": ("-", "Haystack role of the sensor"),
    "covered_hours": ("h", "time the rule could assess (known inputs, gate open)"),
    "status": ("-", "assessment status text"),
}


def output_rows(cols: list[str]) -> list[str]:
    rows = ["| Output | Unit | Meaning |", "|---|---|---|"]
    for c in cols:
        if c not in OUTPUT_COLUMNS:
            raise SystemExit(f"output column {c!r} has no unit in docs_units.OUTPUT_COLUMNS")
        unit, meaning = OUTPUT_COLUMNS[c]
        rows.append(f"| `{c}` | {unit} | {meaning} |")
    return rows


def imperial_note(has_delta: bool, scales: set[str]) -> str:
    """One line, only where the display conversion is not obvious (a temperature difference has no +32)."""
    return "**Imperial display**: Δ°C parameters are differences, shown as Δ°F with no +32." if has_delta else ""


# --------------------------------------------------------------------------------------------------------------------
# units convention block (shared by both cookbooks)
# --------------------------------------------------------------------------------------------------------------------

_CONVENTION_ROWS = [
    ("Temperature", "temperature"), ("Temperature difference", "temperature_delta"), ("Temperature rate", "temperature_rate"),
    ("Air pressure", "pressure_air"), ("Water pressure", "pressure_water"), ("Air flow", "flow_air"), ("Water flow", "flow_water"),
    ("Power", "power"), ("Energy", "energy"), ("Relative humidity", "humidity"), ("Concentration", "concentration"),
]


def units_convention() -> str:
    rows = ["| Quantity | SI unit (rules compute in this) | Imperial display | Also accepted (converted at ingest) |", "|---|---|---|---|"]
    for label, key in _CONVENTION_ROWS:
        q = _Q[key]
        rows.append(f"| {label} | {q['si']} | {q['display']['imperial']['unit']} | {accepted_units(key) or ('% (the SI unit only)' if key == 'humidity' else 'none')} |")
    rows.append("| Command or position | fraction, 0-1 | % | `%`, ratio |")
    rows.append("| Status | 0/1 | 0/1 | `bool` |")
    return """## Units convention

- Rules compute in **SI only**. The engineer declares each point's unit in NF; ingest converts it to SI (`open_fdd/data/units.json`).
  Unknown or incompatible units are skipped, never guessed from the value.
- Imperial is display-only. Differences (Δ°C) convert with a factor of 1.8 and no +32.
- Fractions are 0-1, relative humidity is 0-100 %RH, statuses are 0/1.

""" + "\n".join(rows) + "\n"


# --------------------------------------------------------------------------------------------------------------------
# parity
# --------------------------------------------------------------------------------------------------------------------


def read_parity() -> tuple[dict, dict, set]:
    """(scope all: rule -> reason, other scopes: rule -> (scope, reason), NO_TWIN)."""
    doc = _load(KNOWN_DIFFS)
    known = {d["rule"]: d["reason"] for d in doc["differences"] if d["scope"] == "all"}
    other = {d["rule"]: (d["scope"], d["reason"]) for d in doc["differences"] if d["scope"] != "all"}
    tree = ast.parse(PARITY_TEST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "NO_TWIN":
            return known, other, set(ast.literal_eval(node.value))
    raise RuntimeError("NO_TWIN not found in tests/parity/test_parity.py")


def parity_status(rid: str, known: dict, no_twin: set) -> str:
    if rid in no_twin:
        return "SQL only"
    return "known divergence" if rid in known else "match"
