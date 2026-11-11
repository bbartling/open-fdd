"""Plot spec v1: which series and fault strips a plot shows, chosen from the Haystack model only.

Open-FDD owns plot *selection*; every app owns only *rendering*. ``build_rule_spec`` and
``build_preset_spec`` return a plain dict (see ``open_fdd/data/plot_spec.schema.json``) that names points,
never values. A renderer fetches values for ``point_uuid`` + ``window`` and draws them in SI, converting for
display only (``open_fdd/data/units.json``). The JS twin ``nf-app/static/plot-spec.js`` emits the same bytes
for the same model (``to_json``), which the golden tests pin.

Selection follows the NF app's binding (``nf-app/static/fdd.js``): a point fills a catalog role when its NF
class is listed for the role (score 2) or it carries every marker of the role (score 1); weather points fill
only ``web_*`` roles. No point names, name regexes or role-to-key maps are used. Rule ids may be matched by
family (``SV-*`` sweeps, ``ECON-*``) because rule ids are part of the contract, not site data.

Model shape (the same one ``nf-app/static/model.js`` builds)::

    {"sites":  [{"uuid", "name", "attrs": {"id", "dis", "markers", "tz"?}}],
     "equips": [{"uuid", "name", "attrs": {"id", "dis", "markers", "siteRef"}}],
     "points": [{"uuid", "tags": [...], "dis", "units", "kind", "name", "equipRef", "siteRef", "cls",
                 "rec": {"attrs": {...}}}]}
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

SPEC_VERSION = 1
DATA_DIR = Path(__file__).resolve().parent / "data"

# Markers every point carries; left out of the spec's tags and of the sort name (model.js GENERIC).
GENERIC_MARKERS = frozenset({"point", "his", "cur", "writable"})
# Catalog roles that only weather points fill start with this prefix (fdd.js isWebRole).
WEB_ROLE_PREFIX = "web_"
# Rule-id families (rule ids are part of the contract): per-sensor sweeps and economizer rules.
SWEEP_RULE_PATTERN = r"^SV-(RATE|RANGE|FLATLINE|SPIKE|STALE)$"
ECON_RULE_PATTERN = r"^ECON-[1-7]$"
_SWEEP_RULE = re.compile(SWEEP_RULE_PATTERN)
_ECON_RULE = re.compile(ECON_RULE_PATTERN)
ECON_EXTRA_ROLE = "oa_damper_pct"

NAV_SEPARATOR = " › "
COLOR_KEYS = 12
FALLBACK_TZ = "UTC"


# ---- data ------------------------------------------------------------------------------------------


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _catalog() -> dict[str, Any]:
    return _load("fdd-catalog.json")


@lru_cache(maxsize=None)
def _registry() -> dict[str, Any]:
    reg = _load("rcx_presets.json")
    by_id = {p["id"]: p for p in reg["presets"]}
    alias = {a: p["id"] for p in reg["presets"] for a in p.get("aliases", [])}
    return {"presets": reg["presets"], "by_id": by_id, "alias": alias}


@lru_cache(maxsize=None)
def _units() -> dict[str, Any]:
    doc = _load("units.json")
    index: dict[str, dict[str, Any]] = {}
    for row in doc["aliases"]:
        for name in row["names"]:
            index[norm_unit(name)] = row
    return {"doc": doc, "index": index}


def norm_unit(unit: Any) -> str:
    """Same normalisation as ``units.js``: trim, lower-case, drop whitespace and underscores."""
    s = "".join(str(unit or "").strip().lower().replace("_", "").split())
    return s.replace("₂", "2").replace("º", "°")


def preset_ids() -> list[str]:
    """Canonical preset ids in registry order."""
    return [p["id"] for p in _registry()["presets"]]


def resolve_preset_id(preset_id: str) -> str:
    """The canonical id for a canonical id or an old alias; ``ValueError`` when neither."""
    reg = _registry()
    if preset_id in reg["by_id"]:
        return preset_id
    if preset_id in reg["alias"]:
        return reg["alias"][preset_id]
    raise ValueError(f"unknown plot preset {preset_id!r}")


# ---- small helpers (ports of model.js / fdd.js) ---------------------------------------------------


def _attrs(rec: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return (rec or {}).get("attrs") or {}


def _id_of(rec: Mapping[str, Any]) -> str:
    return _attrs(rec).get("id") or rec.get("name") or ""


def _markers_of(rec: Mapping[str, Any]) -> list[str]:
    return [m for m in str(_attrs(rec).get("markers") or "").split(",") if m]


def _has(p: Mapping[str, Any], *markers: str) -> bool:
    tags = p.get("tags") or []
    return all(m in tags for m in markers)


def _equip_kinds(equip_rec: Mapping[str, Any], catalog: Mapping[str, Any]) -> list[str]:
    markers = set(_markers_of(equip_rec))
    return [kind for kind, ms in catalog["equipment_kinds"].items() if any(m in markers for m in ms)]


def _is_web_role(role: str) -> bool:
    return role.startswith(WEB_ROLE_PREFIX)


def _role_score(p: Mapping[str, Any], role: str, definition: Mapping[str, Any]) -> int:
    """How well point ``p`` fills ``role``: 2 NF class, 1 marker set, 0 not at all (fdd.js roleScore)."""
    if _is_web_role(role) != _has(p, "weather"):
        return 0
    if p.get("cls") and p["cls"] in definition["classes"]:
        return 2
    markers = definition["markers"]
    return 1 if markers and all(m in (p.get("tags") or []) for m in markers) else 0


def _point_order(scored: tuple[int, Mapping[str, Any]]) -> tuple[int, str, str]:
    # Best match first, then code-point order of the name and the uuid (deterministic; no locale).
    return (-scored[0], str(scored[1].get("name") or ""), str(scored[1].get("uuid") or ""))


def _bind_roles(roles: Iterable[str], pool: list[Mapping[str, Any]], catalog: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for role in roles:
        definition = catalog["roles"].get(role)
        if not definition:
            out[role] = []
            continue
        scored = [(_role_score(p, role, definition), p) for p in pool]
        out[role] = [p for _, p in sorted((s for s in scored if s[0] > 0), key=_point_order)]
    return out


def _equip_pool(equip_rec: Mapping[str, Any], model: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Points an equip's roles may bind to: its own tagged points plus its site's weather points."""
    eid = _id_of(equip_rec)
    site_ref = _attrs(equip_rec).get("siteRef")
    return [
        p for p in model["points"]
        if _has(p, "point") and (not site_ref or p.get("siteRef") == site_ref)
        and (p.get("equipRef") == eid or _has(p, "weather"))
    ]


def _marker_points(selector: Mapping[str, Any], equip_rec: Mapping[str, Any], model: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Points of this equip (never weather) that carry the selector's markers: all of ``markers``, one of ``any_of``, none of ``exclude``."""
    eid = _id_of(equip_rec)
    site_ref = _attrs(equip_rec).get("siteRef")
    any_of, exclude = selector.get("any_of") or [], selector.get("exclude") or []
    found = [
        p for p in model["points"]
        if _has(p, "point") and p.get("equipRef") == eid and (not site_ref or p.get("siteRef") == site_ref)
        and _has(p, *selector["markers"]) and (not any_of or any(_has(p, m) for m in any_of))
        and not any(_has(p, m) for m in exclude)
    ]
    return [p for _, p in sorted(((1, p) for p in found), key=_point_order)]


def _find_site(model: Mapping[str, Any], site_ref: str | None) -> Mapping[str, Any] | None:
    sites = model.get("sites") or []
    for s in sites:
        if _id_of(s) == site_ref:
            return s
    return sites[0] if len(sites) == 1 and not site_ref else None


def _resolve_equip(model: Mapping[str, Any], equip: Any) -> Mapping[str, Any]:
    if isinstance(equip, Mapping):
        return equip
    found = [e for e in model.get("equips") or [] if e.get("uuid") == equip]
    if not found:
        found = [e for e in model.get("equips") or [] if _id_of(e) == equip]
    if len(found) != 1:
        raise ValueError(f"equip {equip!r} matches {len(found)} records in the model; pass the equip record or its uuid")
    return found[0]


# ---- window, site, ids -----------------------------------------------------------------------------


def _iso_utc(value: Any) -> str:
    """ISO-8601 UTC with a Z; milliseconds only when non-zero. Accepts datetime, epoch ms, or an ISO string (no zone = UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    else:
        text = str(value).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{ms:03d}" if ms else "") + "Z"


def _window(window: Mapping[str, Any]) -> dict[str, str]:
    start, end = _iso_utc(window["from"]), _iso_utc(window["to"])
    if end < start:
        raise ValueError("window.to is before window.from")
    return {"from": start, "to": end}


def _site_block(model: Mapping[str, Any], equip_rec: Mapping[str, Any], tz: str | None) -> dict[str, str]:
    site_ref = _attrs(equip_rec).get("siteRef") or ""
    site = _find_site(model, site_ref)
    own = (_attrs(site).get("tz") or _attrs(site).get("timezone")) if site else None
    if own:
        zone, source = own, "model"
    elif tz:
        zone, source = tz, "option"
    else:
        zone, source = FALLBACK_TZ, "fallback"
    return {"ref": site_ref or (_id_of(site) if site else ""), "tz": zone, "tz_source": source}


def color_key(point_uuid: str) -> int:
    """FNV-1a 32-bit of the UTF-8 bytes of the point uuid, modulo 12: stable across reloads, apps and windows."""
    h = 0x811C9DC5
    for byte in str(point_uuid).encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h % COLOR_KEYS


# ---- units -----------------------------------------------------------------------------------------


def _quantity_for(p: Mapping[str, Any], role_def: Mapping[str, Any] | None) -> str | None:
    """The quantity of a point from its declared unit (units.json), refined by its markers; ``None`` = unit unusable."""
    units = _units()
    doc = units["doc"]
    unit = p.get("units") or ""
    if unit:
        row = units["index"].get(norm_unit(unit))
        if row is None:
            return None
        quantity = row["quantity"]
        refine = doc["refine"].get(quantity)
        if refine:
            quantity = refine["yes"] if _has(p, refine["marker"]) else refine["no"]
        return quantity
    if p.get("kind") == "Bool":
        return "boolean"
    scale = (role_def or {}).get("scale")
    return doc["role_scales"].get(scale) if scale else None


def _series_kind(p: Mapping[str, Any], role_def: Mapping[str, Any] | None) -> str:
    if _has(p, "weather"):
        return "weather"
    if _has(p, "sp"):
        return "sp"
    if _has(p, "cmd"):
        return "cmd"
    if p.get("kind") == "Bool" or _has(p, "status") or (role_def or {}).get("scale") == "boolean":
        return "status"
    return "sensor"


def _series_row(p: Mapping[str, Any], role: str, role_def: Mapping[str, Any] | None, equip_rec: Mapping[str, Any] | None,
                site_dis: str, required: bool) -> dict[str, Any] | None:
    quantity = _quantity_for(p, role_def)
    if quantity is None:
        return None
    q = _units()["doc"]["quantities"][quantity]
    kind = _series_kind(p, role_def)
    owner = None if kind == "weather" or equip_rec is None else equip_rec
    # Weather points belong to the site, not to one equip: no equip_uuid, navigated under the site.
    owner_dis = site_dis if owner is None else (_attrs(owner).get("dis") or owner.get("name") or "")
    return {
        "point_uuid": p["uuid"],
        "equip_uuid": None if owner is None else owner["uuid"],
        "role": role,
        "dis": p.get("dis") or "",
        "nav": f"{owner_dis}{NAV_SEPARATOR}{p.get('dis') or ''}",
        "tags": [t for t in (p.get("tags") or []) if t not in GENERIC_MARKERS],
        "class": p.get("cls") or None,
        "quantity": quantity,
        "unit_si": q["si"],
        "kind": kind,
        "axis": q["axis"],
        "color_key": color_key(p["uuid"]),
        "required": required,
    }


# ---- fault strips (ports of rcx.js rcxMatchRank / rcxBestPoint) ------------------------------------


def _equip_identity(equip_rec: Mapping[str, Any]) -> dict[str, str]:
    return {"id": _id_of(equip_rec), "site": _attrs(equip_rec).get("siteRef") or "", "uuid": equip_rec.get("uuid") or ""}


def _match_rank(p: Mapping[str, Any], who: Mapping[str, str], model: Mapping[str, Any]) -> int:
    """0 not this equip, 1 equipRef only (legacy), 2 equipRef + siteRef, 3 equip uuid."""
    if p.get("equipRef") != who["id"]:
        return 0
    a = _attrs(p.get("rec"))
    if who["uuid"] and a.get("equipUuid"):
        return 3 if a["equipUuid"] == who["uuid"] else 0
    if not who["site"]:
        return 1
    if p.get("siteRef"):
        return 2 if p["siteRef"] == who["site"] else 0
    return 1 if len([e for e in model.get("equips") or [] if _id_of(e) == who["id"]]) <= 1 else 0


def _best_point(model: Mapping[str, Any], equip_rec: Mapping[str, Any], rule_id: str, markers: list[str],
                sensor_ref: str | None) -> Mapping[str, Any] | None:
    who = _equip_identity(equip_rec)
    best, best_rank = None, 0
    for p in model["points"]:
        a = _attrs(p.get("rec"))
        if not _has(p, *markers) or (a.get("ruleRef") or "") != rule_id:
            continue
        if sensor_ref is not None and str(a.get("sensorRef") or "") != str(sensor_ref):
            continue
        if sensor_ref is None and a.get("sensorRef"):
            continue
        rank = _match_rank(p, who, model)
        if rank > best_rank:
            best, best_rank = p, rank
    return best


def _strip(model: Mapping[str, Any], equip_rec: Mapping[str, Any], rule_id: str, sensor_uuid: str | None) -> dict[str, Any]:
    timeline = _best_point(model, equip_rec, rule_id, ["fault_timeline"], sensor_uuid)
    if timeline:
        point_uuid, source, approximate = timeline["uuid"], "timeline", False
    else:
        result = _best_point(model, equip_rec, rule_id, ["fdd", "fault"], sensor_uuid)
        if result:
            point_uuid, source, approximate = result["uuid"], "fault_pct", True
        else:
            point_uuid, source, approximate = None, "intervals", False
    return {"rule_id": rule_id, "equip_uuid": equip_rec["uuid"], "point_uuid": point_uuid, "sensor_uuid": sensor_uuid,
            "source": source, "approximate": approximate}


def _sensor_result_points(model: Mapping[str, Any], equip_rec: Mapping[str, Any], rule_id: str) -> list[Mapping[str, Any]]:
    who = _equip_identity(equip_rec)
    out = []
    for p in model["points"]:
        a = _attrs(p.get("rec"))
        if (_has(p, "fdd", "fault") and (a.get("ruleRef") or "") == rule_id
                and (a.get("fddSummary") == "sensor" or a.get("sensorRef")) and _match_rank(p, who, model) > 0):
            out.append(p)
    return out


# ---- builders --------------------------------------------------------------------------------------


def _finish(kind: str, rule_id: str | None, preset_id: str | None, site: dict[str, str], equips: list[Mapping[str, Any]],
            window: dict[str, str], series: list[dict[str, Any]], strips: list[dict[str, Any]],
            missing: set[tuple[str, str]], reason: str, catalog: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "spec_version": SPEC_VERSION,
        "kind": kind,
        "rule_id": rule_id,
        "preset_id": preset_id,
        "site": site,
        "equip": [
            {"uuid": e["uuid"], "ref": _id_of(e), "dis": _attrs(e).get("dis") or e.get("name") or "",
             "kind": (_equip_kinds(e, catalog) or [""])[0]}
            for e in equips
        ],
        "window": window,
        "series": series,
        "fault_strips": strips,
        "missing": [{"role": role, "reason": reason_} for role, reason_ in sorted(missing)],
        "selection_reason": reason,
    }


def build_rule_spec(model: Mapping[str, Any], rule_id: str, equip: Any, window: Mapping[str, Any], *,
                    tz: str | None = None, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Plot spec for one FDD rule on one equip: the rule's catalog input roles plus its fault strip.

    Sweep rules (``SV-*``) plot every bound sensor with one strip per sensor; the sensors the hook assessed
    (result points carrying ``sensorRef``) are plotted too.
    """
    catalog = catalog or _catalog()
    rule = next((r for r in catalog["rules"] if r["id"] == rule_id), None)
    if rule is None:
        raise ValueError(f"unknown FDD rule {rule_id!r}")
    equip_rec = _resolve_equip(model, equip)
    site = _site_block(model, equip_rec, tz)
    win = _window(window)
    kinds = _equip_kinds(equip_rec, catalog)
    wanted_kinds = rule.get("equipment_kinds") or []
    if wanted_kinds and not any(k in kinds for k in wanted_kinds):
        reason = f"rule {rule_id} does not apply to equip kind {(kinds or ['none'])[0]}"
        return _finish("rule", rule_id, None, site, [equip_rec], win, [], [], set(), reason, catalog)

    required = list(dict.fromkeys(rule.get("required_roles") or []))
    optional = [r for r in dict.fromkeys(rule.get("optional_roles") or []) if r not in required]
    roles = required + optional
    pool = _equip_pool(equip_rec, model)
    bound = _bind_roles(roles + [ECON_EXTRA_ROLE], pool, catalog)
    if _ECON_RULE.fullmatch(str(rule_id).strip().upper()) and ECON_EXTRA_ROLE not in roles and bound[ECON_EXTRA_ROLE]:
        roles.append(ECON_EXTRA_ROLE)
    sweep = bool(_SWEEP_RULE.fullmatch(str(rule_id)))
    site_dis = _attrs(_find_site(model, site["ref"])).get("dis") or site["ref"]

    series: list[dict[str, Any]] = []
    seen: set[str] = set()
    missing: set[tuple[str, str]] = set()

    def add(p: Mapping[str, Any], role: str, is_required: bool) -> None:
        if p["uuid"] in seen:
            return
        seen.add(p["uuid"])
        row = _series_row(p, role, catalog["roles"].get(role), equip_rec, site_dis, is_required)
        if row is None:
            missing.add((role, "unit_unusable"))
        else:
            series.append(row)

    for role in roles:
        points = bound[role] if sweep else bound[role][:1]
        for p in points:
            add(p, role, role in required)
    if sweep:
        by_uuid = {p["uuid"]: p for p in model["points"] if _has(p, "point")}
        for result in _sensor_result_points(model, equip_rec, rule_id):
            a = _attrs(result.get("rec"))
            sensor = by_uuid.get(str(a.get("sensorRef") or ""))
            if sensor:
                add(sensor, a.get("roleRef") or "sensor", False)
    for role in required:
        if not bound[role]:
            missing.add((role, "unbound"))

    if sweep:
        strips = [_strip(model, equip_rec, rule_id, s["point_uuid"]) for s in series]
    else:
        strips = [_strip(model, equip_rec, rule_id, None)]
    bound_n = len([r for r in roles if bound[r]])
    reason = f"rule inputs {rule_id}: {bound_n} of {len(roles)} roles bound by class/markers"
    return _finish("rule", rule_id, None, site, [equip_rec], win, series, strips, missing, reason, catalog)


def build_preset_spec(model: Mapping[str, Any], preset_id: str, equips: Iterable[Any], window: Mapping[str, Any], *,
                      tz: str | None = None, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Plot spec for a registry preset over the given equips (all of one site; one spec per site).

    An equip qualifies when its kind matches the preset and every required selector is bound; the others are
    left out and their unbound required roles are listed in ``missing``. Fewer than ``min_equips`` qualifying
    equips gives an empty plot.
    """
    catalog = catalog or _catalog()
    canonical = resolve_preset_id(preset_id)
    preset = _registry()["by_id"][canonical]
    recs = sorted((_resolve_equip(model, e) for e in equips),
                  key=lambda e: (_attrs(e).get("dis") or e.get("name") or "", _id_of(e), e.get("uuid") or ""))
    if not recs:
        raise ValueError("build_preset_spec needs at least one equip")
    if len({_attrs(e).get("siteRef") or "" for e in recs}) > 1:
        raise ValueError("a plot spec covers one site: build one spec per site")
    site = _site_block(model, recs[0], tz)
    win = _window(window)
    site_dis = _attrs(_find_site(model, site["ref"])).get("dis") or site["ref"]
    kinds_wanted = preset["equip_kinds"]
    selectors = preset["series"]

    qualifying: list[tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], list[Mapping[str, Any]]]]]] = []
    missing: set[tuple[str, str]] = set()
    for rec in recs:
        kinds = _equip_kinds(rec, catalog)
        if kinds_wanted and not any(k in kinds for k in kinds_wanted):
            continue
        pool = _equip_pool(rec, model)
        bound = _bind_roles([s["role"] for s in selectors if "role" in s], pool, catalog)
        found = []
        unbound = []
        for sel in selectors:
            points = bound[sel["role"]] if "role" in sel else _marker_points(sel, rec, model)
            if sel["required"] and not points:
                unbound.append(sel["role"] if "role" in sel else "marker:" + ",".join(sel["markers"]))
            found.append((sel, points))
        skip = preset.get("skip_equip_if_bound") or []
        if unbound:
            missing.update((r, "unbound") for r in unbound)
            continue
        if any(bound.get(r) for r in skip):
            continue
        qualifying.append((rec, found))

    series: list[dict[str, Any]] = []
    strips: list[dict[str, Any]] = []
    used: list[Mapping[str, Any]] = []
    if len(qualifying) >= preset["min_equips"]:
        seen: set[str] = set()
        bound_selectors = 0
        for rec, found in qualifying:
            used.append(rec)
            for sel, points in found:
                if points:
                    bound_selectors += 1
                role = sel["role"] if "role" in sel else "marker:" + ",".join(sel["markers"])
                for p in (points if sel.get("multiple") else points[:1]):
                    if p["uuid"] in seen:
                        continue
                    seen.add(p["uuid"])
                    row = _series_row(p, role, catalog["roles"].get(sel.get("role")), rec, site_dis, bool(sel["required"]))
                    if row is None:
                        missing.add((role, "unit_unusable"))
                    else:
                        series.append(row)
            for rule_id in preset["fault_rules"]:
                strips.append(_strip(model, rec, rule_id, None))
        reason = (f"preset {canonical}: {len(qualifying)} of {len(recs)} equips qualify, "
                  f"{bound_selectors} of {len(qualifying) * len(selectors)} series selectors bound by class/markers")
    else:
        reason = (f"preset {canonical}: {len(qualifying)} of {len(recs)} equips qualify, "
                  f"fewer than the {preset['min_equips']} it needs")
    return _finish("preset", None, canonical, site, used, win, series, strips, missing, reason, catalog)


# ---- canonical JSON --------------------------------------------------------------------------------


def to_json(spec: Mapping[str, Any]) -> str:
    """Canonical JSON: sorted keys, no whitespace, non-ASCII kept. The JS producer emits the same bytes."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ = [
    "SPEC_VERSION", "build_rule_spec", "build_preset_spec", "color_key", "norm_unit", "preset_ids", "resolve_preset_id", "to_json",
]
