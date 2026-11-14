"""SPARQL data client: query the site model on an NF box, get trend data, run the pandas reference rules here.

Same workflow as a stand-alone SPARQL playground ("server = model + time series, laptop = fault math"), served by the
Open-FDD NF app itself (#1618):

    from open_fdd.nf import NFClient
    from open_fdd.nf.sparql_data import fetch_auto, frames, run_rules
    client = NFClient.from_env()
    answer = fetch_auto(client, open("ahu_points.rq").read(), start, end)     # Full: sparql-data hook; Lite: rdf + rdflib
    print(run_rules(frames(answer)))                                           # the same open_fdd.rules functions

* Full edition: the ``sparql-data`` hook runs the query (SELECT / ASK, read-only) and returns the matched points'
  history (NF point/data or Timescale), paged over points (200 a page) and time (``next_from``) on one model
  ``snapshot``.
* Lite (or ``mode="local"``): the ``rdf`` hook hands over the model Turtle in pages; the query runs here with rdflib
  (SELECT / ASK only, no SERVICE) and history comes from NF ``/api/v1/point/data`` through the read-only client.

``frames`` builds one SI DataFrame per equipment exactly like ``open_fdd.nf.model.equipment_frames`` (same SI plan,
column names and attrs). A point's role comes from the query's ``?role`` column, else its ``ofddRole`` attribute, else
the catalog binding (NF class, then markers). No fault math lives here: ``run_rules`` is ``open_fdd.nf.rules.run_rules``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

from open_fdd.nf.client import NFClient, NFError, to_iso_z, parse_nf_ts

APP_FULL = "open-fdd"
APP_LITE = "open-fdd-lite"
HOOK_DATA = "sparql-data"
HOOK_RDF = "rdf"
POINT_LIMIT = 200
PAGE_DAYS = 7.0
MIN_WINDOW = timedelta(minutes=5)
MAX_CALLS = 5000
UUID_VARS = ("uuid", "tsId", "timeseriesId", "point", "p")

Transport = Callable[[str, Mapping[str, Any]], dict]


def hook_transport(client: NFClient, app_id: str = APP_FULL, timeout: float = 180.0) -> Transport:
    """``transport(hook_id, args) -> answer`` through NF StartHook (flat string map) and the run's JSON answer line."""
    return lambda hook_id, args: client.call_hook(app_id, hook_id, args, timeout=timeout)


def _utc(t: datetime | str) -> datetime:
    if isinstance(t, str):
        return parse_nf_ts(t)
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _empty(bucket: str) -> dict:
    return {"ok": True, "kind": "select", "vars": [], "rows": [], "uuid_var": None, "points": {}, "equips": [],
            "series": {}, "source": None, "bucket": bucket, "snapshot": None, "calls": 0}


def _merge(out: dict, ans: Mapping[str, Any]) -> None:
    out["points"].update(ans.get("points") or {})
    seen = {(e["site"], e["id"]) for e in out["equips"]}
    out["equips"].extend(e for e in ans.get("equips") or [] if (e["site"], e["id"]) not in seen)
    for u, s in (ans.get("series") or {}).items():
        out["series"].setdefault(u, []).extend(list(x) for x in s)


def fetch(transport: Transport, query: str, start: datetime | str, end: datetime | str, *, bucket: str = "5 minutes",
          source: str = "auto", point_limit: int = POINT_LIMIT, page_days: float = PAGE_DAYS,
          max_calls: int = MAX_CALLS) -> dict:
    """Every page of the ``sparql-data`` hook for ``[start, end)`` merged into one answer.

    Points page with ``pointOffset`` (at most 200 a page), time in windows of ``page_days`` that follow the hook's
    ``next_from`` when an answer was cut at the byte cap; a ``too_large`` window is halved (down to 5 minutes).
    Every call carries the first answer's ``snapshot``: if the model changes meanwhile the hook refuses and this
    raises ``NFError`` (start again) rather than merge two different models. Values stay in stored units.
    """
    t0, t1 = _utc(start), _utc(end)
    if t1 <= t0:
        raise NFError("start must be before end")
    out = _empty(bucket)
    page = timedelta(days=page_days)
    offset: int | None = 0
    first = True
    while offset is not None:
        cur = t0
        next_offset = None
        while cur < t1:
            stop = min(cur + page, t1)
            while True:
                if out["calls"] >= max_calls:
                    raise NFError(f"more than {max_calls} sparql-data calls; narrow the query or the range")
                args: dict[str, Any] = {"query": query, "from": to_iso_z(cur), "to": to_iso_z(stop), "bucket": bucket,
                                        "source": source, "pointOffset": offset, "pointLimit": point_limit,
                                        "includeRows": first}
                if out["snapshot"]:
                    args["snapshot"] = out["snapshot"]
                ans = transport(HOOK_DATA, args)
                out["calls"] += 1
                if not ans.get("ok"):
                    if ans.get("error_code") == "too_large" and stop - cur > MIN_WINDOW:
                        stop = cur + max(MIN_WINDOW, (stop - cur) / 2)
                        continue
                    raise NFError(f"sparql-data: {ans.get('error') or 'failed'}")
                break
            if ans.get("kind") == "ask":
                return {**_empty(bucket), "kind": "ask", "value": bool(ans.get("value")), "calls": out["calls"]}
            if first:
                out.update(vars=list(ans.get("vars") or []), rows=list(ans.get("rows") or []),
                           uuid_var=ans.get("uuid_var"), source=ans.get("source"), snapshot=ans.get("snapshot"),
                           rows_total=ans.get("rows_total"), points_total=ans.get("points_total"))
                first = False
            _merge(out, ans)
            next_offset = ans.get("next_point_offset")
            cur = parse_nf_ts(ans["next_from"]) if not ans.get("complete", True) and ans.get("next_from") else stop
        offset = next_offset
    _dedup(out)
    return out


def _dedup(out: dict) -> None:
    """Time order per point; a repeated timestamp keeps the last sample (page edges, NF duplicates)."""
    for u, s in out["series"].items():
        last: dict[int, Any] = {}
        for t, v in s:
            last.pop(int(t), None)
            last[int(t)] = v
        out["series"][u] = sorted(([t, v] for t, v in last.items()), key=lambda x: x[0])


# ---------------------------------------------------------------------------- Lite / local SPARQL
_FORM = re.compile(r"^\s*(?:(?:PREFIX\s+[^\s:]*:\s*<[^>]*>|BASE\s*<[^>]*>|#[^\n]*)\s*)*([A-Za-z]+)", re.I)


def with_prefixes(query: str, turtle: str) -> str:
    """The Turtle's ``@prefix`` lines as PREFIX lines in front of the query, for those it does not declare."""
    declared = {m.group(1) for m in re.finditer(r"PREFIX\s+([A-Za-z0-9_-]*):", query, re.I)}
    lines = [f"PREFIX {m.group(1)}: <{m.group(2)}>"
             for m in re.finditer(r"^@prefix\s+([A-Za-z0-9_-]*):\s*<([^>]*)>\s*\.", turtle, re.M)
             if m.group(1) not in declared]
    return "\n".join(lines + [query]) if lines else query


def check_query(query: str) -> str:
    """``SELECT`` or ``ASK``; anything else (graphs, updates, SERVICE) raises NFError. Local path = same policy as the hook."""
    from rdflib.plugins.sparql import prepareQuery

    if not isinstance(query, str) or not query.strip() or len(query) > 20000:
        raise NFError("query is required (at most 20000 characters)")
    m = _FORM.match(query)
    form = (m.group(1) if m else "").upper()
    if form not in ("SELECT", "ASK"):
        raise NFError(f"only SELECT and ASK are allowed (got {form or 'nothing'}): SPARQL here is read-only")
    try:
        prepared = prepareQuery(query)
    except Exception as exc:  # noqa: BLE001 - rdflib raises several parse error types
        raise NFError(f"SPARQL parse error: {exc}") from exc
    if "ServiceGraphPattern" in repr(prepared.algebra):
        raise NFError("SERVICE (federated queries) is not allowed")
    return form


def rdf_turtle(transport: Transport) -> tuple[str, str]:
    """``(turtle, base)`` from the ``rdf`` hook, every page on one snapshot."""
    text, offset, snap, base = [], 0, None, ""
    for _ in range(10000):
        args: dict[str, Any] = {"offset": offset}
        if snap:
            args["snapshot"] = snap
        ans = transport(HOOK_RDF, args)
        if not ans.get("ok"):
            raise NFError(f"rdf: {ans.get('error') or 'failed'}")
        snap, base = ans.get("snapshot"), ans.get("base") or base
        text.append(ans.get("turtle") or "")
        if ans.get("next_offset") is None:
            return "".join(text), base
        offset = int(ans["next_offset"])
    raise NFError("rdf: too many pages")


def _pick(vars_: list[str], rows: list[dict], keys: Mapping[str, str], uuid_var: str = "") -> tuple[str, list[str]]:
    order = [uuid_var] if uuid_var else [*[v for v in UUID_VARS if v in vars_], *[v for v in vars_ if v not in UUID_VARS]]
    for v in order:
        ids = sorted({keys[r[v]] for r in rows if r.get(v) in keys})
        if ids:
            return v, ids
    raise NFError("the result names no point of the model: select a uuid (ref:hasTimeseriesId) or a point IRI")


def fetch_local(client: NFClient, query: str, start: datetime | str, end: datetime | str, *, window_sec: int = 300,
                app_id: str = APP_LITE, turtle: str | None = None, base: str | None = None, uuid_var: str = "",
                transport: Transport | None = None) -> dict:
    """Same answer as ``fetch`` without a SPARQL engine on the box: Turtle from the ``rdf`` hook (or given), the query
    here (rdflib), history through ``NFClient.point_data`` (``window_sec=0`` = raw). Read-only throughout."""
    import rdflib

    from open_fdd.nf.model import load_model

    if turtle is None:
        turtle, base = rdf_turtle(transport or hook_transport(client, app_id))
    q = with_prefixes(query, turtle)
    form = check_query(q)
    g = rdflib.Graph()
    g.parse(data=turtle, format="turtle")
    res = g.query(q)
    if form == "ASK":
        return {**_empty("raw" if not window_sec else f"{window_sec} s"), "kind": "ask", "value": bool(res.askAnswer)}
    vars_ = [str(v) for v in res.vars]
    rows = [{v: (None if r[i] is None else str(r[i])) for i, v in enumerate(vars_)} for r in res]
    if len(rows) > 5000:
        raise NFError("SPARQL result exceeds 5000 rows; narrow the query or add LIMIT")
    model = load_model(client)
    keys: dict[str, str] = {}
    for p in model.points:
        if p.uuid:
            keys[p.uuid] = p.uuid
            if base:
                keys[base + p.uuid] = p.uuid
    var, uuids = _pick(vars_, rows, keys, uuid_var)
    by = {p.uuid: p for p in model.points}
    data = client.point_data(uuids, _utc(start), _utc(end), window_sec=window_sec)
    out = _empty("raw" if not window_sec else f"{window_sec} s")
    out.update(vars=vars_, rows=rows, uuid_var=var, source="nf", points_total=len(uuids))
    for u in uuids:
        p = by[u]
        out["points"][u] = {"dis": p.dis, "unit": p.unit, "kind": p.kind, "cls": p.cls, "tags": list(p.tags),
                            "equip": p.equip_ref, "site": p.site_ref, "weather": p.weather_ref,
                            "role": (p.rec.get("attrs") or {}).get("ofddRole", "")}
        out["series"][u] = [[int(t.timestamp() * 1000), v] for t, v in data.get(u, [])]
    want = {(p.site_ref, p.equip_ref) for p in (by[u] for u in uuids) if p.equip_ref}
    from open_fdd.nf.model import id_of, markers_of
    for e in model.equips:
        a = e.get("attrs") or {}
        if (a.get("siteRef", ""), id_of(e)) in want:
            out["equips"].append({"site": a.get("siteRef", ""), "id": id_of(e), "dis": a.get("dis") or e.get("name") or id_of(e),
                                  "tags": markers_of(e)})
    return out


def fetch_auto(client: NFClient, query: str, start: datetime | str, end: datetime | str, *, bucket: str = "5 minutes",
               mode: str = "auto", app_id: str | None = None, **kw: Any) -> dict:
    """``mode`` hook | local | auto. auto: the Full app's ``sparql-data`` hook when the box has it, else Lite (local)."""
    if mode not in ("auto", "hook", "local"):
        raise NFError("mode must be auto, hook or local")
    window = 0 if bucket == "raw" else _bucket_sec(bucket)
    if mode == "local":
        return fetch_local(client, query, start, end, window_sec=window, app_id=app_id or APP_LITE, **kw)
    if mode == "hook":
        return fetch(hook_transport(client, app_id or APP_FULL), query, start, end, bucket=bucket, **kw)
    apps = {a.get("id") for a in (client.get("/api/v1/apps").get("applications") or client.get("/api/v1/apps").get("apps") or [])}
    full = app_id or (APP_FULL if APP_FULL in apps else None)
    if full:
        return fetch(hook_transport(client, full), query, start, end, bucket=bucket, **kw)
    return fetch_local(client, query, start, end, window_sec=window, app_id=app_id or APP_LITE, **kw)


def _bucket_sec(bucket: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*(minute|hour|day)s?\s*", bucket, re.I)
    if not m:
        raise NFError('bucket must be "raw" or like "5 minutes", "1 hour"')
    return int(m.group(1)) * {"minute": 60, "hour": 3600, "day": 86400}[m.group(2).lower()]


# ---------------------------------------------------------------------------- frames
def answer_model(answer: Mapping[str, Any]):
    """The answer's points and equipment as an ``open_fdd.nf.model.Model`` (only what the query matched)."""
    from open_fdd.nf.model import Model, Point

    pts = []
    for u, m in sorted(answer["points"].items()):
        tags = list(m.get("tags") or [])
        attrs = {"ofddRole": m["role"]} if m.get("role") else {}
        pts.append(Point(uuid=u, name=" ".join(t for t in tags if t not in ("point", "his", "cur", "writable", "sensor"))
                         or (m.get("dis") or u), dis=m.get("dis") or u, tags=tags, unit=m.get("unit") or "",
                         kind=m.get("kind") or "Number", equip_ref=m.get("equip") or "", site_ref=m.get("site") or "",
                         weather_ref=m.get("weather") or "", device_ref="", cls=m.get("cls") or "", latest=None,
                         rec={"uuid": u, "attrs": attrs}))
    equips = [{"name": e["id"], "attrs": {"id": e["id"], "siteRef": e.get("site") or "", "dis": e.get("dis") or e["id"],
                                         "markers": ",".join(e.get("tags") or [])}}
              for e in answer.get("equips") or []]
    return Model(sites=[], equips=equips, devices=[], points=pts)


def explicit_roles(answer: Mapping[str, Any]) -> dict[str, str]:
    """``{uuid: role}`` the query or model names outright: the ``?role`` column, else the point's ``ofddRole``."""
    out: dict[str, str] = {}
    var = answer.get("uuid_var")
    if var and "role" in (answer.get("vars") or []):
        for r in answer.get("rows") or []:
            u, role = r.get(var), r.get("role")
            u = u if u in answer["points"] else next((k for k in answer["points"] if u and u.endswith(k)), None)
            if u and role:
                out.setdefault(u, str(role))
    for u, m in answer["points"].items():
        if u not in out and m.get("role"):
            out[u] = str(m["role"])
    return out


def samples_of(answer: Mapping[str, Any]) -> dict[str, list]:
    """``{uuid: [(utc datetime, value)]}`` (the shape ``NFClient.point_data`` returns)."""
    return {u: [(datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc), v) for t, v in s]
            for u, s in (answer.get("series") or {}).items()}


def frames(answer: Mapping[str, Any], *, weather: str = "columns", roles: Iterable[str] | None = None,
           site: str | None = None, equip: str | None = None, window_sec: int | None = None) -> dict[tuple[str, str], Any]:
    """``{(site, equip): SI DataFrame}`` for ``open_fdd.rules``: the very code of ``equipment_frames``.

    Binding is ``bind_equipment`` (NF class, then markers; the equipment's points plus its site's weather points),
    frame assembly and SI conversion are ``frames_from_samples`` / ``si_plan_for``. A point the query (``?role``) or
    the model (``ofddRole``) binds explicitly fills that role, and only that role, on its equipment. Weather points
    (``weather`` marker, no equipRef) join every equipment of their site as ``web-*`` columns (``weather="columns"``)
    or are left out (``"separate"``: read them with ``weather_frame``).
    """
    from open_fdd.nf.model import bind_equipment, frames_from_samples

    if weather not in ("columns", "separate"):
        raise NFError('weather must be "columns" or "separate"')
    model = answer_model(answer)
    if weather == "separate":
        model.points = [p for p in model.points if not _is_weather(p)]
    explicit = {u: r for u, r in explicit_roles(answer).items() if any(p.uuid == u for p in model.points)}
    by = {p.uuid: p for p in model.points}
    pins: dict[tuple[str, str], dict] = {}
    scope = []
    for b in bind_equipment(model, roles=roles, site=site, equip=equip):
        b.roles = {r: [p for p in ps if explicit.get(p.uuid, r) == r] for r, ps in b.roles.items()}
        b.roles = {r: ps for r, ps in b.roles.items() if ps}
        for u, role in sorted(explicit.items()):
            p = by[u]
            if roles is not None and role not in set(roles):
                continue
            if p.site_ref == b.site and (p.equip_ref == b.equip or (_is_weather(p) and not p.equip_ref)):
                pins.setdefault((b.site, b.equip), {}).setdefault(role, p)
        if b.roles or (b.site, b.equip) in pins:
            scope.append(b)
    return frames_from_samples(scope, samples_of(answer), window_sec or _window_of(answer), pins)


def _is_weather(p) -> bool:
    return p.has("weather") and not p.equip_ref


def weather_frame(answer: Mapping[str, Any], site: str | None = None):
    """The answer's weather points (``weather`` marker, no equipRef) as one SI frame of ``web-*`` columns, or None."""
    import pandas as pd

    from open_fdd.nf.model import bind_roles, column_for, load_catalog, si_plan_for

    model = answer_model(answer)
    explicit = explicit_roles(answer)
    web = [r for r in load_catalog()["roles"] if r.startswith("web_")]
    data = samples_of(answer)
    cols = {}
    for p in model.points:
        if not _is_weather(p) or (site and p.site_ref != site) or not data.get(p.uuid):
            continue
        role = explicit.get(p.uuid) or next((r for r, ps in bind_roles(web, [p]).items() if ps), None)
        if not role or column_for(role) in cols:
            continue
        plan = si_plan_for(role, p)
        if plan.convert is None:
            continue
        idx = pd.DatetimeIndex([t for t, _ in data[p.uuid]], tz="UTC") if data[p.uuid][0][0].tzinfo is None \
            else pd.DatetimeIndex([t for t, _ in data[p.uuid]])
        cols[column_for(role)] = plan.convert(pd.Series([v for _, v in data[p.uuid]], index=idx, dtype="float64"))
    if not cols:
        return None
    df = pd.DataFrame(cols).sort_index()
    df.index.name = "timestamp_utc"
    return df


def _window_of(answer: Mapping[str, Any]) -> int:
    b = str(answer.get("bucket") or "")
    if b.endswith(" s"):
        return int(b.split()[0])
    if b and b != "raw":
        try:
            return _bucket_sec(b)
        except NFError:
            pass
    return 300


def run_rules(frames_: Mapping[tuple[str, str], Any], rules: Iterable[str] | None = None, **kw: Any):
    """``open_fdd.nf.rules.run_rules``: the pandas reference rules, unchanged (no fault math in this module)."""
    from open_fdd.nf.rules import run_rules as _run

    return _run(frames_, rules, **kw)


def run_example(client: NFClient, query: str, start: datetime | str, end: datetime | str, *,
                rules: Iterable[str] | None = None, bucket: str = "5 minutes", mode: str = "auto"):
    """Query -> trend data -> SI frames -> pandas rules, in one call. Returns ``(answer, frames, results)``."""
    ans = fetch_auto(client, query, start, end, bucket=bucket, mode=mode)
    if ans["kind"] == "ask":
        raise NFError("an ASK query returns no points; use SELECT")
    fr = frames(ans)
    return ans, fr, run_rules(fr, rules)
