"""Point-role index loaded from ``roles/openfdd-roles.json`` (1.1.0-draft.1).

Setpoint pairing uses the vocabulary's role names, legacy keys, aliases and Haystack
class names. It does not guess from ``-sp`` or ``-setpoint`` suffixes.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ROLES_VERSION = "1.1.0-draft.1"
_SETPOINT_ASPECT = "s223:Aspect-Setpoint"


def roles_json_path() -> Path | None:
    """Locate the vocabulary file in the repo checkout (or ``OPENFDD_ROLES_JSON``)."""
    override = os.environ.get("OPENFDD_ROLES_JSON")
    if override:
        path = Path(override)
        if path.is_file():
            return path
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "roles" / "openfdd-roles.json"
        if candidate.is_file():
            return candidate
    return None


def _forms(value: str) -> set[str]:
    text = value.strip()
    if not text:
        return set()
    hyphen = text.replace("_", "-")
    under = text.replace("-", "_")
    return {text, text.lower(), hyphen, hyphen.lower(), under, under.lower()}


@lru_cache(maxsize=1)
def load_role_index() -> dict[str, Any]:
    """Return the parsed vocabulary, or an empty index when the file is absent."""
    path = roles_json_path()
    if path is None:
        return {"version": "", "by_role": {}, "by_id": {}, "order": ()}
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_role: dict[str, dict[str, Any]] = {}
    by_id: dict[str, str] = {}
    for rec in payload.get("roles") or []:
        name = str(rec.get("role") or "")
        if not name:
            continue
        by_role[name] = rec
        keys = {name}
        keys.update(str(k) for k in rec.get("legacy_keys") or [])
        keys.update(str(k) for k in rec.get("aliases") or [])
        hay = rec.get("haystack") or {}
        keys.update(str(k) for k in hay.get("classes") or [])
        for key in keys:
            for form in _forms(key):
                by_id.setdefault(form, name)
    return {
        "version": str(payload.get("version") or ""),
        "by_role": by_role,
        "by_id": by_id,
        "order": tuple(by_role),
    }


def canonical_role(point_id: str) -> str | None:
    """Map a point id, legacy key, alias, or Haystack class to a role name."""
    if not point_id:
        return None
    index = load_role_index()["by_id"]
    for form in _forms(point_id):
        hit = index.get(form)
        if hit:
            return hit
    return None


def _has_setpoint_aspect(rec: dict[str, Any]) -> bool:
    aspects = (rec.get("s223") or {}).get("aspects") or []
    return _SETPOINT_ASPECT in aspects


def is_setpoint_role(role_or_point_id: str) -> bool:
    role = canonical_role(role_or_point_id) or role_or_point_id
    rec = load_role_index()["by_role"].get(role)
    return bool(rec and _has_setpoint_aspect(rec))


def setpoint_role_for(point_id: str) -> str | None:
    """Role that is the Aspect-Setpoint partner of ``point_id``, when the vocabulary defines one."""
    role = canonical_role(point_id)
    if role is None or is_setpoint_role(role):
        return None
    partner = f"{role}_setpoint"
    rec = load_role_index()["by_role"].get(partner)
    if rec is None or not _has_setpoint_aspect(rec):
        return None
    return partner


def match_property_pattern(
    *,
    types: set[str],
    aspects: set[str],
    mediums: set[str],
    quantity_kinds: set[str],
    equip_types: set[str],
) -> str | None:
    """Match a 223P property description to one role. More specific patterns win."""
    from open_fdd.ontology_audit.terms import expand

    def has(values: set[str], curie: str | None) -> bool:
        if not curie:
            return True
        return curie in values or expand(curie) in values

    best: str | None = None
    best_score = -1
    for name, rec in load_role_index()["by_role"].items():
        spec = rec.get("s223") or {}
        if not has(types, spec.get("property_class")):
            continue
        needed = [*(spec.get("roles") or []), *(spec.get("aspects") or [])]
        if any(not has(aspects, item) for item in needed):
            continue
        prop_sp = any(item.endswith("Aspect-Setpoint") for item in aspects)
        role_sp = _SETPOINT_ASPECT in (spec.get("aspects") or [])
        if prop_sp != role_sp:
            continue
        if spec.get("medium") and not has(mediums, spec.get("medium")):
            continue
        if spec.get("quantity_kind") and not has(quantity_kinds, spec.get("quantity_kind")):
            continue
        applies = list(spec.get("applies_to") or [])
        if applies and equip_types and not any(has(equip_types, item) for item in applies):
            continue
        score = len(needed) + int(bool(spec.get("medium"))) + int(bool(spec.get("quantity_kind"))) + len(applies)
        if score > best_score:
            best_score = score
            best = name
    return best
