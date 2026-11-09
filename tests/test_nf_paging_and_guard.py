"""5.0.6 (#1550): the Python pagers (scripts/nf/nf_paging.py, open_fdd/nf/client.py), the doctor / orphan scan on a
>500-record site, and the installer guard (hand-edited files on the box).

Fake NF servers only; nothing here talks to a real box.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from open_fdd.nf.client import NFClient, NFError, page_all as client_page_all
from test_nf_app_install import Clock, doctor_nf, fake, install_args, make_manifest, sync

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nf_paging", ROOT / "scripts" / "nf" / "nf_paging.py")
nfp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nfp)


# ---------------------------------------------------------------- fake NF point/query (offset paging, like NF 3.10.x)

def rec(uuid: str, **extra) -> dict:
    return {"uuid": uuid, "name": uuid, "layer": "model", "pointType": "POINT", "attrs": {"markers": "point"}, **extra}


def filler(prefix: str, n: int) -> list[dict]:
    return [rec(f"{prefix}-{i:04d}") for i in range(n)]


SITE = rec("m-site", pointType="SITE", name="site-a", attrs={"id": "site-a", "markers": "site", "latitude": 43.07, "longitude": -89.4})
MODEL_994 = [*filler("a", 900), SITE, rec("m-equip", pointType="EQUIPMENT"), *filler("z", 92)]


def offset_server(all_: list[dict], max_size: int = 10**9, log: list | None = None):
    def serve(body: dict) -> dict:
        if log is not None:
            log.append(dict(body))
        off = int(body.get("pageOffset") or 0)
        size = min(int(body.get("pageSize") or 100), max_size)
        return {"points": all_[off:off + size], "totalCount": str(len(all_))}
    return serve


def token_server(all_: list[dict], size: int = 500):
    def serve(body: dict) -> dict:
        at = int(body["pageToken"][1:]) if body.get("pageToken") else 0
        return {"points": all_[at:at + size], **({"nextPageToken": f"t{at + size}"} if at + size < len(all_) else {})}
    return serve


def old_query(serve, body: dict) -> list[dict]:
    """The 5.0.5 loops, in behaviour: follow ONLY nextPageToken."""
    out, token = [], ""
    while True:
        r = serve({"pageSize": 500, **body, **({"pageToken": token} if token else {})})
        out.extend(r.get("points") or [])
        token = r.get("nextPageToken") or ""
        if not token:
            return out


# ---------------------------------------------------------------- the pagers

@pytest.mark.parametrize("pager,error", [(nfp.page_all, nfp.PagingError), (client_page_all, NFError)])
def test_pagers_read_a_994_record_model_by_offset(pager, error):
    serve = offset_server(MODEL_994)
    assert [r["pointType"] for r in old_query(serve, {"layer": "model"}) if r["pointType"] != "POINT"] == [], "old loop: 0 sites"
    got = pager(lambda p: serve({"layer": "model", **p}), "points")
    assert len(got) == 994 and any(r["pointType"] == "SITE" for r in got)


@pytest.mark.parametrize("pager,error", [(nfp.page_all, nfp.PagingError), (client_page_all, NFError)])
def test_pagers_tokens_caps_size_caps_and_loud_failures(pager, error):
    f = lambda serve: (lambda p: serve(p))  # noqa: E731
    assert len(pager(f(token_server(filler("t", 1234))), "points")) == 1234                 # token, no totalCount
    assert len(pager(f(offset_server(MODEL_994, max_size=100)), "points")) == 994           # server caps pageSize
    assert len(pager(f(offset_server(filler("k", 1000))), "points")) == 1000                # exact multiple
    assert pager(f(offset_server([])), "points") == []
    with pytest.raises(error, match=r"paging cap reached after 1000 records.*totalCount 2500.*partial result"):
        pager(f(offset_server(filler("c", 2500))), "points", max_records=1000)
    with pytest.raises(error, match="repeated records already read"):
        pager(lambda p: {"points": filler("i", 500), "totalCount": "994"}, "points")        # ignores pageOffset
    with pytest.raises(error, match="read 500 of totalCount 994"):
        pager(lambda p: {"points": [] if p.get("pageOffset") else filler("e", 500), "totalCount": "994"}, "points")
    with pytest.raises(error, match="nextPageToken repeated|repeated records"):
        pager(lambda p: {"points": [rec(f"r{p.get('pageToken', '')}x")], "nextPageToken": "same"}, "points")


def test_pager_error_for_scripts_is_a_system_exit():
    assert issubclass(nfp.PagingError, SystemExit)


def test_client_query_all_and_sites_page_by_offset():
    c = NFClient.__new__(NFClient)
    log: list = []
    serve = offset_server(MODEL_994, log=log)
    c.post = lambda path, body: serve(body)
    got = c.query_all("model", {"field": {"property": "siteRef", "text": "x"}})
    assert len(got) == 994 and [b.get("pageOffset", 0) for b in log] == [0, 500]
    assert log[0]["structuredQuery"]["field"]["text"] == "x" and log[0]["layer"] == "model"
    sites = [{"id": f"s{i}", "latitude": 1, "longitude": 2} for i in range(1100)]
    urls: list[str] = []

    def get(path: str) -> dict:
        urls.append(path)
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(path).query)
        off = int(q.get("pageOffset", ["0"])[0])
        return {"sites": sites[off:off + int(q["pageSize"][0])], "totalCount": str(len(sites))}

    c.get = get
    assert len(c.sites()) == 1100 and urls[1].endswith("pageSize=500&pageOffset=500")


# ---------------------------------------------------------------- nf_app_sync on a >500-record site

def paged_nf(nf, model: list[dict] | None = None, automation: list[dict] | None = None, default: list[dict] | None = None):
    real = nf.call

    def call(method, path, body=None, ok_404=False):
        if path == "/api/v1/point/query":
            nf.log.append((method, path))
            data = {"model": model, "automation": automation, "default": default}.get(body.get("layer"))
            if data is not None:
                return offset_server(data)(body)
        return real(method, path, body, ok_404)

    nf.call = call
    return nf


def test_orphan_scan_sees_automation_points_past_500():
    auto = [{"uuid": f"p{i:04d}", "name": "x", "attrs": {"application_id": "keep"}} for i in range(700)]
    auto.append({"uuid": "zz-orphan", "name": "oa_x", "attrs": {"application_id": "gone"}})
    nf = paged_nf(fake(), automation=auto)
    assert len(sync.automation_points(nf)) == 701
    orphans = sync.orphan_points(sync.automation_points(nf), {"keep"}, set())
    assert [p["uuid"] for p in orphans] == ["zz-orphan"], "5.0.5 read 500 and would have missed it"


def test_doctor_weather_coords_find_a_site_at_position_900(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path)
    paged_nf(nf, model=MODEL_994)
    sync.cmd_doctor(nf, m)
    assert "modeled Haystack site on the model layer" in capsys.readouterr().out


def test_doctor_weather_coords_prefer_the_app_options(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path)
    nf.store["new-app"]["options"] += [{"name": "latitude", "value": {"double": 43.07}}, {"name": "longitude", "value": {"string": "-89.4"}}]
    sync.cmd_doctor(nf, m)
    assert "[PASS] weather coords: app options latitude/longitude" in capsys.readouterr().out
    # unset options (0 / 0 or empty) do not count
    nf.store["new-app"]["options"][-2:] = [{"name": "latitude", "value": {"double": 0}}, {"name": "longitude", "value": {"double": 0}}]
    assert sync.option_coords(nf.store["new-app"]) is None


def test_fdd_freshness_reads_result_points_beyond_the_first_500():
    import datetime
    now = datetime.datetime(2026, 11, 9, 15, 0, tzinfo=datetime.timezone.utc)
    raw = [{"uuid": f"a{i:04d}", "attrs": {"markers": "his"}, "latestValue": {"ts": "2026-11-09T14:59:00Z"}} for i in range(600)]
    fresh = {"uuid": "z-res", "attrs": {"ruleRef": "R", "fddStatus": "ok", "fddLastRun": "2026-11-09T14:30:00Z"}, "latestValue": {"ts": "2026-11-09T14:30:00Z"}}
    nf = paged_nf(fake(), default=[*raw, fresh])
    lvl, text = sync.fdd_freshness(nf, 3600, now)
    assert lvl == "pass", text


def test_a_paging_failure_in_the_scan_is_reported_not_swallowed(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path)
    real = nf.call
    nf.call = lambda method, path, body=None, ok_404=False: (
        {"points": filler("q", 500), "totalCount": "994"} if path == "/api/v1/point/query" and body.get("layer") == "model"
        else real(method, path, body, ok_404))
    sync.cmd_doctor(nf, m)
    out = capsys.readouterr().out
    assert "[FAIL] weather coords: could not read the model layer completely" in out and "repeated records" in out


# ---------------------------------------------------------------- installer guard

def pushed_box(tmp_path, clk=None):
    """A box after one real push of the test manifest: (manifest, fake NF)."""
    m, nf, clk = make_manifest(tmp_path), fake(), clk or Clock()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    return m, nf, clk


def writes_since(nf, n: int) -> list[tuple[str, str]]:
    return [x for x in nf.log[n:] if x[0] in ("POST", "PATCH", "DELETE") and x[1] != "/api/v1/point/query"]


def test_every_push_records_a_manifest_of_what_it_wrote(tmp_path):
    m, nf, _ = pushed_box(tmp_path)
    info = json.loads(nf.files[("new-app", "/static/version.json")])
    assert set(info["files"]) == {"/package.json", "/hooks/x.js"}
    assert info["files"]["/hooks/x.js"] == sync.sha256_hex(nf.files[("new-app", "/hooks/x.js")])
    assert info["version"] == "9.9.9"


def test_a_second_push_with_no_hand_edits_goes_ahead(tmp_path, capsys):
    m, nf, clk = pushed_box(tmp_path)
    capsys.readouterr()
    (tmp_path / "x.js").write_text("// hook v2\n")           # the repo moved on, the box was not touched
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    out = capsys.readouterr().out
    assert "no hand-edited files on the box" in out and "STOPPED" not in out
    assert nf.files[("new-app", "/hooks/x.js")] == b"// hook v2\n"


def test_a_hand_edited_file_stops_the_push_before_anything_is_written(tmp_path, capsys):
    m, nf, clk = pushed_box(tmp_path)
    capsys.readouterr()
    nf.files[("new-app", "/hooks/x.js")] = b"// hotfix made on the box\n"
    before = len(nf.log)
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == sync.EXIT_DRIFT == 4
    out = capsys.readouterr().out
    assert ("push: STOPPED: 1 file(s) on the box differ from what was last pushed (hand-edited on the box):\n"
            "  /hooks/x.js\n") in out
    assert "nothing was written" in out and "--save-remote DIR" in out and "--force" in out
    assert "/package.json" not in out.split("STOPPED")[1], "only the edited file is listed"
    assert writes_since(nf, before) == [], "no write of any kind"
    assert nf.files[("new-app", "/hooks/x.js")] == b"// hotfix made on the box\n"


def test_force_overwrites_the_edited_files_and_says_which(tmp_path, capsys):
    m, nf, clk = pushed_box(tmp_path)
    capsys.readouterr()
    nf.files[("new-app", "/hooks/x.js")] = b"// hotfix\n"
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True) == 0
    out = capsys.readouterr().out
    assert "push: --force: overwriting 1 file(s) on the box that differ from what was last pushed:\n  /hooks/x.js" in out
    assert nf.files[("new-app", "/hooks/x.js")] == b"// hook\n"


def test_save_remote_downloads_the_edited_box_copies_first(tmp_path, capsys):
    m, nf, clk = pushed_box(tmp_path)
    nf.files[("new-app", "/hooks/x.js")] = b"// hotfix\n"
    keep = tmp_path / "box-copies"
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, save_remote=keep) == sync.EXIT_DRIFT   # still stops
    assert (keep / "hooks" / "x.js").read_bytes() == b"// hotfix\n"
    assert not (keep / "package.json").exists(), "only edited files are saved"
    assert f"push: saved 1 box copies of the files below to {keep}" in capsys.readouterr().out
    assert nf.files[("new-app", "/hooks/x.js")] == b"// hotfix\n"
    # with --force it saves, then overwrites
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True, save_remote=keep) == 0
    assert nf.files[("new-app", "/hooks/x.js")] == b"// hook\n"


def test_a_file_added_on_the_box_that_the_last_push_never_wrote_counts_as_edited(tmp_path):
    m, nf, clk = pushed_box(tmp_path)
    info = json.loads(nf.files[("new-app", "/static/version.json")])
    del info["files"]["/package.json"]
    nf.files[("new-app", "/static/version.json")] = json.dumps(info).encode()
    nf.files[("new-app", "/package.json")] = b'{"hand": "made"}'
    drift = sync.find_drift(nf, m)
    assert drift["drifted"] == ["/package.json"] and drift["baseline"] == "manifest"


def test_no_manifest_warns_and_compares_with_the_repo_copy(tmp_path, capsys):
    m, nf = make_manifest(tmp_path), fake()
    app = nf.app_rec("new-app", "9.9.8")
    nf.store["new-app"] = app
    nf.files[("new-app", "/static/version.json")] = json.dumps({"version": "9.9.8"}).encode()   # an older install: no files, no commit
    nf.files[("new-app", "/package.json")] = sync.deploy_bytes(m, "package.json")              # identical to the repo
    nf.files[("new-app", "/hooks/x.js")] = b"// older or hand-edited\n"
    clk = Clock()
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == sync.EXIT_DRIFT
    out = capsys.readouterr().out
    assert ("push: WARNING: the box has no push manifest (it was installed by an older release), so a hand edit cannot be "
            "told from an older version; comparing each file on the box with this repo's copy") in out
    assert "push: STOPPED: 1 file(s) on the box differ from this repo's copy (hand-edited on the box):\n  /hooks/x.js" in out
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True) == 0
    assert "--force: overwriting 1 file(s) on the box that differ from this repo's copy" in capsys.readouterr().out
    # the push that just ran wrote the manifest: the next one is judged exactly
    assert "files" in json.loads(nf.files[("new-app", "/static/version.json")])


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_no_manifest_uses_the_installed_commit_so_an_older_release_is_not_a_hand_edit(tmp_path, capsys):
    m = make_manifest(tmp_path)

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "old release")
    commit = git("rev-parse", "HEAD")
    nf = fake()
    nf.store["new-app"] = nf.app_rec("new-app", "9.9.9")
    nf.files[("new-app", "/static/version.json")] = json.dumps({"version": "9.9.9", "commit": commit}).encode()
    nf.files[("new-app", "/package.json")] = (tmp_path / "package.json").read_bytes()
    nf.files[("new-app", "/hooks/x.js")] = b"// hook\r\n"                   # an older upload with CRLF: same text
    (tmp_path / "x.js").write_text("// hook v2 in the working tree\n")      # the repo moved on since that release
    d = sync.find_drift(nf, m)
    assert d["baseline"] == "commit" and d["drifted"] == [], "the box equals the commit it was installed from"
    nf.files[("new-app", "/hooks/x.js")] = b"// hand edit\n"
    d = sync.find_drift(nf, m)
    assert d["drifted"] == ["/hooks/x.js"]
    clk = Clock()
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == sync.EXIT_DRIFT
    out = capsys.readouterr().out
    assert f"comparing each file on the box with the copy in the installed commit {commit[:7]}" in out
    assert f"differ from the copy in the installed commit {commit[:7]}" in out


def test_install_stops_on_drift_without_verifying_or_touching_the_box(tmp_path, capsys):
    m, nf, clk = pushed_box(tmp_path)
    nf.files[("new-app", "/hooks/x.js")] = b"// hotfix\n"
    capsys.readouterr()
    before = len(nf.log)
    rc = sync.cmd_install(nf, m, install_args(), clk, clk.sleep)
    out = capsys.readouterr().out
    assert rc == 4
    assert "install: STOPPED (exit 4): hand-edited files on the box (see above); the box was not changed" in out
    assert writes_since(nf, before) == [] and nf.starts == [], "no write, no verify run"
    assert sync.cmd_install(nf, m, install_args("--force"), clk, clk.sleep) == 0
    a = sync.build_parser().parse_args(["install", "x.json", "--force", "--save-remote", "d"])
    assert a.force and a.save_remote == Path("d")


def test_doctor_lists_hand_edited_files_read_only_and_does_not_fail(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path, sites=[{"id": "s", "latitude": 43.0, "longitude": -89.0}],
                      redirect=(302, {"Location": "https://h/api/v1/apps/static/new-app/"}), timescale=True)
    clk = Clock()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True) == 0          # writes the manifest
    capsys.readouterr()
    assert sync.cmd_doctor(nf, m) == 0
    assert "[PASS] hand edits: none (2 files match what was last pushed)" in capsys.readouterr().out
    nf.files[("new-app", "/hooks/x.js")] = b"// hotfix\n"
    before = len(nf.log)
    assert sync.cmd_doctor(nf, m) == 0, "a hand edit is a warning, not a failed check"
    out = capsys.readouterr().out
    assert ("[WARN] hand edits: 1 file(s) on the box differ from what was last pushed (edited by hand): /hooks/x.js. "
            "The next push/install stops until you pass --force (--save-remote DIR keeps the box copies first)") in out
    assert writes_since(nf, before) == []


def test_text_files_are_uploaded_with_lf_whatever_the_checkout_line_endings(tmp_path):
    m = make_manifest(tmp_path)
    (tmp_path / "x.js").write_bytes(b"// a\r\n// b\r\n")
    assert sync.deploy_bytes(m, "x.js") == b"// a\n// b\n"
    (tmp_path / "blob.wasm").write_bytes(b"\x00\r\n\x01")
    assert sync.deploy_bytes(m, "blob.wasm") == b"\x00\r\n\x01", "binary files are untouched"


# ---------------------------------------------------------------- doctor: the timescale setting is judged like the hooks read it

@pytest.mark.parametrize("options,hooks,level,phrase", [
    ([], [], "PASS", "not configured"),
    ([{"name": "timescale", "value": {"string": json.dumps({"host": "db", "password": "pw-secret"})}}], [], "PASS", "parses and names a host"),
    ([{"name": "timescale", "value": {"string": "postgres://u:pw-secret@db/nf"}}], [], "PASS", "postgres:// URL"),
    ([{"name": "timescale", "value": {"string": "{}"}}], [], "FAIL", 'no "host" or "connectionString"'),
    ([{"name": "timescale", "value": {"string": '{"host": "db", "password": "pw-secret"'}}], [], "FAIL", "not valid JSON"),
    ([{"name": "timescale", "value": {}}], [], "WARN", "has no value"),
    ([{"name": "engine", "value": {"string": "timescale"}}], [], "FAIL", "no Timescale connection setting was found"),
    ([], [{"id": "fdd", "config": {"timescale": {"host": "db"}}}], "WARN", "does not store hook config"),
])
def test_timescale_check(options, hooks, level, phrase):
    lvl, text = sync.timescale_check({"options": options, "hooks": hooks})
    assert lvl == level and phrase in text, text
    assert "pw-secret" not in text, "the value is never printed"


def test_http_500_on_file_read_stops_the_guard(tmp_path, capsys):
    """#7: only 404 means missing. A 500 must stop the push, not look like an absent file."""
    m, nf, clk = pushed_box(tmp_path)
    capsys.readouterr()
    real_read = nf.read_file

    def boom(app_id, nf_path):
        if nf_path == "/hooks/x.js":
            raise sync.ApiError("GET files -> HTTP 500: boom", 500, "http")
        return real_read(app_id, nf_path)

    nf.read_file = boom
    before = len(nf.log)
    with pytest.raises(sync.ApiError, match="HTTP 500"):
        sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep)
    assert writes_since(nf, before) == [], "no write when a file read failed"


def test_console_ok_404_only_swallows_404_not_500(monkeypatch):
    """Unit: Console.call with ok_404=True returns None on 404 and raises on 500."""
    import email.message
    import io
    import urllib.error
    import urllib.request as ureq

    c = sync.Console("https://nf.example", "user", "pass")

    def urlopen404(req, timeout=0, context=None):
        raise urllib.error.HTTPError(req.full_url, 404, "no", hdrs=email.message.Message(), fp=io.BytesIO(b"missing"))

    monkeypatch.setattr(ureq, "urlopen", urlopen404)
    assert c.call("GET", "/api/v1/apps/a/files/hooks/x.js", ok_404=True) is None

    def urlopen500(req, timeout=0, context=None):
        raise urllib.error.HTTPError(req.full_url, 500, "err", hdrs=email.message.Message(), fp=io.BytesIO(b"boom"))

    monkeypatch.setattr(ureq, "urlopen", urlopen500)
    with pytest.raises(sync.ApiError) as ei:
        c.call("GET", "/api/v1/apps/a/files/hooks/x.js", ok_404=True)
    assert ei.value.status == 500



def test_remote_version_info_http_500_propagates():
    """HTTP 500 on /static/version.json must raise, not fall back to repo baseline."""
    class Boom:
        def read_file(self, app_id, nf_path):
            raise sync.ApiError("GET files -> HTTP 500", 500, "http")

    with pytest.raises(sync.ApiError) as ei:
        sync.remote_version_info(Boom(), "app")
    assert ei.value.status == 500


def test_remote_version_info_missing_is_empty():
    class Missing:
        def read_file(self, app_id, nf_path):
            return None

    assert sync.remote_version_info(Missing(), "app") == {}


def test_doctor_sites_adapter_forwards_page_token(tmp_path, capsys):
    """#10: weather_coords Sites fetch must forward pageToken when the server uses tokens."""
    m, nf = doctor_nf(tmp_path)
    urls = []
    pages = [
        {"sites": [{"id": "a", "latitude": 0, "longitude": 0}], "nextPageToken": "tok2"},
        {"sites": [{"id": "b", "latitude": 43.07, "longitude": -89.4}], "nextPageToken": ""},
    ]

    real = nf.call

    def call(method, path, body=None, ok_404=False):
        if path.startswith("/api/v1/sites"):
            urls.append(path)
            idx = 0 if "pageToken=" not in path else 1
            # first call has no token; second must carry pageToken=tok2
            if "pageToken=" in path:
                assert "pageToken=tok2" in path
                return pages[1]
            return pages[0]
        return real(method, path, body, ok_404)

    nf.call = call
    lvl, text = sync.weather_coords_source(nf, nf.store.get("new-app"))
    assert lvl == "pass" and "NF Sites API has coordinates" in text
    assert any("pageToken=tok2" in u for u in urls), urls

