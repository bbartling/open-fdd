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
               "series": {u: page}, "complete": not rest,
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

        def point_data(self, uuids, start, end, window_sec=300):
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