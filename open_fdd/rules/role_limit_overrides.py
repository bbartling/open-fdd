"""Persisted sensor-sweep role-limit overrides (#1589): SI only, versioned, shipped < site < equipment.

The shipped limits are ``open_fdd/data/sensor_sweep_limits.json`` (phase 1, #1581). An override is a small SI document

    {"version": 1, "roles": {"zone-air-temp": {"lo": 12.0, "hi": 30.0}, ...}}

stored as one revision of ``fdd.rule_config`` (rule_id ``SV-LIMITS``; scope_key ``site`` or ``equip:<equipment id>``;
append-only, at most one active revision per scope). Precedence per field: shipped file, then the site override, then
the equipment override. The merged document is validated with ``validate_role_limits`` before anything is saved, and
``render_rule.render(rule_id, role_limits=effective_role_limits(...))`` gives the SQL a scheduled run uses. The NF
hook twin is ``nf-app/hooks/lib/role-limits.js`` (same merge, same conversions, same fragment rendering).

Display units are an editor concern: :func:`to_si` / :func:`from_si` convert degF (absolute temperature, temperature
difference and rate are separate conversions), inH2O, cfm and gpm, with the factors of ``open_fdd/data/unit_factors.json``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from open_fdd.rules import sensor_sweep_catalog as _cat

LIMITS_RULE_ID = "SV-LIMITS"
SITE_SCOPE = "site"
EQUIP_SCOPE_PREFIX = "equip:"
OVERRIDE_VERSION = 1
SWEEP_RULES = ("SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-STALE", "SV-RATE")

# Editable fields and the kind of quantity each one is (decides the unit conversion).
FIELD_KIND: dict[str, str] = {
    "lo": "absolute", "hi": "absolute",
    "spike_delta": "difference", "flat_tol": "difference", "stale_tol": "difference",
    "rate_per_h": "rate",
}
# Which sweep rule consumes each field (the editor shows it next to the value).
FIELD_RULES: dict[str, tuple[str, ...]] = {
    "lo": ("SV-RANGE",), "hi": ("SV-RANGE",), "spike_delta": ("SV-SPIKE",), "flat_tol": ("SV-FLATLINE",),
    "stale_tol": ("SV-STALE",), "rate_per_h": ("SV-RATE",),
}

_FACTORS = json.loads((Path(__file__).resolve().parents[1] / "data" / "unit_factors.json").read_text(encoding="utf-8"))["factors"]
SI_UNIT = {"absolute_temperature": "degC", "relative_humidity": "%RH", "air_pressure": "Pa", "volume_flow": "L/s", "power": "kW"}
# display unit -> SI factor, per quantity (multiplicative; temperature handled separately because of the offset).
_MULTIPLY: dict[str, dict[str, float]] = {
    "relative_humidity": {"%RH": 1.0, "%": 1.0},
    "air_pressure": {"Pa": 1.0, "inH2O": _FACTORS["pa_per_in_wc"]["value"], "psi": _FACTORS["pa_per_psi"]["value"]},
    "volume_flow": {"L/s": 1.0, "cfm": _FACTORS["lps_per_cfm"]["value"], "gpm": _FACTORS["lps_per_gpm"]["value"]},
    "power": {"kW": 1.0, "ton": _FACTORS["kw_per_ton"]["value"]},
}
TEMPERATURE_UNITS = ("degC", "degF")


def display_units(quantity: str) -> tuple[str, ...]:
    """Units the editor accepts for a quantity (SI first)."""
    if quantity == "absolute_temperature":
        return TEMPERATURE_UNITS
    return tuple(_MULTIPLY[quantity])


def to_si(value: float, unit: str, quantity: str, field: str) -> float:
    """Convert one editor value to SI. Absolute temperature: (F - 32) * 5/9; a difference or a rate: F * 5/9."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}: value must be a finite number")
    kind = FIELD_KIND[field]
    if quantity == "absolute_temperature":
        if unit == "degC":
            return float(value)
        if unit != "degF":
            raise ValueError(f"{field}: unit {unit!r} is not a temperature unit (degC, degF)")
        return (value - 32.0) * 5.0 / 9.0 if kind == "absolute" else value * 5.0 / 9.0
    factors = _MULTIPLY.get(quantity) or {}
    if unit not in factors:
        raise ValueError(f"{field}: unit {unit!r} not accepted for {quantity} ({', '.join(factors)})")
    return value * factors[unit]


def from_si(value: float, unit: str, quantity: str, field: str) -> float:
    """Inverse of :func:`to_si` (what the editor shows)."""
    kind = FIELD_KIND[field]
    if quantity == "absolute_temperature":
        if unit == "degC":
            return float(value)
        return value * 9.0 / 5.0 + 32.0 if kind == "absolute" else value * 9.0 / 5.0
    return value / _MULTIPLY[quantity][unit]


def equipment_scope(equipment_id: str) -> str:
    if not isinstance(equipment_id, str) or not equipment_id:
        raise ValueError("equipment id is required for an equipment scope")
    return EQUIP_SCOPE_PREFIX + equipment_id


def shipped_document() -> dict:
    return json.loads(_cat._LIMITS_FILE.read_text(encoding="utf-8"))


def normalize_override(params: Any, shipped: Mapping | None = None) -> dict:
    """Validate the shape of one override document and return it normalized (SI floats). Unknown roles or fields,
    non-finite numbers or a wrong version are rejected. An empty ``roles`` map is a reset to the scope below."""
    if not isinstance(params, Mapping) or params.get("version") != OVERRIDE_VERSION:
        raise ValueError(f"override: version must be {OVERRIDE_VERSION}")
    roles = params.get("roles")
    if not isinstance(roles, Mapping):
        raise ValueError("override: roles must be an object")
    known = {e["role"]: e for e in (shipped or shipped_document())["roles"]}
    out: dict[str, dict[str, float]] = {}
    for role, fields in roles.items():
        if role not in known:
            raise ValueError(f"override: unknown role {role!r}")
        if not isinstance(fields, Mapping) or not fields:
            raise ValueError(f"override: {role} needs at least one field")
        out[role] = {}
        for field, value in fields.items():
            if field not in FIELD_KIND:
                raise ValueError(f"override: {role}.{field} is not editable ({', '.join(FIELD_KIND)})")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"override: {role}.{field} must be a finite SI number")
            out[role][field] = float(value)
    doc = {"version": OVERRIDE_VERSION, "roles": out}
    for key in ("note", "reset", "rollback_of"):
        if key in params:
            doc[key] = params[key]
    return doc


def merge(shipped: Mapping | None = None, site: Mapping | None = None, equipment: Mapping | None = None,
          revisions: Mapping[str, int | None] | None = None) -> tuple[dict, dict]:
    """(document, sources): the shipped role-limit document with the site, then the equipment override applied,
    and per role per field which layer it came from ('shipped' | 'site' | 'equipment'). Not validated yet."""
    base = copy.deepcopy(dict(shipped or shipped_document()))
    revisions = revisions or {}
    sources: dict[str, dict[str, str]] = {e["role"]: {f: "shipped" for f in FIELD_KIND} for e in base["roles"]}
    by_role = {e["role"]: e for e in base["roles"]}
    for layer, override in (("site", site), ("equipment", equipment)):
        if not override:
            continue
        doc = normalize_override(override, base)
        rev = revisions.get(layer)
        for role, fields in doc["roles"].items():
            entry = by_role[role]
            for field, value in fields.items():
                entry[field] = value
                sources[role][field] = layer
            entry["source"] = f"{layer} override" + (f" revision {rev}" if rev is not None else "")
    return base, sources


def effective_role_limits(shipped: Mapping | None = None, site: Mapping | None = None, equipment: Mapping | None = None) -> dict:
    """The validated limits (a ``load_role_limits`` result) for ``render_rule.render(..., role_limits=...)``.
    Raises ValueError when the merge is invalid (e.g. lo >= hi, a non-positive tolerance)."""
    doc, _ = merge(shipped, site, equipment)
    return _cat.load_role_limits(doc)


def config_hash(site: Mapping | None = None, equipment: Mapping | None = None) -> str:
    """sha256 of the overrides in effect (canonical JSON of their roles); '' when none (the shipped limits)."""
    layers = {k: dict(v.get("roles") or {}) for k, v in (("site", site), ("equipment", equipment)) if v and v.get("roles")}
    if not layers:
        return ""
    return hashlib.sha256(json.dumps(layers, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---- fdd.rule_config storage (any DB-API 2 cursor with %s parameters, e.g. psycopg) ------------------------------

def active_overrides(cur, site_id: str) -> dict[str, dict]:
    """{scope_key: {"revision", "parameters"}} of the active SV-LIMITS revisions of a site."""
    cur.execute("SELECT scope_key, revision, parameters FROM fdd.rule_config WHERE site_id = %s AND rule_id = %s AND active",
                (site_id, LIMITS_RULE_ID))
    out = {}
    for scope, rev, params in cur.fetchall():
        out[scope] = {"revision": int(rev), "parameters": params if isinstance(params, dict) else json.loads(params)}
    return out


def save_override(cur, site_id: str, scope_key: str, params: Mapping, created_by: str, *, equipment_base: Mapping | None = None) -> int:
    """Validate (merged with the shipped limits and, for an equipment scope, the active site override) and append a
    new active revision. Returns the revision. The caller commits (one transaction)."""
    if scope_key != SITE_SCOPE and not scope_key.startswith(EQUIP_SCOPE_PREFIX):
        raise ValueError(f"scope_key must be {SITE_SCOPE!r} or {EQUIP_SCOPE_PREFIX}<equipment id>")
    doc = normalize_override(params)
    active = active_overrides(cur, site_id)
    site = doc if scope_key == SITE_SCOPE else (active.get(SITE_SCOPE) or {}).get("parameters")
    effective_role_limits(None, site, None if scope_key == SITE_SCOPE else doc)    # raises before anything is written
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{site_id}|{LIMITS_RULE_ID}|{scope_key}",))
    cur.execute("SELECT coalesce(max(revision), 0) + 1 FROM fdd.rule_config WHERE site_id = %s AND rule_id = %s AND scope_key = %s",
                (site_id, LIMITS_RULE_ID, scope_key))
    rev = int(cur.fetchone()[0])
    cur.execute("UPDATE fdd.rule_config SET active = false WHERE site_id = %s AND rule_id = %s AND scope_key = %s AND active",
                (site_id, LIMITS_RULE_ID, scope_key))
    cur.execute("INSERT INTO fdd.rule_config (site_id, rule_id, scope_key, revision, parameters, active, created_by) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, true, %s)",
                (site_id, LIMITS_RULE_ID, scope_key, rev, json.dumps(doc), created_by))
    return rev


def reset_override(cur, site_id: str, scope_key: str, created_by: str) -> int:
    """Back to the layer below (shipped, or the site for an equipment scope): an empty active revision (audited)."""
    return save_override(cur, site_id, scope_key, {"version": OVERRIDE_VERSION, "roles": {}, "reset": True}, created_by)


def rollback_override(cur, site_id: str, scope_key: str, revision: int, created_by: str) -> int:
    """Re-activate an earlier revision's parameters as a NEW revision (history stays append-only)."""
    cur.execute("SELECT parameters FROM fdd.rule_config WHERE site_id = %s AND rule_id = %s AND scope_key = %s AND revision = %s",
                (site_id, LIMITS_RULE_ID, scope_key, int(revision)))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no revision {revision} for {scope_key}")
    params = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    params = {k: v for k, v in params.items() if k not in ("reset", "rollback_of")}
    return save_override(cur, site_id, scope_key, {**params, "rollback_of": int(revision)}, created_by)
