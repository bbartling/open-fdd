"""Haystack model from NF, role binding and SI equipment frames for the pandas rules.

Mirrors the NF app so a pandas run and the app's SQL run see the same inputs:

  * ``load_model``      = ``nf-app/static/model.js`` ``loadModel`` (model layer entities, then every
                          point of each site from the default layer, merged tags + latest value)
  * ``bind_equipment``  = ``nf-app/static/fdd.js`` ``bindRoles`` / ``equipPool`` / ``roleScore``
                          (site scoped; weather points only fill ``web_*`` roles; a class match
                          ranks before a marker match)
  * ``equipment_frames``= ``nf-app/hooks/fdd.js`` ``siPlan`` (SI by unit, percent -> fraction for
                          fraction roles, booleans 0/1, unitless fraction roles skipped)

Nothing site-specific lives here: sites, equipment, points and units all come from NF.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from open_fdd.nf.client import NFClient, NFError
from open_fdd.nf.units import quantity_of, si_unit_of, to_si

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GENERIC = {"point", "his", "cur", "writable"}
ENTITY_TYPES = ("SITE", "EQUIPMENT", "DEVICE")
STRICT_QUANTITY = ("temperature", "pressure", "flow")
FRACTION_UNIT = re.compile(r"^(ratio|fraction|frac|0-1|0\.\.1|0 to 1|unitless ratio)$", re.I)

# Catalog equipment kind -> equipment stamp the pandas rules understand.
KIND_STAMP = {
    "vav": "VAV", "ahu": "AHU", "chiller": "CHILLER", "chwPlant": "CHW_PLANT",
    "cooling_tower": "COOLING_TOWER", "boiler": "BOILER", "heatpump": "HP", "meter": "METER",
    "baseboard": "ZONE_OTHER", "zone_other": "ZONE_OTHER", "weather": "WEATHER", "general": "GENERAL",
}


# ---------------------------------------------------------------------------- data files
@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """``fdd-catalog.json`` shipped in the package (copy of ``nf-app/static/fdd-catalog.json``)."""
    return json.loads((DATA_DIR / "fdd-catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def role_scales() -> dict[str, str]:
    """``role_scales.json``: SQL role -> ``fraction | boolean | percent_rh | text | si:<unit>``."""
    return json.loads((DATA_DIR / "role_scales.json").read_text(encoding="utf-8"))["roles"]


@lru_cache(maxsize=1)
def role_columns() -> dict[str, str]:
    """``role_map.json``: SQL role -> the Haystack column name the pandas rules read."""
    return json.loads((DATA_DIR / "role_map.json").read_text(encoding="utf-8"))


def column_for(role: str) -> str:
    """Pandas column for a SQL role (web weather roles map to ``web-outside-air-*``; else the role name)."""
    extra = {"web_oa_t": "web-outside-air-temp", "web_oa_dp": "web-outside-air-dewpoint",
             "web_wb_t": "web-outside-air-wetbulb", "web_oa_h": "web-outside-air-humidity"}
    return role_columns().get(role) or extra.get(role) or role


# ---------------------------------------------------------------------------- model
@dataclass
class Point:
    uuid: str
    name: str
    dis: str
    tags: list[str]
    unit: str
    kind: str
    equip_ref: str
    site_ref: str
    weather_ref: str
    device_ref: str
    cls: str
    latest: dict | None
    rec: dict = field(repr=False, default_factory=dict)

    def has(self, *markers: str) -> bool:
        return all(m in self.tags for m in markers)


@dataclass
class Model:
    sites: list[dict]
    equips: list[dict]
    devices: list[dict]
    points: list[Point]


def id_of(rec: Mapping[str, Any]) -> str:
    return (rec.get("attrs") or {}).get("id") or rec.get("name") or ""


def markers_of(rec: Mapping[str, Any]) -> list[str]:
    return [m for m in ((rec.get("attrs") or {}).get("markers") or "").split(",") if m]


def to_point(rec: Mapping[str, Any]) -> Point:
    a = rec.get("attrs") or {}
    tags = markers_of(rec)
    return Point(
        uuid=rec.get("uuid", ""),
        name=" ".join(t for t in tags if t not in GENERIC and t != "sensor") or rec.get("name", ""),
        dis=a.get("dis") or rec.get("name", ""),
        tags=tags,
        unit=a.get("unit", ""),
        kind=a.get("kind") or "Number",
        equip_ref=a.get("equipRef", ""),
        site_ref=a.get("siteRef", ""),
        weather_ref=a.get("weatherStationRef", ""),
        device_ref=a.get("deviceRef", ""),
        cls=a.get("class", ""),
        latest=rec.get("latestValue"),
        rec=dict(rec),
    )


def load_model(client: NFClient) -> Model:
    """Sites, equipment, devices (model layer) and every point of each site (default layer)."""
    recs = client.query_all("model")
    of = lambda t: [r for r in recs if r.get("pointType") == t]  # noqa: E731
    sites, equips, devices = of("SITE"), of("EQUIPMENT"), of("DEVICE")
    if not sites:
        raise NFError("no Haystack site in this NF's model layer; tag the site, equipment and points first")
    points: list[Point] = []
    for s in sites:
        recs_s = client.query_all("default", {"field": {"property": "siteRef", "text": id_of(s)}})
        points.extend(to_point(r) for r in recs_s if r.get("pointType") not in ENTITY_TYPES)
    return Model(sites, equips, devices, points)


def site_name(model: Model, site_id: str) -> str:
    for s in model.sites:
        if id_of(s) == site_id:
            return (s.get("attrs") or {}).get("dis") or s.get("name") or site_id
    return site_id


# ---------------------------------------------------------------------------- binding
def equip_kinds(equip: Mapping[str, Any], catalog: Mapping | None = None) -> list[str]:
    cat = catalog or load_catalog()
    ms = set(markers_of(equip))
    return [k for k, marks in cat["equipment_kinds"].items() if any(m in ms for m in marks)]


def _is_web(role: str) -> bool:
    return role.startswith("web_")


def role_score(p: Point, role: str, definition: Mapping) -> int:
    """How well ``p`` fills ``role`` (0 = not at all): class match 2, all markers 1."""
    if _is_web(role) != p.has("weather"):
        return 0
    if p.cls and p.cls in definition["classes"]:
        return 2
    marks = definition["markers"]
    return 1 if marks and all(m in p.tags for m in marks) else 0


def bind_roles(roles: Iterable[str], pool: list[Point], catalog: Mapping | None = None) -> dict[str, list[Point]]:
    """Points of ``pool`` that fill each role, best first (class before markers, then by name)."""
    cat = catalog or load_catalog()
    out: dict[str, list[Point]] = {}
    for role in roles:
        d = cat["roles"].get(role)
        scored = [] if not d else [(role_score(p, role, d), p) for p in pool]
        out[role] = [p for s, p in sorted(((s, p) for s, p in scored if s > 0),
                                          key=lambda sp: (-sp[0], sp[1].name))]
    return out


def equip_pool(equip: Mapping[str, Any], model: Model) -> list[Point]:
    """An equip's tagged points plus its site's weather points. Never crosses sites (equip ids are
    only unique within a site)."""
    eid = id_of(equip)
    site = (equip.get("attrs") or {}).get("siteRef", "")
    return [p for p in model.points
            if p.has("point") and (not site or p.site_ref == site) and (p.equip_ref == eid or p.has("weather"))]


def roles_for_kinds(kinds: Iterable[str], catalog: Mapping | None = None) -> list[str]:
    """Every role a rule applicable to these equipment kinds reads (required + optional)."""
    cat = catalog or load_catalog()
    ks = set(kinds)
    seen: dict[str, None] = {}
    for rule in cat["rules"]:
        rk = rule.get("equipment_kinds") or []
        if rk and not (ks & set(rk)):
            continue
        for r in [*rule.get("required_roles", []), *rule.get("optional_roles", [])]:
            seen.setdefault(r, None)
    return list(seen)


@dataclass
class EquipBinding:
    site: str
    equip: str
    dis: str
    kinds: list[str]
    equip_rec: dict = field(repr=False)
    roles: dict[str, list[Point]]  # only roles with at least one candidate

    @property
    def stamp(self) -> str:
        for k in KIND_STAMP:
            if k in self.kinds:
                return KIND_STAMP[k]
        return ""

    def best(self) -> dict[str, Point]:
        return {r: pts[0] for r, pts in self.roles.items() if pts}


def bind_equipment(model: Model, roles: Iterable[str] | None = None, site: str | None = None,
                   equip: str | None = None, catalog: Mapping | None = None) -> list[EquipBinding]:
    """Bind roles for every equip (optionally one site / one equip, matched on id or display name)."""
    cat = catalog or load_catalog()
    want_roles = list(roles) if roles else None
    out: list[EquipBinding] = []
    for e in model.equips:
        a = e.get("attrs") or {}
        e_site = a.get("siteRef", "")
        if site and site not in (e_site, site_name(model, e_site)):
            continue
        if equip and equip.lower() not in (id_of(e).lower(), str(a.get("dis") or e.get("name") or "").lower()):
            continue
        kinds = equip_kinds(e, cat)
        candidate_roles = want_roles or roles_for_kinds(kinds, cat)
        bound = bind_roles(candidate_roles, equip_pool(e, model), cat)
        out.append(EquipBinding(e_site, id_of(e), a.get("dis") or e.get("name") or id_of(e), kinds, e,
                                {r: pts for r, pts in bound.items() if pts}))
    return out


# ---------------------------------------------------------------------------- SI plan
def role_quantity(role: str, catalog: Mapping | None = None) -> str | None:
    cat = catalog or load_catalog()
    name = str((cat["roles"].get(role) or {}).get("name") or role)
    if re.search(r"request|count", name):
        return None
    if re.search(r"temp|dewpoint|wetbulb", name):
        return "temperature"
    if "pressure" in name:
        return "pressure"
    if re.search(r"airflow|(^|-)flow($|-)", name):
        return "flow"
    return None


@dataclass
class RolePlan:
    convert: Callable[[Any], Any] | None  # vectorised over a pandas Series; None = role skipped
    unit: str
    reason: str = ""
    scaled: bool = False


def si_plan_for(role: str, p: Point, catalog: Mapping | None = None) -> RolePlan:
    """Port of ``siPlan`` in ``nf-app/hooks/fdd.js`` for one bound role."""
    unit = p.unit or ""
    probe = to_si(1, unit)
    scale = role_scales().get(role) or (load_catalog()["roles"].get(role) or {}).get("scale")
    is_bool = bool(re.match(r"^bool", p.kind or "", re.I))
    skip = lambda why: RolePlan(None, unit, why)  # noqa: E731
    if scale in ("fraction", "boolean"):
        pct = bool(probe) and probe.quantity == "percent" and not re.search("rh", unit, re.I)
        if scale == "fraction":
            if is_bool or FRACTION_UNIT.match(unit):
                return RolePlan(lambda s: s, "fraction")
            if pct:
                return RolePlan(lambda s: s / 100.0, "fraction", scaled=True)
            return skip(f'is a fraction 0-1 but unit "{unit}" is not a percent or fraction' if unit
                        else "is a fraction 0-1 but its point has no unit (0-100 or 0-1 cannot be told apart)")
        if probe and not pct and not FRACTION_UNIT.match(unit):
            return skip(f'is a 0/1 status but unit "{unit}" is a {probe.quantity}')
        div = (not is_bool) and pct

        def to_bool(s, div=div):
            x = s / 100.0 if div else s
            return x.where((x >= -1e-9) & (x <= 1 + 1e-9)).clip(0.0, 1.0)

        return RolePlan(to_bool, "bool", scaled=div)
    if scale == "text":
        return skip("is a text role; numeric history cannot feed it")
    want = role_quantity(role, catalog)
    if probe:
        if want and probe.quantity != want:
            return skip(f'is a {want} but unit "{unit}" is a {probe.quantity}')
        from open_fdd.nf.units import convert_series
        return RolePlan(lambda s, u=unit: convert_series(s, u)[0], probe.unit)
    if want in STRICT_QUANTITY:
        return skip(f"({want}) has " + (f'unknown unit "{unit}"' if unit else "no unit"))
    return RolePlan(lambda s: s, unit)


# ---------------------------------------------------------------------------- frames
def _frame_scope(model: Model, roles, site, equip) -> list[EquipBinding]:
    return [b for b in bind_equipment(model, roles=roles, site=site, equip=equip) if b.roles]


def equipment_frames(
    client: NFClient,
    model: Model,
    start: datetime,
    end: datetime,
    window_sec: int = 300,
    roles: Iterable[str] | None = None,
    site: str | None = None,
    equip: str | None = None,
) -> dict[tuple[str, str], "Any"]:
    """``{(site_id, equip_id): DataFrame}`` ready for ``open_fdd.rules``.

    * UTC DatetimeIndex, one column per bound role (pandas Haystack name, e.g. ``discharge-air-temp``)
    * values in SI, scaled per the role's declared scale
    * ``df.attrs``: ``equipment_id``, ``site_id``, ``equipment_type`` (stamp), ``role_units``
      (column -> unit), ``bindings`` (column -> {role, uuid, name, unit, source_unit, class}),
      ``skipped`` (role -> reason), ``window_sec``
    Equipment with no usable data in the range is left out.
    """
    import pandas as pd

    scope = _frame_scope(model, roles, site, equip)
    uuids: list[str] = []
    for b in scope:
        uuids.extend(p.uuid for p in b.best().values())
    data = client.point_data(sorted(set(uuids)), start, end, window_sec=window_sec) if uuids else {}
    out: dict[tuple[str, str], pd.DataFrame] = {}
    for b in scope:
        cols: dict[str, Any] = {}
        bindings: dict[str, dict] = {}
        units: dict[str, str] = {}
        skipped: dict[str, str] = {}
        for role, p in b.best().items():
            samples = data.get(p.uuid) or []
            if not samples:
                skipped[role] = "no history in the requested range"
                continue
            plan = si_plan_for(role, p)
            if plan.convert is None:
                skipped[role] = plan.reason
                continue
            col = column_for(role)
            if col in cols:
                continue
            idx = pd.DatetimeIndex([t for t, _ in samples], tz="UTC")
            series = pd.Series([v for _, v in samples], index=idx, dtype="float64")
            cols[col] = plan.convert(series)
            units[col] = plan.unit
            bindings[col] = {"role": role, "uuid": p.uuid, "name": p.dis, "unit": plan.unit,
                             "source_unit": p.unit, "class": p.cls}
        if not cols:
            continue
        df = pd.DataFrame(cols).sort_index()
        df.index.name = "timestamp_utc"
        df.attrs.update({
            "equipment_id": b.equip, "site_id": b.site, "equipment_type": b.stamp,
            "role_units": units, "bindings": bindings, "skipped": skipped, "window_sec": window_sec,
            "equipment_name": b.dis,
        })
        out[(b.site, b.equip)] = df
    return out


def default_range(days: float, now: datetime | None = None) -> tuple[datetime, datetime]:
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    return end - timedelta(days=days), end


def model_summary(model: Model, bindings: list[EquipBinding] | None = None) -> list[dict]:
    """Plain dicts: one per equip with its kinds and the point bound to each role."""
    out = []
    for b in bindings if bindings is not None else bind_equipment(model):
        best = b.best()
        out.append({
            "site": b.site, "equip": b.equip, "dis": b.dis, "kinds": b.kinds, "type": b.stamp,
            "roles": {r: {"column": column_for(r), "point": p.dis, "uuid": p.uuid, "unit": p.unit,
                          "scale": role_scales().get(r, "")} for r, p in best.items()},
        })
    return out
