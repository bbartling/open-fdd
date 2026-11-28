"""Sensor sweep quantity catalog (pandas oracle twin of ``fdd_core::sensor_sweep``)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Final

_ROLE_FILE = Path(__file__).resolve().parents[1] / "data" / "sensor_sweep_roles.json"
ASSESSABLE_ROLES_BY_SWEEP: Final[dict[str, tuple[str, ...]]] = {
    rule_id: tuple(roles) for rule_id, roles in json.loads(_ROLE_FILE.read_text(encoding="utf-8")).items()
}
if set(ASSESSABLE_ROLES_BY_SWEEP) != {"SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE", "SV-RATE"}:
    raise ValueError(f"{_ROLE_FILE}: expected exactly the five sensor sweep rules")

# SI only: degC / delta-degC, %RH, Pa, L/s, kW. Every per-role limit (range band, spike delta, flatline and stale
# tolerance, rate threshold) lives in open_fdd/data/sensor_sweep_limits.json. The SQL renderer
# (sql/fdd/render_rule.py) and the pandas sweeps below both read it through load_role_limits().
_LIMITS_FILE = Path(__file__).resolve().parents[1] / "data" / "sensor_sweep_limits.json"
SWEEP_QUANTITIES: Final[tuple[str, ...]] = (
    "absolute_temperature", "relative_humidity", "air_pressure", "volume_flow", "power",
)
_DEFAULT_KEYS: Final[tuple[str, ...]] = (
    "flat_tol_temperature", "stale_tol_temperature", "rate_per_h", "flat_s", "stale_s",
)
_ROLE_KEYS: Final[frozenset[str]] = frozenset(
    {"role", "quantity", "lo", "hi", "spike_delta", "flat_tol", "stale_tol", "rate_per_h", "source"}
)
# #1763: per-sensor limits. A merged document (role_limit_overrides.merge) may carry "sensors": one resolved entry per
# point (series_id) = its role's entry with the sensor's own fields on top; "fields" names the sensor's own fields.
_SENSOR_KEYS: Final[frozenset[str]] = _ROLE_KEYS | {"series_id", "fields"}
SENSOR_FIELDS: Final[tuple[str, ...]] = ("lo", "hi", "spike_delta", "flat_tol", "stale_tol", "rate_per_h")
# A series id is rendered into SQL as a literal: only these characters (NF point uuids, parity ids) are accepted.
SERIES_ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}")   # use fullmatch


def _finite(value: object, what: str, *, positive: bool = False, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    if positive and value <= 0:
        raise ValueError(f"{what} must be > 0, got {value!r}")
    return float(value)


def validate_role_limits(
    doc: dict, allowlists: dict[str, tuple[str, ...]] | None = None
) -> dict:
    """Validate a role-limit document (SI) and return it normalized. Raises ValueError on any invalid limit."""
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ValueError("role limits: version must be 1")
    defaults = doc.get("defaults")
    if not isinstance(defaults, dict) or set(defaults) != set(_DEFAULT_KEYS):
        raise ValueError(f"role limits: defaults must have exactly {list(_DEFAULT_KEYS)}")
    out_defaults = {k: _finite(defaults[k], f"defaults.{k}", positive=True) for k in _DEFAULT_KEYS}
    fallback: dict[str, dict[str, float]] = {}
    for quantity, lim in (doc.get("quantity_fallback") or {}).items():
        if quantity not in SWEEP_QUANTITIES:
            raise ValueError(f"quantity_fallback: unknown quantity {quantity!r}")
        lo, hi = _finite(lim.get("lo"), f"{quantity}.lo"), _finite(lim.get("hi"), f"{quantity}.hi")
        if lo >= hi:
            raise ValueError(f"quantity_fallback.{quantity}: lo must be < hi")
        fallback[quantity] = {"lo": lo, "hi": hi, "spike": _finite(lim.get("spike_delta"), f"{quantity}.spike_delta", positive=True)}
    roles: dict[str, dict] = {}
    for entry in doc.get("roles") or []:
        if not isinstance(entry, dict) or set(entry) != _ROLE_KEYS:
            raise ValueError(f"role limits: each role needs exactly {sorted(_ROLE_KEYS)}")
        role = entry["role"]
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role limits: role must be a non-empty string")
        if role in roles:
            raise ValueError(f"role limits: duplicate role {role!r}")
        roles[role] = _limit_entry(entry, role)
    sensors: dict[str, dict] = {}
    for entry in doc.get("sensors") or []:
        if not isinstance(entry, dict) or set(entry) != _SENSOR_KEYS:
            raise ValueError(f"sensor limits: each sensor needs exactly {sorted(_SENSOR_KEYS)}")
        sid = entry["series_id"]
        if not isinstance(sid, str) or not SERIES_ID_RE.fullmatch(sid):
            raise ValueError(f"sensor limits: invalid series id {sid!r}")
        if sid in sensors:
            raise ValueError(f"sensor limits: duplicate series id {sid!r}")
        role = roles.get(entry["role"])
        if role is None:
            raise ValueError(f"sensor {sid}: unknown role {entry['role']!r}")
        fields = entry["fields"]
        if not isinstance(fields, list) or not fields or any(f not in SENSOR_FIELDS for f in fields):
            raise ValueError(f"sensor {sid}: fields must name its own limits ({', '.join(SENSOR_FIELDS)})")
        if entry["quantity"] != role["quantity"]:
            raise ValueError(f"sensor {sid}: quantity {entry['quantity']!r} != role quantity {role['quantity']!r}")
        sensors[sid] = {**_limit_entry(entry, f"sensor {sid}"), "series_id": sid, "fields": sorted(set(fields))}
    for rule_id, names in (allowlists or {}).items():
        for name in names:
            entry = roles.get(name)
            if entry is None:
                raise ValueError(f"{rule_id}: assessed role {name!r} has no limits entry")
            if rule_id == "SV-SPIKE" and entry["spike_delta"] is None:
                raise ValueError(f"{rule_id}: role {name!r} needs spike_delta")
            if rule_id == "SV-FLATLINE":   # SV-STALE (#1673) is missing-data only: no value tolerance
                if entry["quantity"] not in ("absolute_temperature", "relative_humidity"):
                    raise ValueError(f"{rule_id}: role {name!r} quantity {entry['quantity']!r} has no declared tolerance")
                field = "flat_tol"
                if entry["quantity"] == "relative_humidity" and entry[field] is None:
                    raise ValueError(f"{rule_id}: humidity role {name!r} needs {field}")
    return {"defaults": out_defaults, "fallback": fallback, "roles": roles, "sensors": sensors}


def _limit_entry(entry: dict, what: str) -> dict:
    """One validated role (or sensor) limit entry, SI floats."""
    if entry["quantity"] not in SWEEP_QUANTITIES:
        raise ValueError(f"{what}: unknown quantity {entry['quantity']!r}")
    if not isinstance(entry["source"], str) or not entry["source"].strip():
        raise ValueError(f"{what}: source is required")
    lo, hi = _finite(entry["lo"], f"{what}.lo"), _finite(entry["hi"], f"{what}.hi")
    if lo >= hi:
        raise ValueError(f"{what}: lo ({lo}) must be < hi ({hi})")
    return {
        "role": entry["role"], "quantity": entry["quantity"], "lo": lo, "hi": hi, "source": entry["source"],
        "spike_delta": _finite(entry["spike_delta"], f"{what}.spike_delta", positive=True, allow_none=True),
        "flat_tol": _finite(entry["flat_tol"], f"{what}.flat_tol", positive=True, allow_none=True),
        "stale_tol": _finite(entry["stale_tol"], f"{what}.stale_tol", positive=True, allow_none=True),
        "rate_per_h": _finite(entry["rate_per_h"], f"{what}.rate_per_h", positive=True, allow_none=True),
    }


def load_role_limits(source: dict | Path | str | None = None) -> dict:
    """Load and validate role limits (default: the shipped JSON) against the sweep allowlists."""
    if source is None:
        source = _LIMITS_FILE
    doc = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
    return validate_role_limits(doc, ASSESSABLE_ROLES_BY_SWEEP)


ROLE_LIMITS: Final[dict] = load_role_limits()


def explicit_role_value(entry: dict, field: str, limits: dict | None = None) -> float | None:
    """A per-role flat_tol / stale_tol / rate_per_h that must be rendered or applied for that role.

    A temperature role whose value is null or equal to the global default follows the rule's tuner instead
    (so overriding the tuner still works). Other quantities (humidity) always carry their own value."""
    value = entry.get(field)
    if value is None:
        return None
    defaults = (limits or ROLE_LIMITS)["defaults"]
    if field == "rate_per_h":
        return None if value == defaults["rate_per_h"] else value
    if entry["quantity"] == "absolute_temperature":
        return None if value == defaults[f"{field}_temperature"] else value
    return value


_EXPECTED_CONSTANT_TOKENS: Final[tuple[str, ...]] = (
    "status",
    "cmd",
    "command",
    "setpoint",
    "occupancy_status",
    "occupancy",
    "operating_mode_status",
)


def quantity_for_haystack_role(role: str, limits: dict | None = None) -> str | None:
    r = (role or "").strip().lower()
    if not r:
        return None
    entry = (limits or ROLE_LIMITS)["roles"].get(r)
    if entry is not None:
        return entry["quantity"]
    if "humid" in r or r.endswith("-rh"):
        return "relative_humidity"
    if "static" in r or "pressure" in r or r.endswith("-dp"):
        return "air_pressure"
    if "temp" in r or "wetbulb" in r or "dewpoint" in r:
        return "absolute_temperature"
    return None


def limits_for_haystack_role(role: str, limits: dict | None = None) -> dict[str, float] | None:
    table = limits or ROLE_LIMITS
    entry = table["roles"].get(role)
    if entry is not None:
        return {"lo": entry["lo"], "hi": entry["hi"], "spike": entry["spike_delta"]}
    q = quantity_for_haystack_role(role, table)
    if q and q in table["fallback"]:
        return dict(table["fallback"][q])
    return None


def sensor_override(role: str, series_id: str | None, field: str, limits: dict | None = None) -> float | None:
    """The sensor's own saved ``field`` (#1763), else None (its role entry or the rule tuner applies)."""
    if not series_id:
        return None
    entry = ((limits or ROLE_LIMITS).get("sensors") or {}).get(series_id)
    if entry is None or entry["role"] != role or field not in entry["fields"]:
        return None
    return entry[field]


def starter_profile(
    role: str,
    unit: str | None = None,
    *,
    series_id: str | None = None,
    limits: dict | None = None,
    flatline_tol: float | None = None,
    rate_per_h: float | None = None,
) -> dict:
    """The SI limits one sensor starts from, and where each came from (#1763).

    Per field: the sensor's own saved value, then its role entry (shipped, or a saved site / equipment override), then
    the rule tuner (temperature flatline tolerance, rate), then the quantity starter (range and spike band of a
    temperature, humidity or pressure role with no entry). ``flatline_tol`` / ``rate_per_h`` are the rule tuners in
    effect (default: the shipped defaults). Rate has no quantity starter: it stays role-specific. Expected-constant
    roles, an unknown quantity, a unit that is not the quantity's SI unit, or a quantity with no starter and no role
    entry (flow, power) give ``{"assessed": False, "reason": ...}``: never a PASS."""
    table = limits or ROLE_LIMITS
    if is_expected_constant_role(role):
        return {"assessed": False, "reason": "commands, setpoints and states step by design"}
    q = quantity_for_haystack_role(role, table)
    if q is None:
        return {"assessed": False, "reason": "unknown quantity"}
    if unit is not None and not unit_declares_quantity(unit, q):
        return {"assessed": False, "reason": f"unit {unit!r} is not the SI unit of {q}"}
    entry = table["roles"].get(role)
    base = entry if entry is not None else table["fallback"].get(q)
    if base is None:
        return {"assessed": False, "reason": f"{q} needs a role entry (no quantity starter)"}
    layer = "role" if entry is not None else "quantity starter"
    out = {"assessed": True, "role": role, "quantity": q, "lo": base["lo"], "hi": base["hi"],
           "spike_delta": base["spike_delta"] if entry is not None else base["spike"]}
    sources = {"lo": layer, "hi": layer, "spike_delta": layer}
    flat = explicit_role_value(entry, "flat_tol", table) if entry is not None else None
    if flat is not None:
        out["flat_tol"], sources["flat_tol"] = flat, "role"
    elif q == "absolute_temperature":
        out["flat_tol"] = float(flatline_tol if flatline_tol is not None else table["defaults"]["flat_tol_temperature"])
        sources["flat_tol"] = "rule tuner"
    else:
        out["flat_tol"], sources["flat_tol"] = None, "none"
    rate = explicit_role_value(entry, "rate_per_h", table) if entry is not None else None
    if rate is not None:
        out["rate_per_h"], sources["rate_per_h"] = rate, "role"
    elif entry is not None and role in ASSESSABLE_ROLES_BY_SWEEP["SV-RATE"]:
        out["rate_per_h"] = float(rate_per_h if rate_per_h is not None else table["defaults"]["rate_per_h"])
        sources["rate_per_h"] = "rule tuner"
    else:
        out["rate_per_h"], sources["rate_per_h"] = None, "none"
    for field in ("lo", "hi", "spike_delta", "flat_tol", "rate_per_h"):
        own = sensor_override(role, series_id, field, table)
        if own is not None:
            out[field], sources[field] = own, "sensor"
    out["sources"] = sources
    return out


def _tolerance_for_role(role: str, temperature_tol: float, field: str, limits: dict | None) -> float:
    table = limits or ROLE_LIMITS
    q = quantity_for_haystack_role(role, table)
    if q not in ("absolute_temperature", "relative_humidity"):
        raise ValueError(f"{field} role {role!r} has no declared tolerance quantity ({q!r})")
    entry = table["roles"].get(role)
    explicit = explicit_role_value(entry, field, table) if entry else None
    if explicit is not None:
        return explicit
    if q == "relative_humidity":
        raise ValueError(f"{field} role {role!r} has no declared humidity tolerance")
    return float(temperature_tol)


def flatline_tolerance_for_role(role: str, temperature_tol: float, limits: dict | None = None) -> float:
    """Flatline span tolerance for ``role`` (SI). Temperature roles use the tuned ``flatline_tol`` (a delta-degC)
    unless the role carries its own value; %RH roles use their declared value and never inherit a temperature one."""
    return _tolerance_for_role(role, temperature_tol, "flat_tol", limits)


def stale_tolerance_for_role(role: str, temperature_tol: float, limits: dict | None = None) -> float:
    """Stale span tolerance for ``role``; same resolution as the flatline tolerance."""
    return _tolerance_for_role(role, temperature_tol, "stale_tol", limits)


def is_expected_constant_role(role: str) -> bool:
    r = (role or "").strip().lower()
    if not r:
        return False
    if r.endswith("-sp") or r.endswith("_sp") or "setpoint" in r:
        return True
    return any(tok in r for tok in _EXPECTED_CONSTANT_TOKENS)


def _norm_unit(unit: str) -> str:
    return "".join(ch for ch in unit.strip().lower() if ch.isalnum())


def unit_declares_quantity(unit: str | None, quantity: str) -> bool:
    """True only for the SI unit of ``quantity`` (degC, %, Pa, L/s, kW); anything else is not assessed, never converted."""
    if unit is None or not str(unit).strip():
        return False
    raw = str(unit).strip()
    t = _norm_unit(raw)
    if quantity == "absolute_temperature":
        return t in {"c", "degc", "celsius"}
    if quantity == "relative_humidity":
        return t in {"pct", "percent", "percent0100", "rh", "percentrelativehumidity", "percentrh"} or "%" in raw
    if quantity == "air_pressure":
        return t in {"pa", "pascal"}
    if quantity == "volume_flow":
        return t in {"ls", "lpersec", "lsec"}
    if quantity == "power":
        return t == "kw"
    return False


def sweep_assessable_role(
    role: str,
    unit: str | None,
    units_map: dict[str, str] | None = None,
    *,
    rule_id: str | None = None,
    limits: dict | None = None,
) -> bool:
    if rule_id is not None and role not in ASSESSABLE_ROLES_BY_SWEEP.get(rule_id, ()):
        return False
    if is_expected_constant_role(role):
        return False
    lim = limits_for_haystack_role(role, limits)
    if lim is None:
        return False
    resolved = (units_map or {}).get(role) or unit
    if not resolved or resolved in {"bool", "0/1"}:
        return False
    q = quantity_for_haystack_role(role, limits)
    if not q:
        return False
    return unit_declares_quantity(resolved, q)


def flatline_quantity_allowed(quantity: str) -> bool:
    return quantity != "air_pressure"
