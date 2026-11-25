"""open_fdd.nf.sparql_data: paging, snapshot, too_large retry, local (rdflib) path, frames == equipment_frames."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.nf import sparql_data as sd  # noqa: E402
from open_fdd.nf.client import NFError  # noqa: E402

T0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
MS0 = int(T0.timestamp() * 1000)


def _pt(u, equip="AHU-1", role="", tags=("point", "his", "sensor"), unit="°C"):
    return {"dis": u, "unit": unit, "kind": "Number", "cls": "", "tags": list(tags), "equip": equip, "site": "s1",
            "weather": "", "role": role}


class FakeHook:
    """sparql-data over two points, paged one point a page, cut at 3 samples a page (next_from)."""

    def __init__(self, n=6, change_snapshot_at=None, too_large_over=None):
        self.calls, self.n, self.change_at, self.too_large_over = [], n, change_snapshot_at, too_large_over
        self.points = {"u1": _pt("u1", role="sat"), "u2": _pt("u2", role="mat")}

    def __call__(self, hook, args):
        assert hook == "sparql-data"
        self.calls.append(dict(args))
        f = int(datetime.fromisoformat(args["from"].replace("Z", "+00:00")).timestamp() * 1000)
        t = int(datetime.fromisoformat(args["to"].replace("Z", "+00:00")).timestamp() * 1000)
        if self.too_large_over and t - f > self.too_large_over:
            return {"ok": False, "error": "too big", "error_code": "too_large"}
        snap = "B" if self.change_at is not None and len(self.calls) > self.change_at else "A"
        if args.get("snapshot") and args["snapshot"] != snap:
            return {"ok": False, "error": "model changed since snapshot", "error_code": "snapshot"}
        off = int(args.get("pointOffset") or 0)
        u = sorted(self.points)[off]
        samples = [[MS0 + i * 300_000, float(i)] for i in range(self.n) if f <= MS0 + i * 300_000 < t]
        page, rest = samples[:3], samples[3:]
        ans = {"ok": True, "kind": "select", "vars": ["uuid", "role"], "uuid_var": "uuid", "source": "nf",
               "snapshot": snap, "points": {u: self.points[u]}, "equips": [{"site": "s1", "id": "AHU-1", "dis": "AHU 1",
                                                                            "tags": ["equip", "ahu"]}],
               "series": {u: page}, "complete": not rest, "point_offset": off, "points_total": len(self.points),
               "from": args["from"], "to": args["to"],
               "next_point_offset": off + 1 if off + 1 < len(self.points) else None}
        if args.get("includeRows"):
            ans["rows"] = [{"uuid": k, "role": self.points[k]["role"]} for k in sorted(self.points)]
        if rest:
            ans["next_from"] = datetime.fromtimestamp(rest[0][0] / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return ans


def test_fetch_pages_points_and_time_on_one_snapshot():
    h = FakeHook()
    ans = sd.fetch(h, "SELECT ?uuid ?role WHERE {}", T0, T0 + timedelta(hours=1), bucket="raw")
    assert set(ans["series"]) == {"u1", "u2"}
    assert [t for t, _ in ans["series"]["u1"]] == [MS0 + i * 300_000 for i in range(6)]
    assert all(c.get("snapshot") == "A" for c in h.calls[1:])
    assert h.calls[0]["includeRows"] is True and all(c["includeRows"] is False for c in h.calls[1:])
    assert len(ans["rows"]) == 2


def test_fetch_refuses_a_model_change_mid_paging():
    with pytest.raises(NFError, match="snapshot|changed"):
        sd.fetch(FakeHook(change_snapshot_at=1), "SELECT ?uuid WHERE {}", T0, T0 + timedelta(hours=1))


def test_fetch_halves_a_too_large_window():
    h = FakeHook(too_large_over=20 * 60_000)
    ans = sd.fetch(h, "SELECT ?uuid WHERE {}", T0, T0 + timedelta(hours=1), bucket="raw")
    assert len(ans["series"]["u1"]) == 6
    spans = [(datetime.fromisoformat(c["to"][:-1] + "+00:00") - datetime.fromisoformat(c["from"][:-1] + "+00:00")) for c in h.calls]
    assert max(spans) > timedelta(minutes=20) and min(spans) <= timedelta(minutes=20)  # refused, then halved


def test_fetch_rejects_bad_range_and_reports_errors():
    with pytest.raises(NFError):
        sd.fetch(FakeHook(), "SELECT ?uuid WHERE {}", T0, T0)
    with pytest.raises(NFError, match="nope"):
        sd.fetch(lambda h, a: {"ok": False, "error": "nope"}, "SELECT ?uuid WHERE {}", T0, T0 + timedelta(hours=1))


def test_flat_string_args_reach_the_hook():
    from open_fdd.nf.client import hook_args

    flat = hook_args({"pointOffset": 0, "includeRows": True, "query": "SELECT", "snapshot": None})
    assert flat == {"pointOffset": "0", "includeRows": "true", "query": "SELECT"}


def test_check_query_is_read_only():
    pytest.importorskip("rdflib")
    assert sd.check_query("SELECT ?s WHERE { ?s ?p ?o }") == "SELECT"
    assert sd.check_query("PREFIX x: <urn:x#>\nASK { ?s ?p ?o }") == "ASK"
    for q in ("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "DESCRIBE <urn:x>", "INSERT DATA { <urn:a> <urn:b> 1 }",
              "SELECT * WHERE { SERVICE <http://evil/> { ?s ?p ?o } }", ""):
        with pytest.raises(NFError):
            sd.check_query(q)


def test_frames_explicit_roles_use_the_shared_si_assembly():
    ans = sd.fetch(FakeHook(), "SELECT ?uuid ?role WHERE {}", T0, T0 + timedelta(hours=1), bucket="raw")
    fr = sd.frames(ans, window_sec=300)
    df = fr[("s1", "AHU-1")]
    assert list(df.columns) == ["discharge-air-temp", "mixed-air-temp"]
    assert df.attrs["role_units"]["discharge-air-temp"] == "°C" and df.attrs["window_sec"] == 300
    assert str(df.index.tz) == "UTC" and len(df) == 6


def test_frames_degf_converted_to_si_like_equipment_frames():
    from open_fdd.nf.model import Model, Point, frames_from_samples, bind_equipment

    ans = {"kind": "select", "vars": ["uuid"], "uuid_var": "uuid", "rows": [], "bucket": "raw",
           "points": {"u1": _pt("u1", role="sat", unit="°F")},
           "equips": [{"site": "s1", "id": "AHU-1", "dis": "AHU 1", "tags": ["equip", "ahu"]}],
           "series": {"u1": [[MS0, 212.0], [MS0 + 300_000, 32.0]]}}
    df = sd.frames(ans)[("s1", "AHU-1")]
    assert df["discharge-air-temp"].round(6).tolist() == [100.0, 0.0]
    assert Model and Point and frames_from_samples and bind_equipment


def test_weather_frame_and_separate():
    wx = _pt("w1", equip="", role="web_oa_t", tags=("point", "his", "sensor", "weather"))
    ans = {"kind": "select", "vars": ["uuid"], "uuid_var": "uuid", "rows": [], "bucket": "raw",
           "points": {"u1": _pt("u1", role="sat"), "w1": wx},
           "equips": [{"site": "s1", "id": "AHU-1", "dis": "AHU 1", "tags": ["equip", "ahu"]}],
           "series": {"u1": [[MS0, 12.0]], "w1": [[MS0, -3.0]]}}
    assert "web-outside-air-temp" in sd.frames(ans)[("s1", "AHU-1")].columns
    assert "web-outside-air-temp" not in sd.frames(ans, weather="separate")[("s1", "AHU-1")].columns
    assert sd.weather_frame(ans)["web-outside-air-temp"].tolist() == [-3.0]


def test_run_rules_is_the_package_runner():
    from open_fdd.nf import rules

    assert sd.run_rules.__module__ == "open_fdd.nf.sparql_data"
    ans = sd.fetch(FakeHook(), "SELECT ?uuid ?role WHERE {}", T0, T0 + timedelta(hours=1), bucket="raw")
    out = sd.run_rules(sd.frames(ans))
    assert list(out.columns) == rules.COLUMNS


def test_bucket_parsing():
    assert sd._bucket_sec("5 minutes") == 300 and sd._bucket_sec("1 hour") == 3600
    with pytest.raises(NFError):
        sd._bucket_sec("3 fortnights")

def test_fetch_local_runs_the_query_here_like_lite(tmp_path):
    """Lite path: Turtle (from the rdf hook or given), the query with rdflib, history through point_data."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    pytest.importorskip("rdflib")
    if shutil.which("node") is None:
        pytest.skip("node builds the fixture Turtle")
    root = Path(__file__).resolve().parents[1]
    fixture = root / "tools" / "rdf-check" / "fixtures" / "model.json"
    ttl = tmp_path / "m.ttl"
    subprocess.run(["node", str(root / "tools" / "rdf-check" / "gen_ttl.js"), str(fixture), str(ttl)], check=True,
                   capture_output=True)
    recs = json.loads(fixture.read_text(encoding="utf-8"))["records"]
    sat = "11111111-0000-4000-8000-000000000004"

    class Client:
        calls = []

        def query_all(self, layer, structured=None):
            return [r for r in recs if (r["pointType"] != "POINT") == (layer == "model")]

        def point_data(self, uuids, start, end, window_sec=300, **kw):
            self.calls.append((tuple(uuids), window_sec))
            return {u: [(T0, 55.0), (T0 + timedelta(minutes=5), 56.0)] for u in uuids}

    c = Client()
    q = (root / "examples" / "sparql_data" / "ahu_points.rq").read_text(encoding="utf-8")
    ans = sd.fetch_local(c, q, T0, T0 + timedelta(hours=1), window_sec=0, turtle=ttl.read_text(encoding="utf-8"),
                         base="urn:test:")
    assert ans["uuid_var"] == "uuid" and sat in ans["points"]
    assert ans["points"][sat]["unit"] == "degF" and ans["series"][sat][0][1] == 55.0
    assert c.calls and c.calls[0][1] == 0  # raw
    assert any(e["id"] == "AHU-1" for e in ans["equips"])
    df = sd.frames(ans)[("site-a", "AHU-1")]
    assert df["discharge-air-temp"].round(4).tolist() == [12.7778, 13.3333]  # degF -> degC, same SI plan
    with pytest.raises(NFError):
        sd.fetch_local(c, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", T0, T0 + timedelta(hours=1),
                       turtle=ttl.read_text(encoding="utf-8"))

def test_point_iri_in_the_fixed_base_and_older_iris_all_name_the_point():
    """#1773: the base is the fixed urn:nf:; IRIs from older host- or site-based exports still name their point."""
    base, u = "urn:nf:", "11111111-0000-4000-8000-000000000004"
    keys = {u: u, base + u: u}
    assert sd._pick(["p"], [{"p": base + u}], keys) == ("p", [u])
    assert sd._pick(["p"], [{"p": f"urn:nf:192.168.1.50:8090:{u}"}], keys) == ("p", [u])
    assert sd._pick(["p"], [{"p": f"urn:nf:site:11111111-0000-4000-8000-000000000001:{u}"}], keys) == ("p", [u])
    assert sd._pick(["p", "q"], [{"p": None, "q": u}], keys) == ("q", [u])
    for bad in ("urn:nf:192.168.1.50:8090:nope", f"http://x.test/{u}"):
        with pytest.raises(NFError):
            sd._pick(["p"], [{"p": bad}], keys)


def test_to_iso_z_keeps_fractions_for_exact_continuation():
    from open_fdd.nf.client import parse_nf_ts, to_iso_z

    assert to_iso_z(datetime(2026, 1, 5, tzinfo=timezone.utc)) == "2026-01-05T00:00:00Z"
    t = parse_nf_ts("2026-01-05T00:00:00.500Z")
    assert to_iso_z(t) == "2026-01-05T00:00:00.500Z" and parse_nf_ts(to_iso_z(t)) == t
    assert to_iso_z(datetime(2026, 1, 5, 0, 0, 0, 123456, tzinfo=timezone.utc)).endswith(".123456Z")


def test_fetch_continues_from_a_subsecond_next_from():
    seen = []

    def hook(h, a):
        seen.append(a["from"])
        env = {"ok": True, "kind": "select", "uuid_var": "uuid", "snapshot": "A", "source": "nf", "point_offset": 0,
               "points_total": 1, "from": a["from"], "to": a["to"], "points": {"u1": _pt("u1")}, "equips": [],
               "next_point_offset": None}
        if len(seen) == 1:
            return {**env, "vars": ["uuid"], "rows": [], "series": {"u1": [[MS0, 1.0]]}, "complete": False,
                    "next_from": "2026-01-05T00:00:00.500Z"}
        return {**env, "series": {"u1": [[MS0 + 500, 2.0]]}, "complete": True}

    ans = sd.fetch(hook, "SELECT ?uuid WHERE {}", T0, T0 + timedelta(minutes=5), bucket="raw")
    assert seen[1] == "2026-01-05T00:00:00.500Z" and len(seen) == 2
    assert [t for t, _ in ans["series"]["u1"]] == [MS0, MS0 + 500]


def test_raw_point_data_splits_at_the_sample_cap_and_keeps_text():
    from open_fdd.nf.client import NFClient

    calls = []

    class C(NFClient):
        def __init__(self):
            pass

        def get(self, path):
            import urllib.parse as up
            q = up.parse_qs(up.urlparse(path).query)
            f = datetime.fromisoformat(q["from"][0].replace("Z", "+00:00"))
            t = datetime.fromisoformat(q["to"][0].replace("Z", "+00:00"))
            calls.append((f, t))
            n = int((t - f).total_seconds() // 60)
            vals = [{"ts": (f + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
                     "double": float(i)} for i in range(min(n, 4))]
            txt = [{"ts": f.isoformat().replace("+00:00", "Z"), "string": "Occupied"}]
            full = [{"ts": f.isoformat().replace("+00:00", "Z"), "double": 1.0}] * 2   # always at a cap of 1
            return {"data": [{"uuid": "num", "values": vals}, {"uuid": "txt", "values": txt}, {"uuid": "full", "values": full}]}

    out = C().point_data(["num", "txt"], T0, T0 + timedelta(minutes=8), window_sec=0, keep_text=True, sample_cap=4)
    assert len(out["num"]) == 8 and len(calls) > 1           # a read at the cap is split until under it
    assert out["txt"][0][1] == "Occupied"
    assert C().point_data(["txt"], T0, T0 + timedelta(minutes=1), window_sec=0)["txt"] == []   # numbers only by default
    with pytest.raises(NFError, match="sample cap"):
        C().point_data(["full"], T0, T0 + timedelta(minutes=8), window_sec=0, sample_cap=1)

# ---------------------------------------------------------------------------- #1623: page receipts
def _page(a, **kw):
    """One valid single-point page answering request ``a``; ``kw`` overrides fields (``None`` deletes one)."""
    ans = {"ok": True, "kind": "select", "vars": ["uuid"], "rows": [{"uuid": "u1"}], "uuid_var": "uuid",
           "snapshot": "A", "source": "nf", "point_offset": int(a.get("pointOffset") or 0), "points_total": 1,
           "from": a["from"], "to": a["to"], "points": {"u1": _pt("u1")}, "equips": [],
           "series": {"u1": [[MS0, 1.0]]}, "complete": True, "next_point_offset": None}
    ans.update(kw)
    return {k: v for k, v in ans.items() if v is not None or k in ("next_point_offset",)}


def _one(**kw):
    return lambda h, a: _page(a, **kw)


T1 = T0 + timedelta(hours=1)


def test_incomplete_page_without_next_from_is_rejected():
    """The minimal malformed response of #1623: one row, complete=false, no next_from -> error, never success."""
    calls = []

    def hook(h, a):
        calls.append(a)
        return _page(a, complete=False, next_from=None)

    with pytest.raises(sd.PageError, match="without next_from"):
        sd.fetch(hook, "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")
    assert len(calls) == 1


@pytest.mark.parametrize("kw, match", [
    ({"complete": False, "next_from": "2026-01-05T00:00:00Z"}, "does not advance"),      # repeated cursor
    ({"complete": False, "next_from": "2026-01-04T23:00:00Z"}, "does not advance"),      # regressing
    ({"complete": False, "next_from": "2026-01-05T02:00:00Z"}, "does not advance"),      # past the window
    ({"complete": False, "next_from": "soon"}, "not a timestamp"),
    ({"complete": None}, "complete flag"),
    ({"snapshot": None}, "snapshot"),
    ({"source": "elsewhere"}, "unknown source"),
    ({"point_offset": 3}, "point_offset"),
    ({"points_total": None}, "points_total"),
    ({"from": "2026-01-05T00:30:00Z"}, "window"),
    ({"series": {"u1": [], "u9": []}}, "not a point of this page"),
    ({"series": {}}, "no series for points"),                                            # a point's series is missing
    ({"series": {"u1": [[MS0 - 1, 1.0]]}}, "outside the page window"),
    ({"series": {"u1": [["x", 1.0]]}}, "epoch_ms"),
    ({"series": {"u1": [[MS0, True]]}}, "epoch_ms"),
    ({"series": {"u1": [[MS0, {"v": 1}]]}}, "epoch_ms"),
    ({"points_total": 2}, "points_total"),                                               # last page short
    ({"next_point_offset": 5, "points_total": 6}, "next_point_offset"),                  # skips points
    ({"kind": "construct"}, "unknown kind"),
    ({"ok": None}, "no ok flag"),
])
def test_malformed_pages_are_rejected_distinctly(kw, match):
    with pytest.raises(sd.PageError, match=match):
        sd.fetch(_one(**kw), "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")


def test_hook_error_and_empty_result_are_not_page_errors():
    with pytest.raises(NFError) as e:
        sd.fetch(lambda h, a: {"ok": False, "error": "too big", "error_code": "too_large"}, "SELECT ?uuid WHERE {}",
                 T0, T0 + timedelta(minutes=5), bucket="raw")
    assert not isinstance(e.value, sd.PageError) and "too big" in str(e.value)
    empty = sd.fetch(_one(series={"u1": []}), "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")
    assert empty["series"] == {"u1": []} and empty["points_total"] == 1        # genuine empty data is a success


def test_a_false_or_zero_sample_is_data_not_absence():
    ans = sd.fetch(_one(series={"u1": [[MS0, 0], [MS0 + 1, 0.0]]}), "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")
    assert ans["series"]["u1"] == [[MS0, 0], [MS0 + 1, 0.0]]


def test_continuation_at_a_legal_boundary_and_inconsistent_later_pages():
    nxt = "2026-01-05T00:30:00Z"
    ms_nxt = MS0 + 30 * 60_000

    def good(h, a):
        if a["from"] == to_z(T0):
            return _page(a, complete=False, next_from=nxt, series={"u1": [[MS0, 1.0]]})
        return _page(a, series={"u1": [[ms_nxt, 2.0]]})       # the sample AT next_from belongs to the next page

    ans = sd.fetch(good, "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")
    assert ans["series"]["u1"] == [[MS0, 1.0], [ms_nxt, 2.0]]

    def leaks(h, a):   # first page holds a sample at/after its own next_from: overlap
        return _page(a, complete=False, next_from=nxt, series={"u1": [[ms_nxt, 1.0]]})

    with pytest.raises(sd.PageError, match="outside the page window"):
        sd.fetch(leaks, "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")

    for change in ({"snapshot": "B"}, {"source": "timescale"}, {"points_total": 2}, {"uuid_var": "p"}):
        def mixed(h, a, change=change):
            if a["from"] == to_z(T0):
                return _page(a, complete=False, next_from=nxt)
            return _page(a, series={"u1": []}, **change)
        with pytest.raises(sd.PageError, match="differs from the first page"):
            sd.fetch(mixed, "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")


def to_z(t):
    from open_fdd.nf.client import to_iso_z
    return to_iso_z(t)


def test_multi_page_join_and_offset_substitution():
    pts = {"u1": _pt("u1"), "u2": _pt("u2")}

    def two(h, a, dup=False):
        off = int(a["pointOffset"])
        u = "u1" if (off == 0 or dup) else "u2"
        return _page(a, points={u: pts[u]}, points_total=2, point_offset=off, series={u: [[MS0, float(off)]]},
                     next_point_offset=1 if off == 0 else None, **({} if off == 0 else {"rows": None, "vars": None}))

    ans = sd.fetch(two, "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")
    assert ans["series"] == {"u1": [[MS0, 0.0]], "u2": [[MS0, 1.0]]} and ans["calls"] == 2
    with pytest.raises(sd.PageError, match="repeated from an earlier point page"):
        sd.fetch(lambda h, a: two(h, a, dup=True), "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")


def test_incompatible_hook_response_is_rejected():
    """A pre-5.0.20 / foreign answer without the envelope fields never merges silently."""
    legacy = lambda h, a: {"ok": True, "kind": "select", "vars": ["uuid"], "rows": [], "snapshot": "A",  # noqa: E731
                           "points": {"u1": _pt("u1")}, "series": {"u1": [[MS0, 1.0]]}, "complete": True}
    with pytest.raises(sd.PageError):
        sd.fetch(legacy, "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")


def _rdf(pages):
    def hook(h, a):
        return pages[int(a.get("offset") or 0)](a)
    return hook


def test_rdf_turtle_pages_must_join_exactly():
    text = "@prefix x: <urn:x#> .\nx:a x:b \"\U0001F600\" .\n"          # one astral char = 2 UTF-16 units
    n = len(text.encode("utf-16-le")) // 2
    cut = 10
    env = {"ok": True, "snapshot": "S", "total_chars": n, "base": "urn:b:"}
    good = {0: lambda a: {**env, "offset": 0, "turtle": text[:cut], "next_offset": cut},
            cut: lambda a: {**env, "offset": cut, "turtle": text[cut:], "next_offset": None}}
    assert sd.rdf_turtle(_rdf(good)) == (text, "urn:b:")
    gap = {**good, 0: lambda a: {**env, "offset": 0, "turtle": text[:cut - 1], "next_offset": cut}}
    with pytest.raises(sd.PageError, match="does not follow"):
        sd.rdf_turtle(_rdf(gap))
    short = {**good, cut: lambda a: {**env, "offset": cut, "turtle": text[cut:-1], "next_offset": None}}
    with pytest.raises(sd.PageError, match="total_chars"):
        sd.rdf_turtle(_rdf(short))
    changed = {**good, cut: lambda a: {**env, "snapshot": "T", "offset": cut, "turtle": text[cut:], "next_offset": None}}
    with pytest.raises(sd.PageError, match="snapshot"):
        sd.rdf_turtle(_rdf(changed))
    wrong = {**good, cut: lambda a: {**env, "offset": 0, "turtle": text[cut:], "next_offset": None}}
    with pytest.raises(sd.PageError, match="offset"):
        sd.rdf_turtle(_rdf(wrong))
    with pytest.raises(sd.PageError, match="receipt"):
        sd.rdf_turtle(_rdf({0: lambda a: {"ok": True, "offset": 0, "next_offset": None}}))


def test_bucketed_fetch_pages_on_epoch_bucket_boundaries():
    """A bucket split across two time pages would come back twice under one timestamp (5.0.20)."""
    seen = []

    def hook(h, a):
        seen.append((a["from"], a["to"]))
        return _page(a, series={"u1": []})

    sd.fetch(hook, "SELECT ?uuid WHERE {}", T0 + timedelta(minutes=2), T0 + timedelta(minutes=58), bucket="5 minutes",
             page_days=0.0123)
    assert seen[0][0] == "2026-01-05T00:00:00Z" and seen[-1][1] == "2026-01-05T01:00:00Z"
    for f, t in seen:
        for x in (f, t):
            assert int(datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()) % 300 == 0, x


def test_a_point_with_no_samples_answers_an_empty_series():
    """{"u1": []} is a point with no samples in the window: valid, and distinct from a missing series entry."""
    got = sd.fetch(_one(series={"u1": []}), "SELECT ?uuid WHERE {}", T0, T1, bucket="raw")
    assert got is not None
