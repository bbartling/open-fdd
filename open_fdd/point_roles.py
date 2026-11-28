"""Canonical point roles (ASHRAE 223P) from ``roles/openfdd-roles.json``.

The vocabulary is the rule-input contract (version ``1.1.0-draft.1``). A rule input and the pandas
column are the role's ``role`` name. ``legacy_keys`` and ``aliases`` still resolve to that name.
The hyphenated columns the reference rules used before this migration (``discharge-air-temp``) live
in ``legacy_pandas_columns.json`` and still resolve; they are not the column the rules read.
:func:`pandas_column` maps a role, a legacy key or a hyphenated column onto the role name.
:func:`resolve` maps any of those onto the role name.

Haystack tag sets in the file are an optional overlay. The role itself is the 223P pattern.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

VERSION = "1.1.0-draft.1"
_ROLE_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def _packaged_copy() -> Path:
    return Path(__file__).resolve().parent / "data" / "openfdd-roles.json"


def roles_path() -> Path:
    """The vocabulary file: the repo copy when this checkout contains it, else the packaged copy."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "roles" / "openfdd-roles.json"
        if candidate.is_file() and (parent / "pyproject.toml").is_file():
            return candidate
    packaged = _packaged_copy()
    if packaged.is_file():
        return packaged
    raise FileNotFoundError("roles/openfdd-roles.json")


@lru_cache(maxsize=1)
def load_vocabulary() -> dict:
    """The roles document. Raises ``ValueError`` when it does not validate."""
    doc = json.loads(roles_path().read_text(encoding="utf-8"))
    problems = validate_vocabulary(doc)
    if problems:
        raise ValueError("openfdd-roles.json: " + "; ".join(problems))
    return doc


def validate_vocabulary(doc: dict | None = None) -> list[str]:
    """Problems with the vocabulary the package depends on (empty means it loads).

    The full schema, derivation and ontology checks stay in ``roles/validate_roles.py``.
    """
    if doc is None:
        doc = json.loads(roles_path().read_text(encoding="utf-8"))
    problems: list[str] = []
    if doc.get("version") != VERSION:
        problems.append(f"version {doc.get('version')!r} != {VERSION}")
    units = doc.get("units") or {}
    if not isinstance(units, dict) or not units:
        problems.append("units missing")
        units = {}
    wires: set[str] = set()
    for key, spec in units.items():
        if not isinstance(key, str) or not key.startswith("unit:") or not isinstance(spec, dict):
            problems.append(f"bad unit entry {key!r}")
            continue
        local = key.split(":", 1)[1]
        wire = spec.get("wire")
        if local != wire:
            problems.append(f"unit {key} wire {wire!r} != local name {local}")
        else:
            wires.add(local)
    roles = doc.get("roles")
    if not isinstance(roles, list) or not roles:
        problems.append("roles missing")
        return problems
    seen: set[str] = set()
    claimed: dict[str, str] = {}
    for rec in roles:
        if not isinstance(rec, dict):
            problems.append("role entry is not an object")
            continue
        name = rec.get("role")
        if not isinstance(name, str) or not _ROLE_NAME.match(name):
            problems.append(f"bad role name {name!r}")
            continue
        if name in seen:
            problems.append(f"duplicate role {name}")
        seen.add(name)
        unit = rec.get("unit")
        if unit is not None and unit not in units:
            problems.append(f"{name} unit {unit!r} is not in units")
        for bucket in ("legacy_keys", "aliases"):
            values = rec.get(bucket) or []
            if not isinstance(values, list):
                problems.append(f"{name} {bucket} is not a list")
                continue
            for value in values:
                if not isinstance(value, str) or not value or value == name:
                    problems.append(f"{name} {bucket} has {value!r}")
                    continue
                other = claimed.get(value)
                if other and other != name:
                    problems.append(f"{value!r} is claimed by {other} and {name}")
                claimed[value] = name
    return problems


def roles() -> dict[str, dict]:
    """``{role name: role object}``."""
    return {rec["role"]: rec for rec in load_vocabulary()["roles"]}


def role_names() -> tuple[str, ...]:
    """Role names in file order."""
    return tuple(rec["role"] for rec in load_vocabulary()["roles"])


def rule_input_names() -> tuple[str, ...]:
    """Roles the rules read (``rule_input`` is not false)."""
    return tuple(rec["role"] for rec in load_vocabulary()["roles"] if rec.get("rule_input", True))


def unit_local_names() -> tuple[str, ...]:
    """QUDT unit local names (``DEG_C``, not ``unit:DEG_C``), in file order."""
    names = []
    for key in load_vocabulary()["units"]:
        names.append(key.split(":", 1)[1])
    return tuple(names)


def unit_local_name(unit: str | None) -> str | None:
    """``unit:DEG_C`` -> ``DEG_C``. ``None`` stays ``None``."""
    if unit is None:
        return None
    if unit.startswith("unit:"):
        return unit.split(":", 1)[1]
    return unit


@lru_cache(maxsize=1)
def _role_map() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "data" / "role_map.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


@lru_cache(maxsize=1)
def _legacy_pandas() -> dict[str, str]:
    """Hyphenated pandas column from before the role-name migration -> role name."""
    path = Path(__file__).resolve().parent / "data" / "legacy_pandas_columns.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    """Every accepted spelling except the hyphenated pandas column -> role name."""
    index: dict[str, str] = {}
    for rec in load_vocabulary()["roles"]:
        name = rec["role"]
        index[name] = name
        for key in [*(rec.get("legacy_keys") or []), *(rec.get("aliases") or [])]:
            index.setdefault(str(key), name)
    return index


def resolve(name: str) -> str | None:
    """The role name for a role, a ``legacy_keys`` / ``aliases`` value, or a hyphenated pandas column.

    A name listed in ``ambiguous_legacy_names`` resolves only when it is itself a role
    (``cooling_valve_position`` is the feedback role). It does not resolve through an alias.
    An unknown name returns ``None``.
    """
    text = str(name).strip()
    if not text:
        return None
    by_role = {rec["role"]: rec for rec in load_vocabulary()["roles"]}
    ambiguous = load_vocabulary().get("ambiguous_legacy_names") or {}
    if text in ambiguous and text not in by_role:
        return None
    found = _alias_index().get(text)
    if found:
        if text in ambiguous and text != found:
            return None
        return found
    legacy = _legacy_pandas().get(text)
    if legacy:
        return legacy
    for sql_key, column in _role_map().items():
        if text == column:
            return _alias_index().get(sql_key)
    return None


def pandas_column(name: str) -> str:
    """Pandas column for a role, a legacy key or an older hyphenated column.

    The reference rules read the role name (``discharge_air_temperature``). ``sat`` and
    ``discharge-air-temp`` both resolve to that column.
    """
    text = str(name).strip()
    canon = resolve(text)
    return canon if canon else text


def accepted_names() -> set[str]:
    """Spellings :func:`resolve` accepts: role names, legacy keys, aliases and hyphenated columns."""
    names = set(_alias_index())
    names.update(_legacy_pandas())
    for sql_key, column in _role_map().items():
        if sql_key in _alias_index():
            names.add(column)
    return names


def clear_cache() -> None:
    """Drop cached loads (tests that swap the file)."""
    load_vocabulary.cache_clear()
    _role_map.cache_clear()
    _legacy_pandas.cache_clear()
    _alias_index.cache_clear()
