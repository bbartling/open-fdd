"""SPARQL data client: query the site model on an NF box, get trend data, run the pandas reference rules here.

Same workflow as a stand-alone SPARQL endpoint ("server = model + time series, laptop = fault math"), served by the
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


class PageError(NFError):
    """A ``sparql-data`` / ``rdf`` page that is malformed or inconsistent with the request or the earlier pages.

    Distinct from a hook error (``NFError`` with the hook's message) and from a genuine empty result (an answer whose
    series are empty lists): a page whose receipt does not prove it covers what was asked is never merged.
    """


def _ms_of(value: Any, what: str) -> int:
    try:
        return int(parse_nf_ts(str(value)).timestamp() * 1000)
    except Exception as exc:  # noqa: BLE001 - any unparsable cursor is a malformed page
        raise PageError(f"sparql-data page: {what} {value!r} is not a timestamp") from exc


def check_data_page(ans: Any, *, offset: int, cur: datetime, stop: datetime, first: Mapping[str, Any] | None,
                    seen_points: set[str]) -> datetime | None:
    """Validate one ``sparql-data`` SELECT page against its request; return the next time cursor (``None`` = done).

    The page must echo the requested point offset and time window, carry the same ``snapshot`` / ``source`` /
    ``points_total`` / ``uuid_var`` as the first page, name only its own points in ``series`` (each ``[epoch_ms,
    value]`` inside the window and before the cursor), never repeat a point of an earlier point page, and either be
    ``complete`` or name a ``next_from`` strictly after the window start and at most the window end.
    """
    if not isinstance(ans, Mapping):
        raise PageError("sparql-data page: answer is not an object")
    snap = ans.get("snapshot")
    if not isinstance(snap, str) or not snap:
        raise PageError("sparql-data page: no snapshot receipt")
    if first is not None:
        for key in ("snapshot", "source", "points_total", "uuid_var"):
            if ans.get(key) != first.get(key):
                raise PageError(f"sparql-data page: {key} {ans.get(key)!r} differs from the first page "
                                f"({first.get(key)!r}); restart the request")
    if ans.get("source") not in ("nf", "timescale"):
        raise PageError(f"sparql-data page: unknown source {ans.get('source')!r}")
    if ans.get("point_offset") != offset:
        raise PageError(f"sparql-data page: point_offset {ans.get('point_offset')!r} is not the requested {offset}")
    total = ans.get("points_total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise PageError("sparql-data page: points_total missing or invalid")
    t0, t1 = int(cur.timestamp() * 1000), int(stop.timestamp() * 1000)
    if _ms_of(ans.get("from"), "from") != t0 or _ms_of(ans.get("to"), "to") != t1:
        raise PageError(f"sparql-data page: window {ans.get('from')!r}..{ans.get('to')!r} is not the requested one")
    complete = ans.get("complete")
    if not isinstance(complete, bool):
        raise PageError("sparql-data page: complete flag missing")
    nxt_ms = None
    if not complete:
        if not ans.get("next_from"):
            raise PageError("sparql-data page: incomplete page without next_from")
        nxt_ms = _ms_of(ans["next_from"], "next_from")
        if not t0 < nxt_ms <= t1:
            raise PageError(f"sparql-data page: next_from {ans['next_from']!r} does not advance inside the window")
    elif ans.get("next_from"):
        raise PageError("sparql-data page: complete page with a next_from")
    points = ans.get("points")
    series = ans.get("series")
    if not isinstance(points, Mapping) or not isinstance(series, Mapping):
        raise PageError("sparql-data page: points / series missing")
    nxt_off = ans.get("next_point_offset")
    if nxt_off is not None and (not isinstance(nxt_off, int) or isinstance(nxt_off, bool)
                                or not offset < nxt_off <= total or nxt_off - offset != len(points)):
        raise PageError(f"sparql-data page: next_point_offset {nxt_off!r} does not follow offset {offset} "
                        f"with {len(points)} points")
    if nxt_off is None and offset + len(points) != total:
        raise PageError(f"sparql-data page: last point page ends at {offset + len(points)}, not points_total {total}")
    if any(not isinstance(m, Mapping) for m in points.values()):
        raise PageError("sparql-data page: point metadata is not an object")
    repeated = seen_points.intersection(points)
    if repeated:
        raise PageError(f"sparql-data page: points repeated from an earlier point page: {sorted(repeated)[:3]}")
    end_ms = nxt_ms if nxt_ms is not None else t1
    missing = [u for u in points if u not in series]
    if missing:
        # every point of the page answers, even with no samples ([]); a missing entry is lost data, not an empty series
        raise PageError(f"sparql-data page: no series for points {sorted(missing)[:3]}")
    for u, s in series.items():
        if u not in points:
            raise PageError(f"sparql-data page: series for {u!r}, which is not a point of this page")
        if not isinstance(s, list):
            raise PageError(f"sparql-data page: series {u!r} is not a list")
        for x in s:
            if (not isinstance(x, (list, tuple)) or len(x) != 2 or not isinstance(x[0], int) or isinstance(x[0], bool)
                    or not (isinstance(x[1], (int, float, str)) and not isinstance(x[1], bool))):
                raise PageError(f"sparql-data page: sample {x!r} of {u!r} is not [epoch_ms, number | text]")
            if not t0 <= x[0] < end_ms:
                raise PageError(f"sparql-data page: sample at {x[0]} of {u!r} is outside the page window")
    return None if complete else datetime.fromtimestamp(nxt_ms / 1000, tz=timezone.utc)


def fetch(transport: Transport, query: str, start: datetime | str, end: datetime | str, *, bucket: str = "5 minutes",
          source: str = "auto", point_limit: int = POINT_LIMIT, page_days: float = PAGE_DAYS,
          max_calls: int = MAX_CALLS) -> dict:
    """Every page of the ``sparql-data`` hook for ``[start, end)`` merged into one answer.

    Points page with ``pointOffset`` (at most 200 a page), time in windows of ``page_days`` that follow the hook's
    ``next_from`` when an answer was cut at the byte cap; a ``too_large`` window is halved (down to 5 minutes).
    Every call carries the first answer's ``snapshot``: if the model changes meanwhile the hook refuses and this
    raises ``NFError`` (start again) rather than merge two different models. Every page is checked against its
    request (``check_data_page``): a malformed, incomplete-without-cursor, regressing or inconsistent page raises
    ``PageError`` instead of silently shortening the window (#1623). Values stay in stored units.
    """
    t0, t1 = _utc(start), _utc(end)
    if t1 <= t0:
        raise NFError("start must be before end")
    out = _empty(bucket)
    page = timedelta(days=page_days)
    width = 0 if str(bucket).strip().lower() == "raw" else _bucket_sec(bucket)
    min_window = max(MIN_WINDOW, timedelta(seconds=width))
    if width:
        # buckets are aligned to the Unix epoch: widen to whole buckets and page on bucket boundaries, so no bucket
        # is ever split across two pages (it would come back twice under one timestamp with partial averages)
        t0, t1 = _align(t0, width, up=False), _align(t1, width, up=True)
        page = timedelta(seconds=max(width, (page.total_seconds() // width) * width))
    offset: int | None = 0
    first: dict | None = None
    seen: set[str] = set()
    while offset is not None:
        cur = t0
        next_offset = None
        first_time_page = True
        page_points: set[str] | None = None
        while cur < t1:
            stop = min(cur + page, t1)
            while True:
                if out["calls"] >= max_calls:
                    raise NFError(f"more than {max_calls} sparql-data calls; narrow the query or the range")
                args: dict[str, Any] = {"query": query, "from": to_iso_z(cur), "to": to_iso_z(stop), "bucket": bucket,
                                        "source": source, "pointOffset": offset, "pointLimit": point_limit,
                                        "includeRows": first is None}
                if out["snapshot"]:
                    args["snapshot"] = out["snapshot"]
                ans = transport(HOOK_DATA, args)
                out["calls"] += 1
                if not isinstance(ans, Mapping):
                    raise PageError("sparql-data page: answer is not an object")
                if ans.get("ok") is not True:
                    if ans.get("ok") is False and ans.get("error_code") == "too_large" and stop - cur > min_window:
                        stop = cur + max(min_window, (stop - cur) / 2)
                        if width:
                            stop = max(cur + timedelta(seconds=width), _align(stop, width, up=False))
                        continue
                    if ans.get("ok") is not False:
                        raise PageError("sparql-data page: no ok flag")
                    raise NFError(f"sparql-data: {ans.get('error') or 'failed'}")
                break
            if ans.get("kind") == "ask":
                if first is not None or not isinstance(ans.get("value"), bool):
                    raise PageError("sparql-data page: ASK answer without a boolean value")
                return {**_empty(bucket), "kind": "ask", "value": ans["value"], "calls": out["calls"]}
            if ans.get("kind") != "select":
                raise PageError(f"sparql-data page: unknown kind {ans.get('kind')!r}")
            nxt = check_data_page(ans, offset=offset, cur=cur, stop=stop, first=first, seen_points=seen)
            if page_points is None:
                page_points = set(ans["points"])
            elif set(ans["points"]) != page_points:
                raise PageError("sparql-data page: the point page changed between time pages")
            if first is None:
                if not isinstance(ans.get("vars"), list) or not isinstance(ans.get("rows"), list):
                    raise PageError("sparql-data page: first page without vars / rows")
                first = {k: ans.get(k) for k in ("snapshot", "source", "points_total", "uuid_var")}
                out.update(vars=list(ans["vars"]), rows=list(ans["rows"]), uuid_var=ans.get("uuid_var"),
                           source=ans.get("source"), snapshot=ans.get("snapshot"), rows_total=ans.get("rows_total"),
                           points_total=ans.get("points_total"))
            if first_time_page:
                next_offset = ans.get("next_point_offset")
                first_time_page = False
            elif ans.get("next_point_offset") != next_offset:
                raise PageError("sparql-data page: next_point_offset changed between time pages")
            _merge(out, ans)
            cur = nxt if nxt is not None else stop
        seen |= page_points or set()
        offset = next_offset
    if first is not None and len(seen) != first["points_total"]:
        raise PageError(f"sparql-data: {len(seen)} points received, points_total is {first['points_total']}")
    _dedup(out)
    return out


def _align(t: datetime, width: int, *, up: bool) -> datetime:
    ms, w = int(round(t.timestamp() * 1000)), width * 1000
    ms = -(-ms // w) * w if up else (ms // w) * w
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


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


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def rdf_turtle(transport: Transport) -> tuple[str, str]:
    """``(turtle, base)`` from the ``rdf`` hook, every page on one snapshot.

    Offsets count UTF-16 characters (the hook is JavaScript). Each page must echo the requested offset, keep the first
    page's ``snapshot`` / ``total_chars``, and end exactly where its ``next_offset`` says (or at ``total_chars``);
    anything else raises ``PageError`` instead of joining a gapped or overlapping Turtle (#1623).
    """
    text: list[str] = []
    offset, snap, base, total = 0, None, "", None
    for _ in range(10000):
        args: dict[str, Any] = {"offset": offset}
        if snap:
            args["snapshot"] = snap
        ans = transport(HOOK_RDF, args)
        if not isinstance(ans, Mapping):
            raise PageError("rdf page: answer is not an object")
        if ans.get("ok") is not True:
            if ans.get("ok") is False:
                raise NFError(f"rdf: {ans.get('error') or 'failed'}")
            raise PageError("rdf page: no ok flag")
        chunk, page_snap = ans.get("turtle"), ans.get("snapshot")
        if not isinstance(chunk, str) or not isinstance(page_snap, str) or not page_snap:
            raise PageError("rdf page: turtle / snapshot receipt missing")
        if snap is not None and (page_snap != snap or ans.get("total_chars") != total):
            raise PageError("rdf page: snapshot or total_chars changed between pages; start again")
        if ans.get("offset") != offset:
            raise PageError(f"rdf page: offset {ans.get('offset')!r} is not the requested {offset}")
        snap, total, base = page_snap, ans.get("total_chars"), ans.get("base") or base
        if not isinstance(total, int) or isinstance(total, bool) or total < offset:
            raise PageError("rdf page: total_chars missing or invalid")
        end = offset + _utf16_len(chunk)
        text.append(chunk)
        nxt = ans.get("next_offset")
        if nxt is None:
            if end != total:
                raise PageError(f"rdf page: last page ends at {end}, total_chars is {total}")
            return "".join(text), base
        if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt != end or nxt <= offset or nxt > total:
            raise PageError(f"rdf page: next_offset {nxt!r} does not follow offset {offset} + {end - offset} chars")
        offset = nxt
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
    data = client.point_data(uuids, _utc(start), _utc(end), window_sec=window_sec, keep_text=True)
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
           site: str | None = None, equip: str | None = None, window_sec: int | None = None,
           sweep_marker: str | None = None) -> dict[tuple[str, str], Any]:
    """``{(site, equip): SI DataFrame}`` for ``open_fdd.rules``: the very code of ``equipment_frames``.

    Binding is ``bind_equipment`` (NF class, then markers; the equipment's points plus its site's weather points),
    frame assembly and SI conversion are ``frames_from_samples`` / ``si_plan_for``. A point the query (``?role``) or
    the model (``ofddRole``) binds explicitly fills that role, and only that role, on its equipment. Weather points
    (``weather`` marker, no equipRef) join every equipment of their site as ``web-*`` columns (``weather="columns"``)
    or are left out (``"separate"``: read them with ``weather_frame``). ``sweep_marker`` (e.g. ``"sensor"``) limits the
    SV sweeps to points carrying that marker (see ``frames_from_samples``).
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
    return frames_from_samples(scope, samples_of(answer), window_sec or _window_of(answer), pins, sweep_marker)


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
