"""open_fdd.nf against the real mock NF server (nf-app/dev/mock-nf.mjs) and a small fake NF.

The mock serves two sites in degF / inH2O / cfm / % and some unitless points; the fake NF is a
local HTTP server used to exercise paging, retries and both auth schemes.
Run:  python -m pytest tests/test_open_fdd_nf.py -q   (needs node on PATH for the mock tests)
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.nf import NFClient, NFError  # noqa: E402
from open_fdd.nf import cli as nfcli  # noqa: E402
from open_fdd.nf.client import parse_nf_ts, sample_value, to_iso_z  # noqa: E402
from open_fdd.nf.export import csv_frames, parse_column, read_csv_export, read_turtle  # noqa: E402
from open_fdd.nf.model import (bind_equipment, equipment_frames, load_catalog, load_model,  # noqa: E402
                               role_scales, si_plan_for, Point)
from open_fdd.nf.rules import run_rules  # noqa: E402
from open_fdd.nf.units import to_si  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


# ---------------------------------------------------------------------------- units
def test_units_match_the_app_table():
    assert to_si(212, "°F").value == pytest.approx(100.0)
    assert to_si(1, "inH₂O").value == pytest.approx(249.0889)
    assert to_si(100, "cfm").value == pytest.approx(47.19474)
    assert to_si(50, "%").quantity == "percent"
    assert to_si(1, "in wc").unit == "Pa"
    assert to_si(1, "") is None and to_si(1, "furlongs") is None
    assert to_si(float("nan"), "°F") is None


def test_sample_value_and_timestamps():
    assert sample_value({"double": 1.5}) == 1.5
    assert sample_value({"boolean": True}) == 1.0
    assert sample_value({"unsigned": "7"}) == 7.0
    assert sample_value({}) is None
    t = parse_nf_ts("2026-11-05T13:05:00.123456789Z")
    assert t.tzinfo is not None and t.microsecond == 123456
    assert to_iso_z(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)) == "2026-01-02T03:04:05Z"


# ---------------------------------------------------------------------------- fake NF
class FakeNF:
    """Tiny NF: scripted responses per path; records requests."""

    def __init__(self):
        self.log: list[tuple[str, str, dict | None, dict]] = []
        self.handlers: dict[str, list] = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                path = self.path.split("?")[0]
                outer.log.append((method, self.path, body, dict(self.headers)))
                queue = outer.handlers.get(path) or []
                resp = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else (404, {"error": "none"}))
                if callable(resp):
                    resp = resp(body, dict(self.headers), self.path)
                code, payload = resp
                raw = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fake():
    f = FakeNF()
    yield f
    f.close()


def quick(url, **kw):
    return NFClient(url, sleep=lambda s: None, **kw)


def test_query_all_pages(fake):
    fake.handlers["/api/v1/point/query"] = [
        (200, {"points": [{"uuid": "a"}], "nextPageToken": "t1"}),
        (200, {"points": [{"uuid": "b"}], "nextPageToken": "t2"}),
        (200, {"points": [{"uuid": "c"}]}),
    ]
    got = quick(fake.url).query_all("model", {"field": {"property": "siteRef", "text": "x"}})
    assert [p["uuid"] for p in got] == ["a", "b", "c"]
    bodies = [b for _, _, b, _ in fake.log]
    assert bodies[0]["layer"] == "model" and "pageToken" not in bodies[0]
    assert bodies[1]["pageToken"] == "t1" and bodies[2]["pageToken"] == "t2"
    assert bodies[0]["structuredQuery"]["field"]["property"] == "siteRef"


def test_query_all_rejects_repeated_page_token(fake):
    fake.handlers["/api/v1/point/query"] = [(200, {"points": [{"uuid": "a"}], "nextPageToken": "same"})]
    with pytest.raises(NFError, match="repeated pageToken"):
        quick(fake.url).query_all("default")


def test_retries_transient_403_then_succeeds(fake):
    fake.handlers["/api/v1/platform/info"] = [(403, None), (503, {"e": 1}), (200, {"version": "x"})]
    assert quick(fake.url).platform_info() == {"version": "x"}
    assert len(fake.log) == 3


def test_does_not_retry_a_real_client_error_and_gives_up(fake):
    fake.handlers["/api/v1/platform/info"] = [(404, {"error": "no"})]
    with pytest.raises(NFError) as e:
        quick(fake.url).platform_info()
    assert e.value.status == 404 and len(fake.log) == 1
    fake.log.clear()
    fake.handlers["/api/v1/sites"] = [(502, None)]
    with pytest.raises(NFError):
        quick(fake.url, retries=3).sites()
    assert len(fake.log) == 3


def test_portal_token_flow_with_retry_and_refresh(fake):
    state = {"tokens": 0}

    def token(body, headers, path):
        state["tokens"] += 1
        if state["tokens"] == 1:
            return 403, None  # the known empty-body 403
        return 200, {"accessToken": f"tok{state['tokens']}", "expiresIn": 3600}

    def info(body, headers, path):
        return (200, {"ok": True}) if headers.get("Authorization") == "Bearer tok2" else (401, {"error": "stale"})

    fake.handlers["/api/v1/auth/token"] = [token]
    fake.handlers["/api/v1/platform/info"] = [info]
    c = quick(fake.url, auth=("portal", "id", "secret"))
    assert c.platform_info() == {"ok": True}
    tok_calls = [b for m, p, b, h in fake.log if p == "/api/v1/auth/token"]
    assert tok_calls[-1] == {"client_id": "id", "client_secret": "secret", "grant_type": "client_credentials"}
    # expiry: force it, a new token is fetched and the old one is not reused
    c._token_exp = 0
    fake.handlers["/api/v1/platform/info"] = [lambda b, h, p: (200, {"auth": h.get("Authorization")})]
    assert c.platform_info() == {"auth": "Bearer tok3"}


def test_portal_401_triggers_one_refresh(fake):
    seq = iter(["tokA", "tokB"])
    fake.handlers["/api/v1/auth/token"] = [lambda b, h, p: (200, {"access_token": next(seq)})]
    fake.handlers["/api/v1/sites"] = [lambda b, h, p: (200, {"sites": [{"id": "s"}]}) if h["Authorization"] == "Bearer tokB" else (401, {})]
    assert quick(fake.url, auth=("portal", "i", "s")).sites() == [{"id": "s"}]


def test_basic_auth_header(fake):
    fake.handlers["/api/v1/platform/info"] = [lambda b, h, p: (200, {"auth": h.get("Authorization")})]
    got = quick(fake.url, auth=("basic", "admin", "pw")).platform_info()
    assert got["auth"] == "Basic YWRtaW46cHc="
    with pytest.raises(NFError):
        NFClient(fake.url, auth=("bearer", "x", "y"))


def test_from_env_picks_url_and_credentials(tmp_path):
    envf = tmp_path / "nf.env"
    envf.write_text("NF_LAN_URL=http://lan.test\nNFURL=https://portal.test/\nNF_CLIENT_ID=a\nNF_CLIENT_SECRET=b\n",
                    encoding="utf-8")
    lan = NFClient.from_env(via="lan", env_file=envf, env={})
    portal = NFClient.from_env(via="portal", env_file=envf, env={})
    assert lan.base_url == "http://lan.test" and portal.base_url == "https://portal.test"
    assert lan.auth == ("portal", "a", "b")
    basic = NFClient.from_env(env={"NF_URL": "http://x", "NF_CONSOLE_USER": "u", "NF_CONSOLE_PASSWORD": "p"})
    assert basic.auth == ("basic", "u", "p")
    assert NFClient.from_env(env={"NFURL": "http://y"}).auth is None
    with pytest.raises(NFError, match="NF_URL"):
        NFClient.from_env(env={})


def test_point_data_batches_and_chunks(fake):
    ids = [f"u{i:03d}" for i in range(95)]
    fake.handlers["/api/v1/point/data"] = [lambda b, h, p: (200, {"data": []})]
    end = datetime(2026, 11, 1, tzinfo=timezone.utc)
    quick(fake.url).point_data(ids, end - timedelta(days=15), end, window_sec=900, method="MAX")
    reqs = [p for m, p, b, h in fake.log]
    assert len(reqs) == 3 * 3  # 15 days = 3 chunks of at most 7, 95 uuids = 3 batches of at most 40
    assert all(p.count("uuids=") <= 40 for p in reqs)
    assert "window=900s" in reqs[0] and "method=MAX" in reqs[0]


# ---------------------------------------------------------------------------- mock NF
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock_url():
    if not NODE:
        pytest.skip("node is required for the mock NF")
    port = _free_port()
    proc = subprocess.Popen([NODE, str(ROOT / "nf-app" / "dev" / "mock-nf.mjs"), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/v1/platform/info", timeout=1).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("mock NF did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def client(mock_url):
    return NFClient(mock_url)


@pytest.fixture(scope="module")
def model(client):
    return load_model(client)


@pytest.fixture(scope="module")
def window():
    end = datetime.now(timezone.utc).replace(microsecond=0)
    return end - timedelta(days=2), end


def test_client_info_and_sites(client):
    assert client.platform_info()["version"] == "mock-3.10"
    assert {s["id"] for s in client.sites()} == {"site-north", "site-south"}


def test_load_model(model):
    assert {s["name"] for s in model.sites} == {"site-north", "site-south"}
    assert len(model.equips) == 12 and not model.devices
    north = [p for p in model.points if p.site_ref == "site-north"]
    south = [p for p in model.points if p.site_ref == "site-south"]
    assert north and south and not (set(p.uuid for p in north) & set(p.uuid for p in south))
    assert all(p.tags for p in model.points)


def test_binding_is_site_scoped_and_weather_only_for_web_roles(model):
    by = {(b.site, b.equip): b for b in bind_equipment(model)}
    ahu1, rtu = by[("site-north", "AHU-1")], by[("site-south", "RTU-S1")]
    w1, w2 = ahu1.best()["web_oa_t"], rtu.best()["web_oa_t"]
    assert w1.site_ref == "site-north" and w2.site_ref == "site-south" and w1.uuid != w2.uuid
    for b in by.values():
        for role, pts in b.roles.items():
            for p in pts:
                assert p.has("weather") == role.startswith("web_")
                assert p.site_ref == b.site
    # class match outranks a marker-only match
    cat = load_catalog()
    cls_pt = Point("1", "x", "x", ["point", "fan", "run", "cmd"], "", "Number", "", "", "", "", "run-cmd", None)
    mk_pt = Point("2", "y", "y", ["point", "fan", "run", "cmd"], "", "Number", "", "", "", "", "", None)
    from open_fdd.nf.model import bind_roles
    assert bind_roles(["fan_cmd"], [mk_pt, cls_pt], cat)["fan_cmd"][0].uuid == "1"


def test_equipment_frames_si_conversion(client, model, window):
    frames = equipment_frames(client, model, *window, equip="AHU-1", site="site-north")
    assert list(frames) == [("site-north", "AHU-1")]
    df = frames[("site-north", "AHU-1")]
    assert isinstance(df.index, pd.DatetimeIndex) and str(df.index.tz) == "UTC"
    assert df.attrs["equipment_type"] == "AHU" and df.attrs["site_id"] == "site-north"
    b = df.attrs["bindings"]["discharge-air-temp"]
    raw = client.point_data([b["uuid"]], *window)[b["uuid"]]
    assert b["source_unit"] == "°F" and b["unit"] == "°C"
    raw_s = pd.Series({t: v for t, v in raw}, name="raw")
    joined = pd.concat([raw_s, df["discharge-air-temp"].rename("si")], axis=1).dropna()
    assert len(joined) > 100
    assert ((joined["raw"] - 32) * 5 / 9 - joined["si"]).abs().max() < 1e-9
    assert 0 < df["duct-static-pressure"].mean() < 500  # inH2O -> Pa (1.2 inH2O is about 300 Pa)
    assert df.attrs["role_units"]["duct-static-pressure"] == "Pa"
    # percent -> fraction for fraction roles
    assert df["outside-air-damper"].between(0, 1).all() and df["outside-air-damper"].max() > 0.1
    assert df.attrs["bindings"]["outside-air-damper"]["source_unit"] == "%"
    # 0/1 status stays 0..1
    assert df["fan-status"].between(0, 1).all()


def test_flow_cfm_to_litres_per_second(client, model, window):
    df = equipment_frames(client, model, *window, equip="VAV-1")[("site-north", "VAV-1")]
    b = df.attrs["bindings"]["zone-airflow"]
    raw = pd.Series(dict(client.point_data([b["uuid"]], *window)[b["uuid"]]), name="raw")
    both = pd.concat([raw, df["zone-airflow"].rename("si")], axis=1).dropna()
    assert b["source_unit"] == "cfm" and b["unit"] == "L/s"
    assert (both["raw"] * 0.4719474 - both["si"]).abs().max() < 1e-6


def test_unitless_fraction_command_is_skipped_not_guessed(client, model, window):
    df_all = equipment_frames(client, model, *window, equip="CT-1")
    assert not df_all or "tower-fan-cmd" not in next(iter(df_all.values())).columns
    # the plan itself, without NF
    pt = Point("u", "n", "n", ["point"], "", "Number", "", "", "", "", "", None)
    plan = si_plan_for("tower_fan_cmd", pt)
    assert plan.convert is None and "no unit" in plan.reason
    assert role_scales()["tower_fan_cmd"] == "fraction"
    # a Bool point of the same role is fine, a temperature role with the wrong unit is not
    assert si_plan_for("tower_fan_cmd", Point("u", "n", "n", ["point"], "", "Bool", "", "", "", "", "", None)).convert
    assert si_plan_for("sat", Point("u", "n", "n", ["point"], "kPa", "Number", "", "", "", "", "", None)).convert is None
    assert si_plan_for("sat", Point("u", "n", "n", ["point"], "", "Number", "", "", "", "", "", None)).convert is None


def test_equipment_frames_site_scoping(client, model, window):
    north = equipment_frames(client, model, *window, site="site-north")
    south = equipment_frames(client, model, *window, site="site-south")
    assert {k[0] for k in north} == {"site-north"} and {k[0] for k in south} == {"site-south"}
    assert ("site-south", "RTU-S1") in south and ("site-south", "RTU-S1") not in north
    wx_n = north[("site-north", "AHU-1")].attrs["bindings"]["web-outside-air-temp"]["uuid"]
    wx_s = south[("site-south", "RTU-S1")].attrs["bindings"]["web-outside-air-temp"]["uuid"]
    assert wx_n != wx_s
    assert south[("site-south", "RTU-S1")].attrs["bindings"]["web-outside-air-temp"]["source_unit"] == "°F"


def test_run_rules_finds_the_seeded_faults(client, model, window):
    frames = equipment_frames(client, model, *window, equip="AHU-1")
    table = run_rules(frames)
    assert not table.empty
    assert list(table.columns)[:7] == ["site", "equip", "rule", "status", "fault_hours", "fault_pct", "coverage"]
    assert set(table["status"]) <= {"ok", "fault", "not-assessed", "error"}
    assert (table["status"] == "fault").any()
    assert (table["status"] == "error").sum() == 0
    faults = table[table["status"] == "fault"]
    assert (faults["fault_hours"] > 0).all() and faults["coverage"].between(0, 1).all()
    na = table[table["status"] == "not-assessed"]
    assert na["fault_hours"].isna().all() and na["fault_pct"].isna().all()
    only = run_rules(frames, rules=["FC1"])
    assert list(only["rule"]) == ["FC1"]


# ---------------------------------------------------------------------------- CSV export reader
def app_style_csv(rows: int = 12) -> str:
    """The Export tab format: BOM, CRLF, timestamp + timestamp_utc + '<equip> <dis> [unit]'."""
    t0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    header = ["timestamp", "timestamp_utc", "AHU-9 discharge-air-temp [°F]", "AHU-9 fan-cmd [fraction]",
              "AHU-9 outside-air-damper [%]", "AHU-9 mystery sensor [V]"]
    lines = []
    for i in range(rows):
        t = t0 + timedelta(minutes=5 * i)
        lines.append([t.strftime("%Y-%m-%dT%H:%M:%S"), t.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                      55 + i, 1, 40 + i, 3.3])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(lines)
    return "﻿" + buf.getvalue()


def test_parse_column():
    assert parse_column("AHU-1 SAT [°F]") == ("AHU-1 SAT", "°F")
    assert parse_column("AHU-1 SAT (2)") == ("AHU-1 SAT", "")
    assert parse_column("Weather temp [%RH] (3)") == ("Weather temp", "%RH")


def test_read_csv_export_and_frames(tmp_path):
    f = tmp_path / "open-fdd_x.csv"
    f.write_bytes(app_style_csv().encode("utf-8"))
    df = read_csv_export(f)
    assert str(df.index.tz) == "UTC" and len(df) == 12 and df.shape[1] == 4
    assert df.attrs["columns"]["AHU-9 discharge-air-temp [°F]"]["unit"] == "°F"
    frames = csv_frames(f)
    assert list(frames) == [("csv", "AHU-9")]
    out = frames[("csv", "AHU-9")]
    assert out["discharge-air-temp"].iloc[0] == pytest.approx((55 - 32) * 5 / 9)
    assert out["outside-air-damper"].iloc[0] == pytest.approx(0.40)
    assert out["fan-cmd"].iloc[0] == 1.0
    assert out.attrs["window_sec"] == 300
    assert any("mystery" in k for k in out.attrs["skipped"])
    mapped = csv_frames(f, column_roles={"AHU-9 mystery sensor [V]": "ahu_sat"})
    assert "discharge-air-temp" in mapped[("csv", "AHU-9")].columns


def test_pull_csv_round_trips_through_the_reader(client, model, window, tmp_path):
    frames = equipment_frames(client, model, *window, equip="AHU-1")
    out = tmp_path / "pull.csv"
    assert nfcli.main(["pull", "--url", client.base_url, "--equip", "AHU-1", "--days", "2", "--out", str(out)]) == 0
    back = csv_frames(out)
    orig = frames[("site-north", "AHU-1")]
    got = back[("csv", "AHU-1")]
    assert {"discharge-air-temp", "fan-cmd", "outside-air-damper"} <= set(got.columns)
    assert got["outside-air-damper"].max() <= 1.0
    assert abs(got["discharge-air-temp"].mean() - orig["discharge-air-temp"].mean()) < 0.5


TTL = """@prefix ph: <https://project-haystack.org/def/ph/> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix local: <urn:test:> .
local:s1 a phIoT:site ; rdfs:label "S1" ; ph:hasTag ph:site .
local:AHU-1 a phIoT:equip ; rdfs:label "AHU-1" ; ph:hasTag local:ahu, local:equip ; phIoT:siteRef local:s1 .
local:p1 a phIoT:point ; rdfs:label "AHU-1 sat" ; ph:hasTag local:point, local:his, local:discharge, local:air, local:temp, local:sensor ;
    phIoT:siteRef local:s1 ; phIoT:equipRef local:AHU-1 ; ph:unit "\\u00b0F" ; ph:kind "Number" ;
    ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "uuid-1" ] .
"""


def test_turtle_reader_builds_a_bindable_model():
    pytest.importorskip("rdflib")
    m = read_turtle(TTL)
    assert [s["attrs"]["id"] for s in m.sites] == ["s1"]
    assert m.equips[0]["attrs"]["siteRef"] == "s1"
    assert m.points[0].uuid == "uuid-1" and m.points[0].equip_ref == "AHU-1"
    assert m.points[0].unit == "°F"
    b = bind_equipment(m)[0]
    assert "ahu" in b.kinds and b.best()["sat"].uuid == "uuid-1"


# ---------------------------------------------------------------------------- reporting + ECM hooks
def test_report_source_and_bindings(client, model, window, tmp_path):
    from open_fdd.reporting.report_template import HISTORY_SOURCES, NfSource

    assert {"nf", "nf_csv", "device_folder"} <= set(HISTORY_SOURCES) and "openfdd_api" not in HISTORY_SOURCES
    h = NfSource(equip="AHU-1", site="site-north", client=client, start=window[0], end=window[1]).load()
    assert h.equipment_id == "AHU-1" and "discharge-air-temp" in h.frame.columns
    from open_fdd.ecm_engineering.haystack_bindings import adapt_nf_model

    res = adapt_nf_model(model, site="site-north")
    assert res.ok and any(a["equipment_id"] == "AHU-1" for a in res.assets)
    ahu = next(a for a in res.assets if a["equipment_id"] == "AHU-1")
    assert any(p["canonical_role"] == "discharge-air-temp" and p["fdd_ready"] for p in ahu["points"])


def test_version_axes_are_separate():
    from open_fdd import __version__
    from open_fdd.version import app_version, manifest, package_version

    m = manifest()
    assert m["package_version"] == __version__ == package_version()
    assert __version__.startswith("4.")
    assert m["app_version"] == app_version() and (app_version() or "5").startswith("5")


# ---------------------------------------------------------------------------- CLI smoke
def run_cli(capsys, *argv):
    code = nfcli.main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_cli_info(capsys, mock_url):
    code, out, _ = run_cli(capsys, "info", "--url", mock_url)
    assert code == 0 and json.loads(out)["platform"]["version"] == "mock-3.10"


def test_cli_model_table_and_json(capsys, mock_url):
    code, out, _ = run_cli(capsys, "model", "--url", mock_url, "--site", "site-south")
    assert code == 0 and "RTU-S1" in out and "AHU-1" not in out
    code, out, _ = run_cli(capsys, "model", "--url", mock_url, "--equip", "AHU-1", "--json")
    rows = json.loads(out)
    assert rows[0]["equip"] == "AHU-1" and rows[0]["roles"]["sat"]["column"] == "discharge-air-temp"


def test_cli_pull_csv_and_env_file(capsys, mock_url, tmp_path):
    envf = tmp_path / "nf.env"
    envf.write_text(f"NF_URL={mock_url}\n", encoding="utf-8")
    out = tmp_path / "ahu.csv"
    code, so, _ = run_cli(capsys, "pull", "--env", str(envf), "--equip", "AHU-1", "--days", "1", "--out", str(out))
    assert code == 0 and "SI units" in so
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    df = pd.read_csv(out, encoding="utf-8-sig", index_col=0)
    assert df.shape[0] > 200 and any("[°C]" in c for c in df.columns)


def test_cli_pull_parquet_needs_pyarrow(capsys, mock_url, tmp_path):
    out = tmp_path / "a.parquet"
    code, _, err = run_cli(capsys, "pull", "--url", mock_url, "--equip", "AHU-1", "--days", "1", "--out", str(out))
    try:
        import pyarrow  # noqa: F401
        assert code == 0 and out.is_file()
    except ImportError:
        assert code == 2 and "pyarrow" in err


def test_cli_rules_json_and_table(capsys, mock_url):
    code, out, _ = run_cli(capsys, "rules", "--url", mock_url, "--equip", "AHU-1", "--days", "2", "--json")
    rows = json.loads(out)
    assert code == 0 and rows and all(r["status"] in ("fault", "error") for r in rows)
    code, out, _ = run_cli(capsys, "rules", "--url", mock_url, "--equip", "AHU-1", "--days", "2", "--rules", "FC1", "--all")
    assert code == 0 and "FC1" in out and "rule results" in out


def test_cli_report(capsys, mock_url, tmp_path):
    out = tmp_path / "rep"
    code, so, _ = run_cli(capsys, "report", "--url", mock_url, "--equip", "AHU-1", "--days", "2", "--out", str(out))
    assert code == 0
    assert (out / "rules.csv").is_file()
    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "Faults" in md and "not-assessed" in md


def test_cli_error_paths(capsys, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    for k in ("NF_URL", "NFURL", "NF_LAN_URL", "NF_ENV_FILE"):
        monkeypatch.delenv(k, raising=False)
    code, _, err = run_cli(capsys, "info")
    assert code == 2 and "NF_URL" in err
    code, _, err = run_cli(capsys, "info", "--url", "http://127.0.0.1:1")
    assert code == 2 and "error" in err


def test_reporting_cli_from_nf_and_csv(mock_url, tmp_path, capsys):
    from open_fdd.reporting.cli import main

    out = tmp_path / "r"
    assert main(["--nf", "--url", mock_url, "--equip", "AHU-1", "--days", "2", "--no-charts", "--out", str(out)]) == 0
    assert list(out.glob("*Engineering_Findings.json"))
    f = tmp_path / "e.csv"
    f.write_bytes(app_style_csv(40).encode("utf-8"))
    out2 = tmp_path / "r2"
    assert main(["--csv", str(f), "--no-charts", "--out", str(out2)]) == 0
    assert list(out2.glob("*Engineering_Findings.json"))
    capsys.readouterr()


# ---------------------------------------------------------------------------- analytics hook (5.0.3)
HOOK = "/api/v1/apps/open-fdd/hooks/analytics"


def _run(pid, result, state="STATE_SUCCESS"):
    events = [{"message": "noise"}, {"message": json.dumps(result)}] if result is not None else []
    return {"pid": pid, "state": state, "results": {"hook": {"events": events}}}


def _fake_hook(fake, result, *, pid="p-1", pending=0):
    """POST StartHook -> {pid}; GET runs -> RUNNING `pending` times, then the finished run with `result` logged."""
    posts: list[dict] = []
    seq = [(200, {"runs": [_run("older", {"ok": True, "tool": "x"}), _run(pid, None, "STATE_RUNNING")]})] * pending
    seq.append((200, {"runs": [_run("older", {"ok": True, "tool": "x"}), _run(pid, result)]}))

    def start(body, headers, path):
        posts.append(body)
        return 200, {"pid": pid}

    fake.handlers[HOOK] = [start]
    fake.handlers[HOOK + "/runs"] = seq
    return posts


WEEKLY = {"ok": True, "tool": "analyze_ahu_weekly_runtime", "days": 28, "rows": [
    {"siteRef": "site-a", "equipRef": "AHU-1", "equipUuid": "u-a", "week": "2026-W42", "run_hours": 50.0, "schedule_hours": 50,
     "in_schedule_hours": 50.0, "after_hours": 0.0, "partial_week": False, "mean_oat_on_c": 13.1, "schedule_source": "schedule"},
    {"siteRef": "site-b", "equipRef": "AHU-1", "equipUuid": "u-b", "week": "2026-W42", "run_hours": 50.0, "schedule_hours": 50,
     "in_schedule_hours": 50.0, "after_hours": 0.0, "partial_week": False, "mean_oat_on_c": 17.0, "schedule_source": "default"}]}


def test_analytics_tool_names_match_the_hook():
    from open_fdd.nf.analytics import SHORT, TOOLS

    js = (ROOT / "nf-app" / "hooks" / "analytics.js").read_text(encoding="utf-8")
    block = js[js.index("const TOOLS = {"):].split("};", 1)[0]
    assert set(TOOLS) == {n.strip() for n in block.split("{", 1)[1].replace("\n", " ").split(",") if n.strip()}
    assert set(SHORT.values()) == set(TOOLS)


def test_tool_args_carry_only_what_was_given():
    from open_fdd.nf.analytics import tool_args

    assert tool_args("weekly-runtime") == {"tool": "analyze_ahu_weekly_runtime"}
    assert tool_args("get_fdd_fault_timeline", site="s", equip="AHU-1", rule="CMD-1", days=2, dense=True) == {
        "tool": "get_fdd_fault_timeline", "site": "s", "equip": "AHU-1", "rule": "CMD-1", "days": 2.0, "dense": True}
    assert tool_args("explain-view", view="weekly-fan")["viewId"] == "weekly-fan"
    with pytest.raises(NFError, match="unknown tool"):
        tool_args("drop_tables")


def test_run_hook_starts_once_then_polls_runs(fake):
    posts = _fake_hook(fake, WEEKLY, pending=2)
    run = quick(fake.url).run_hook("open-fdd", "analytics", {"tool": "analyze_ahu_weekly_runtime", "days": 28}, timeout=5, poll=0)
    assert run["state"] == "STATE_SUCCESS" and run["pid"] == "p-1"
    assert posts == [{"args": {"tool": "analyze_ahu_weekly_runtime", "days": 28}}]
    methods = [m for m, *_ in fake.log]
    assert methods.count("POST") == 1 and methods.count("GET") == 3, "one StartHook, three polls (2 running + done)"
    assert "include_results=true" in fake.log[-1][1]


def test_start_hook_is_never_retried(fake):
    fake.handlers[HOOK] = [(503, {"error": "busy"}), (200, {"pid": "p-2"})]
    with pytest.raises(NFError) as e:
        quick(fake.url, retries=4).start_hook("open-fdd", "analytics", {"tool": "x"})
    assert e.value.status == 503
    assert len(fake.log) == 1, "a lost / failed StartHook must not fire a second run"


def test_run_hook_times_out_while_still_running(fake):
    _fake_hook(fake, WEEKLY, pending=10_000)
    with pytest.raises(NFError, match="still running"):
        quick(fake.url).run_hook("open-fdd", "analytics", {}, timeout=0.05, poll=0)


def test_analyze_returns_the_logged_result_and_reports_failures(fake):
    from open_fdd.nf.analytics import analyze

    _fake_hook(fake, WEEKLY)
    out = analyze(quick(fake.url), "weekly-runtime", site="site-a", days=28)
    assert [r["equipUuid"] for r in out["rows"]] == ["u-a", "u-b"]
    fake.handlers.clear()
    _fake_hook(fake, {"ok": False, "tool": "resolve_equipment_roles", "error": '"AHU-1" matches 2 equips', "candidates": [
        {"siteRef": "site-a", "equipRef": "AHU-1", "equipUuid": "u-a"}, {"siteRef": "site-b", "equipRef": "AHU-1", "equipUuid": "u-b"}]})
    with pytest.raises(NFError, match=r"matches 2 equips; candidates: site-a/AHU-1=u-a, site-b/AHU-1=u-b"):
        analyze(quick(fake.url), "roles", equip="AHU-1")
    fake.handlers.clear()
    fake.handlers[HOOK] = [(200, {"pid": "p-1"})]
    fake.handlers[HOOK + "/runs"] = [(200, {"runs": [_run("p-1", None, "STATE_FAILED")]})]
    with pytest.raises(NFError, match="STATE_FAILED"):
        analyze(quick(fake.url), "economizer")
    fake.handlers[HOOK + "/runs"] = [(200, {"runs": [_run("p-1", None)]})]
    with pytest.raises(NFError, match="without a result"):
        analyze(quick(fake.url), "economizer")


def test_cli_analyze_json_table_and_args(capsys, fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    posts = _fake_hook(fake, WEEKLY)
    code, out, _ = run_cli(capsys, "analyze", "weekly-runtime", "--url", fake.url, "--site", "site-a", "--days", "28", "--json")
    assert code == 0 and json.loads(out)["rows"][1]["equipUuid"] == "u-b"
    assert posts[-1] == {"args": {"tool": "analyze_ahu_weekly_runtime", "site": "site-a", "days": 28.0}}
    code, out, _ = run_cli(capsys, "analyze", "analyze_ahu_weekly_runtime", "--url", fake.url)
    assert code == 0 and "u-a" in out and "u-b" in out and "run_hours" in out
    assert posts[-1] == {"args": {"tool": "analyze_ahu_weekly_runtime"}}
    # fault timeline: scope + rule + dense go through as args, the table shows the states
    fake.handlers.clear()
    posts = _fake_hook(fake, {"ok": True, "tool": "get_fdd_fault_timeline", "siteRef": "site-a", "equipRef": "AHU-1", "equipUuid": "u-a",
                              "rule": "CMD-1", "source": "timeline", "approximate": False,
                              "summary": {"confirmed": 1, "ok": 2, "unknown": 1, "last_state": "ok"},
                              "timeline": [{"ts": "2026-11-06T20:05:00.000Z", "state": "confirmed"}, {"ts": "2026-11-06T21:30:00.000Z", "state": "ok"}]})
    code, out, _ = run_cli(capsys, "analyze", "fault-timeline", "--url", fake.url, "--site", "site-a", "--equip", "AHU-1",
                           "--rule", "CMD-1", "--days", "3", "--dense")
    assert code == 0 and "confirmed" in out and "last state ok" in out
    assert posts[-1] == {"args": {"tool": "get_fdd_fault_timeline", "site": "site-a", "equip": "AHU-1", "rule": "CMD-1", "days": 3.0, "dense": True}}


def test_cli_analyze_errors_and_help(capsys, fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    _fake_hook(fake, {"ok": False, "tool": "explain_missing_rcx_view", "error": "unknown view \"nope\""})
    code, _, err = run_cli(capsys, "analyze", "explain-view", "--url", fake.url, "--view", "nope")
    assert code == 2 and "unknown view" in err
    with pytest.raises(SystemExit):
        nfcli.main(["analyze", "drop_tables"])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        nfcli.main(["analyze", "--help"])
    help_text = capsys.readouterr().out
    for word in ("weekly-runtime", "--site", "--equip", "--rule", "--days", "--json", "equipUuid"):
        assert word in help_text
