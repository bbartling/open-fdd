import sys, pathlib
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import nf_common as c
import nf_tag_apply as t

SITE = {"uuid": "s", "attrs": {"id": "s1", "markers": "site"}}
VAV = {"uuid": "e1", "attrs": {"id": "V1", "siteRef": "s1", "markers": "vav,equip,hot,water,reheat"}}
AHU = {"uuid": "e2", "attrs": {"id": "A1", "siteRef": "s1", "markers": "ahu,equip"}}
P1 = {"uuid": "p1", "attrs": {"siteRef": "s1", "equipRef": "V1", "class": "discharge-air-temp-sensor",
                              "markers": "point,discharge,air,temp,sensor,his"}, "latestValue": {"ts": "x", "double": 1.5}}
P2 = {"uuid": "p2", "attrs": {"siteRef": "s1", "equipRef": "A1", "class": "discharge-air-temp-sensor",
                              "markers": "point,discharge,air,temp,sensor"}}
P3 = {"uuid": "p3", "attrs": {"siteRef": "s2", "equipRef": "V9", "markers": "point,cool,cmd,pid"}}
ALL = [SITE, VAV, AHU, P1, P2, P3]

def test_kind():
    assert [c.rec_kind(r) for r in ALL] == ["site", "equip", "equip", "point", "point", "point"]

def test_equip_tag_selection():
    assert c.equip_ids_with_tags(ALL, ["vav"]) == {"V1"}
    assert c.equip_ids_with_tags(ALL, ["equip"], site="s1") == {"V1", "A1"}
    assert c.equip_ids_with_tags(ALL, ["vav"], site="s2") == set()

def test_point_matches():
    ids = c.equip_ids_with_tags(ALL, ["vav"])
    pts = [p for p in ALL if c.rec_kind(p) == "point"]
    sel = lambda **kw: [p["uuid"] for p in pts if c.point_matches(p, **kw)]
    assert sel(equip_ids=ids, point_class="discharge-air-temp-sensor") == ["p1"]
    assert sel(site="s1") == ["p1", "p2"]
    assert sel(tags=["cool", "pid"]) == ["p3"]
    assert sel(tags=["temp"], exclude=["his"]) == ["p2"]
    assert sel(equip="A1") == ["p2"]

def test_split_and_flat_row():
    assert c.split_list(" a, b,,c ") == ["a", "b", "c"]
    r = c.flat_row(P1)
    assert r["latest_value"] == 1.5 and r["equipRef"] == "V1" and r["kind"] == "point"

def test_time_parsing():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    assert c.parse_when("24h", now) == now - timedelta(hours=24)
    assert c.parse_when("now", now) == now
    assert c.parse_ts("2026-11-01T13:10:00.051234567Z").microsecond == 51234
    assert c.parse_when("2026-11-01T00:00Z").tzinfo is not None

def test_tag_apply_guards():
    model = {"p1": P1, "p3": P3}
    ch, err = t.plan_changes([{"uuid": "p1", "attrs": {"unit": "%"}}], model, "s1", False)
    assert not err and ch[0]["diff"] == {"unit": (None, "%")}
    _, err = t.plan_changes([{"uuid": "p3", "attrs": {"unit": "%"}}], model, "s1", False)
    assert "siteRef" in err[0]
    _, err = t.plan_changes([{"uuid": "p1", "period": 300}], model, None, False)
    assert "period" in err[0]
    ch, err = t.plan_changes([{"uuid": "p1", "period": 300}], model, None, True)
    assert not err and ch[0]["period"] == "300"
    _, err = t.plan_changes([{"uuid": "p1", "attrs": {"prop_present_value": "1"}}], model, None, False)
    assert "refused" in err[0]
    _, err = t.plan_changes([{"uuid": "nope"}], model, None, False)
    assert "not in model" in err[0]

def test_env_file_never_reads_private(tmp_path, monkeypatch):
    for k in ("NFURL", "NF_CLIENT_ID", "NF_CLIENT_SECRET", "NF_ENV_FILE"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / "x.env"; f.write_text("NFURL=https://h\nNF_CLIENT_ID=i\nNF_CLIENT_SECRET='s'\n")
    assert c.settings(str(f)) == ("https://h", "i", "s")
    src = (pathlib.Path(c.__file__)).read_text()
    assert "private" not in src
