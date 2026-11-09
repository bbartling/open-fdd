"""nf_app_sync.py: auth messages, install / remove-old / uninstall, run skip logic, deps step, doctor, TLS pinning.

A fake NF (in-memory console) stands in for the box; a tiny local HTTP server answers 401s for the realm tests.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nf_app_sync", Path(__file__).resolve().parents[1] / "scripts" / "nf" / "hooks" / "nf_app_sync.py"
)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

PASSWORD = "s3cr3t-pass-value"


# ---------------------------------------------------------------- fixtures

class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def make_manifest(tmp_path: Path, replaces=("old-a", "old-b")) -> dict:
    (tmp_path / "VERSION").write_text("9.9.9\n")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"pg": "1.0.0", "sql.js": "1.0.0"}}))
    (tmp_path / "x.js").write_text("// hook\n")
    m = {
        "replaces": list(replaces),
        "application": {"id": "new-app", "name": "New App"},
        "files": {"/package.json": "package.json", "/hooks/x.js": "x.js"},
        "hooks": [
            {"id": "fdd", "mode": "MODE_SCHEDULED", "entryPoint": "/hooks/x.js", "invokeTimeout": "60s"},
            {"id": "weather", "mode": "MODE_SCHEDULED", "entryPoint": "/hooks/weather.js", "invokeTimeout": "60s"},
            {"id": "sparql", "mode": "MODE_ON_REQUEST", "entryPoint": "/hooks/sparql.js", "invokeTimeout": "60s"},
        ],
    }
    p = tmp_path / "app.json"
    p.write_text(json.dumps(m))
    return sync.manifest(p)


class FakeNF:
    """In-memory console. `log` lists (method, path) in call order."""

    def __init__(self, apps=None, deps_route=True, points=None, missing_as_nf_500=False):
        self.store = {a["id"]: a for a in (apps or [])}
        self.files: dict[tuple[str, str], bytes] = {}
        self.log: list[tuple[str, str]] = []
        self.deps_route = deps_route
        self.deps_installed = False
        self.points = points or []
        self.runs: dict[tuple[str, str], list[dict]] = {}
        self.starts: list[tuple[str, dict]] = []
        self.deleted_points: list[str] = []
        self.sites = []
        self.model: list[dict] = []
        self.probe_result = (0, {})
        # When True, a missing app file raises ApiError HTTP 500 with nf_missing_file set
        # (NF 3.10.x application/grpc + empty body signature), instead of returning None/404.
        self.missing_as_nf_500 = missing_as_nf_500

    def app_rec(self, app_id, version=None):
        return {"id": app_id, "status": "STATUS_INSTALLED", "hooks": [], "files": [],
                "options": [{"name": "version", "value": {"string": version}}] if version else []}

    def probe(self, path):
        return self.probe_result

    def call(self, method, path, body=None, ok_404=False):
        self.log.append((method, path))
        base = path.split("?")[0]
        parts = base.split("/")  # '', api, v1, apps, <id>, ...
        if base == "/api/v1/apps" and method == "GET":
            return {"applications": [dict(a) for a in self.store.values()]}
        if base == "/api/v1/apps" and method == "POST":
            self.store[body["id"]] = self.app_rec(body["id"])
            return {}
        if base == "/api/v1/sites":
            return {"sites": self.sites}
        if base == "/api/v1/point/query":
            if body.get("layer") == "automation":
                return {"points": self.points}
            return {"points": [p for p in self.model if body.get("layer") == "model"]}
        if parts[3:4] == ["apps"] and len(parts) > 4:
            app_id = parts[4]
            app = self.store.get(app_id)
            tail = parts[5:]
            if method == "DELETE" and not tail:
                del self.store[app_id]
                return {}
            if tail == ["dependencies"]:
                if not self.deps_route:
                    raise sync.ApiError("PATCH dependencies -> HTTP 404", 404)
                self.deps_installed = True
                return {}
            if tail == ["restart"]:
                return {}
            if tail[:1] == ["files"]:
                key = (app_id, "/" + "/".join(tail[1:]))
                if method == "POST":
                    self.files[key] = base64.b64decode(body)
                    return {}
                if key[1].startswith("/node_modules/"):
                    data = b"{}" if self.deps_installed else None
                else:
                    data = self.files.get(key)
                if data is None:
                    if self.missing_as_nf_500:
                        err = sync.ApiError(f"GET /api/v1/apps/{app_id}/files{key[1]} -> HTTP 500", 500, "http")
                        err.nf_missing_file = True
                        raise err
                    if ok_404:
                        return None
                    raise sync.ApiError("404", 404)
                return {"data": base64.b64encode(data).decode()}
            if method == "PATCH" and not tail:
                if body.get("updateMask") == ["configuration"]:
                    v = body["configuration"]["version"]["string"]
                    app["options"] = [{"name": "version", "value": {"string": v}}]
                return {}
            if tail == ["hooks"] and method == "POST":
                app["hooks"] = [h for h in app["hooks"] if h["id"] != body["id"]] + [body]
                return {}
            if tail[:1] == ["hooks"] and len(tail) == 2 and method == "POST":
                hook = tail[1]
                pid = 100 + len(self.starts)
                self.starts.append((hook, dict(body or {})))
                ok = self.deps_installed or hook != "fdd"
                run = {"pid": pid, "state": "STATE_SUCCESS" if ok else "STATE_FAILED", "startTime": "t",
                       "results": {"g": ({"events": []} if ok else
                                         {"error": {"message": "Cannot find package 'pg'"}, "events": []})}}
                self.runs.setdefault((app_id, hook), []).insert(0, run)
                return {"pid": pid}
            if tail[:1] == ["hooks"] and len(tail) == 3 and tail[2] == "runs":
                return {"runs": self.runs.get((app_id, tail[1]), [])}
        raise AssertionError(f"unexpected {method} {path}")

    # Console API used by the module (same surface as sync.Console)
    def apps(self):
        return [dict(a) for a in self.store.values()]

    def app(self, app_id):
        a = self.store.get(app_id)
        if not a:
            return None
        # Derive files[].path from the in-memory store so tests that poke nf.files stay consistent
        # with GET /api/v1/apps listings used by the installer guard.
        derived = [{"path": p, "size": str(len(d)), "hash": "", "mtime": ""}
                   for (aid, p), d in self.files.items() if aid == app_id]
        out = dict(a)
        out["files"] = derived
        return out

    def read_file(self, app_id, nf_path, *, known_paths=None, push_manifest=None):
        if known_paths is not None and nf_path not in known_paths:
            return None
        try:
            r = self.call("GET", f"/api/v1/apps/{app_id}/files{nf_path}", ok_404=True)
        except sync.ApiError as e:
            if getattr(e, "nf_missing_file", False) and sync.path_is_new_on_box(nf_path, known_paths, push_manifest):
                return None
            raise
        return None if r is None else base64.b64decode(r.get("data", ""))


def fake(apps=None, **kw) -> FakeNF:
    return FakeNF(apps, **kw)


def install_args(*extra: str):
    return sync.build_parser().parse_args(["install", "x.json", *extra])


# ---------------------------------------------------------------- auth messages

def test_portal_key_env_gets_a_clear_message_without_secrets():
    msg = sync.env_problem({"NF_CLIENT_ID": "id-123", "NF_CLIENT_SECRET": "sec-456", "NFURL": "https://p"}, "portal.env")
    assert "portal API key" in msg and "CONSOLE_USERNAME" in msg and "NF_CONSOLE_URL" in msg
    assert "id-123" not in msg and "sec-456" not in msg
    assert sync.env_problem({"CONSOLE_USERNAME": "u", "CONSOLE_PASSWORD": "p", "NF_CONSOLE_URL": "https://x"}) is None
    assert "NF_CONSOLE_URL missing" in sync.env_problem({"CONSOLE_USERNAME": "u", "CONSOLE_PASSWORD": "p"})
    assert "CONSOLE_USERNAME / CONSOLE_PASSWORD missing" in sync.env_problem({})


@pytest.mark.parametrize("realm,expect", [("restricted", "Caddy front door"), ("nf-", "NF itself"), (None, "unknown layer")])
def test_401_names_the_layer_that_answered(realm, expect):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(401)
            if realm:
                self.send_header("WWW-Authenticate", f'Basic realm="{realm}"')
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        c = sync.Console(f"http://127.0.0.1:{srv.server_port}", "admin", PASSWORD)
        with pytest.raises(SystemExit) as e:
            c.apps()
        text = str(e.value)
        assert "HTTP 401" in text and expect in text
        assert "CONSOLE_USERNAME" in text and "read-only" in text
        assert PASSWORD not in text and base64.b64encode(f"admin:{PASSWORD}".encode()).decode() not in text
        assert e.value.status == 401
    finally:
        srv.shutdown()


def test_auth_layer_helper():
    assert "Caddy" in sync.auth_layer('Basic realm="restricted"')
    assert "NF itself" in sync.auth_layer('Basic realm="nf-"')
    assert "unknown" in sync.auth_layer(None)


def test_doctor_reports_a_401_as_an_auth_failure(tmp_path, capsys):
    class Denied:
        def apps(self):
            raise sync.ApiError("GET /api/v1/apps -> HTTP 401: rejected by the Caddy front door", 401)

    assert sync.cmd_doctor(Denied(), make_manifest(tmp_path)) == 1
    assert "[FAIL] auth: " in capsys.readouterr().out


# ---------------------------------------------------------------- install

def test_install_orders_files_deps_hooks_restart_and_verifies(tmp_path, capsys):
    m, nf, clk = make_manifest(tmp_path), fake(), Clock()
    rc = sync.cmd_install(nf, m, install_args(), clk, clk.sleep)
    out = capsys.readouterr().out
    assert rc == 0, out
    calls = [f"{mt} {p}" for mt, p in nf.log]
    i_pkg = calls.index("POST /api/v1/apps/new-app/files/package.json")
    i_dep = calls.index("PATCH /api/v1/apps/new-app/dependencies")
    i_hook = calls.index("POST /api/v1/apps/new-app/hooks")
    i_restart = calls.index("PATCH /api/v1/apps/new-app/restart")
    i_run = calls.index("POST /api/v1/apps/new-app/hooks/fdd")
    assert i_pkg < i_dep < i_hook < i_restart < i_run, "deps after package.json, before hooks/restart/first run"
    assert [h for h, _ in nf.starts] == ["fdd", "weather"], "only scheduled hooks are verified; on-request is not started"
    assert "version.json = 9.9.9" in out and "install: OK" in out
    assert "dependencies: installed (pg, sql.js)" in out


def test_install_without_deps_route_is_reported_and_the_first_run_is_not_called_success(tmp_path, capsys):
    m, nf, clk = make_manifest(tmp_path), fake(deps_route=False), Clock()
    rc = sync.cmd_install(nf, m, install_args(), clk, clk.sleep)
    out = capsys.readouterr().out
    assert "dependencies: NOT installed" in out and "PATCH /api/v1/apps/new-app/dependencies" in out
    assert rc == 1, "the fdd first run crashed on the missing package: install must not declare success"
    assert "install: finished with problems" in out


def test_deps_step_waits_for_the_app_to_settle_then_confirms(tmp_path):
    m, clk = make_manifest(tmp_path), Clock()
    nf = fake([{"id": "new-app", "status": "STATUS_INSTALLING", "options": [], "hooks": [], "files": []}])
    polls = {"n": 0}
    orig_app = nf.app

    def app(app_id):
        polls["n"] += 1
        if polls["n"] >= 3:
            nf.store["new-app"]["status"] = "STATUS_INSTALLED"
        return orig_app(app_id)

    nf.app = app
    res = sync.install_deps(nf, m, clk, clk.sleep)
    assert res["requested"] and res["confirmed"] and res["present"] == ["pg", "sql.js"]
    assert polls["n"] >= 3 and clk.now >= 4, "waited for the app to become installed again"


def test_deps_not_visible_is_unconfirmed_not_an_error(tmp_path):
    m, clk = make_manifest(tmp_path), Clock()
    nf = fake()
    nf.store["new-app"] = nf.app_rec("new-app")
    # the route answers but the file API never shows node_modules
    nf.deps_installed = False
    orig = nf.call

    def call(method, path, body=None, ok_404=False):
        if path.endswith("/dependencies"):
            return {}
        return orig(method, path, body, ok_404)

    nf.call = call
    res = sync.install_deps(nf, m, clk, clk.sleep, probe=6)
    assert res["requested"] and not res["confirmed"] and res["error"] is None


def test_install_without_package_json_deps_skips_the_step(tmp_path):
    m = make_manifest(tmp_path)
    m["files"].pop("/package.json")
    nf = fake()
    res = sync.install_deps(nf, m)
    assert res == {"requested": False, "names": [], "present": [], "confirmed": True, "error": None}
    assert not nf.log


# ---------------------------------------------------------------- remove-old / uninstall

def predecessors():
    return [{"id": "old-a", "status": "STATUS_INSTALLED", "options": [{"name": "version", "value": {"string": "4.0.1"}}]},
            {"id": "old-b", "status": "STATUS_INSTALLED", "options": []},
            {"id": "other", "status": "STATUS_INSTALLED", "options": []}]


def pts():
    return [{"uuid": "u1", "name": "oa_x", "attrs": {"application_id": "old-a"}},
            {"uuid": "u2", "name": "oa_y", "attrs": {"application_id": "long-gone"}},
            {"uuid": "u3", "name": "kept", "attrs": {"application_id": "other"}},
            {"uuid": "u4", "name": "plain", "attrs": {}}]


def test_remove_old_without_yes_deletes_nothing_and_lists_orphans(tmp_path, capsys):
    m, nf = make_manifest(tmp_path), fake(predecessors(), points=pts())
    rc = sync.cmd_remove_old(nf, m, yes=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert not [c for c in nf.log if c[0] in ("DELETE", "PATCH", "POST") and "query" not in c[1]]
    assert set(nf.store) == {"old-a", "old-b", "other"}
    assert "would remove app old-a (version 4.0.1)" in out and "would remove app old-b" in out
    assert "u1" in out and "u2" in out and "u3" not in out and "u4" not in out, "only orphans of gone apps"
    assert "dry run: nothing was changed" in out and "delete_points" in out
    assert nf.deleted_points == []


def test_remove_old_with_yes_deletes_only_listed_predecessors(tmp_path, capsys):
    m, nf = make_manifest(tmp_path), fake(predecessors(), points=pts())
    assert sync.cmd_remove_old(nf, m, yes=True) == 0
    assert set(nf.store) == {"other"}
    assert nf.deleted_points == [], "points are only listed, never deleted"
    assert "removed app old-a" in capsys.readouterr().out


def test_install_remove_old_without_yes_is_a_dry_run(tmp_path, capsys):
    m, nf, clk = make_manifest(tmp_path), fake(predecessors(), points=pts()), Clock()
    rc = sync.cmd_install(nf, m, install_args("--remove-old"), clk, clk.sleep)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "would remove app old-a" in out and "dry run" in out
    assert {"old-a", "old-b", "other", "new-app"} <= set(nf.store)
    assert not any(c[0] == "DELETE" for c in nf.log)


def test_install_remove_old_with_yes_removes_after_verifying(tmp_path):
    m, nf, clk = make_manifest(tmp_path), fake(predecessors()), Clock()
    assert sync.cmd_install(nf, m, install_args("--remove-old", "--yes"), clk, clk.sleep) == 0
    assert set(nf.store) == {"other", "new-app"}
    i_del = [i for i, c in enumerate(nf.log) if c[0] == "DELETE"]
    i_run = nf.log.index(("POST", "/api/v1/apps/new-app/hooks/fdd"))
    assert i_del and min(i_del) > i_run, "predecessors go only after the new app verified"


def test_install_that_fails_verification_keeps_the_old_apps(tmp_path):
    m, nf, clk = make_manifest(tmp_path), fake(predecessors(), deps_route=False), Clock()
    assert sync.cmd_install(nf, m, install_args("--remove-old", "--yes"), clk, clk.sleep) == 1
    assert {"old-a", "old-b"} <= set(nf.store)


def test_uninstall_dry_run_then_yes(tmp_path, capsys):
    m = make_manifest(tmp_path)
    nf = fake([{"id": "new-app", "status": "STATUS_INSTALLED", "options": []}, *predecessors()],
              points=[{"uuid": "p1", "name": "w", "attrs": {"application_id": "new-app"}}])
    assert sync.cmd_uninstall(nf, m, yes=False) == 0
    out = capsys.readouterr().out
    assert "would remove app new-app" in out and "p1" in out and "dry run" in out
    assert "new-app" in nf.store
    assert sync.cmd_uninstall(nf, m, yes=True) == 0
    assert "new-app" not in nf.store and {"old-a", "other"} <= set(nf.store), "only the manifest's own app"


# ---------------------------------------------------------------- run skip logic

class RunNF:
    def __init__(self, result_by_hook=None):
        self.starts: list[tuple[str, dict]] = []
        self.result_by_hook = result_by_hook or {}

    def call(self, method, path, body=None, ok_404=False):
        parts = path.split("?")[0].split("/")
        hook = parts[6]
        if method == "POST":
            self.starts.append((hook, body))
            return {"pid": len(self.starts)}
        pid = len(self.starts)
        res = self.result_by_hook.get(self.starts[-1][0])
        return {"runs": [{"pid": i + 1, "state": "STATE_SUCCESS", "startTime": "t",
                          "results": {"g": res if res is not None else {"events": []}}} for i in range(pid)]}


def run_manifest():
    return {"application": {"id": "a"}, "hooks": [
        {"id": "fdd", "mode": "MODE_SCHEDULED"}, {"id": "history", "mode": "MODE_ON_REQUEST"},
        {"id": "sparql", "mode": "MODE_ON_REQUEST"}]}


def test_blanket_run_skips_on_request_hooks_without_args(capsys):
    clk, nf = Clock(), RunNF()
    rc = sync.cmd_run(nf, run_manifest(), clock=clk, sleep=clk.sleep)
    out = capsys.readouterr().out
    assert rc == 0
    assert [h for h, _ in nf.starts] == ["fdd"]
    assert "skipped (needs args): history" in out and "skipped (needs args): sparql" in out


def test_blanket_run_runs_on_request_hooks_when_args_are_given():
    clk, nf = Clock(), RunNF()
    assert sync.cmd_run(nf, run_manifest(), clock=clk, sleep=clk.sleep, args={"query": "ASK {}"}) == 0
    assert nf.starts == [("fdd", {}), ("history", {"query": "ASK {}"}), ("sparql", {"query": "ASK {}"})]


def test_explicit_hook_runs_even_if_on_request_and_ok_false_is_a_failure(capsys):
    clk = Clock()
    nf = RunNF({"sparql": {"events": [{"ts": "x", "message": json.dumps({"ok": False, "error": "args.query is required"})}]}})
    rc = sync.cmd_run(nf, run_manifest(), ["sparql"], clock=clk, sleep=clk.sleep)
    out = capsys.readouterr().out
    assert rc == 1
    assert "ok:false" in out and "args.query is required" in out and "FAILED: hook sparql" in out


def test_ok_false_in_a_result_object_is_a_failure_but_skipped_and_ok_true_are_not():
    assert sync.result_failure({"results": {"g": {"result": {"ok": False, "error": "boom"}}}}) == "boom"
    assert sync.result_failure({"results": {"g": {"result": {"ok": True, "skipped": True}}}}) is None
    assert sync.result_failure({"results": {"g": {"events": [{"message": "plain text"}]}}}) is None


def test_parse_args():
    assert sync.parse_args(["a=1", "b=x=y"]) == {"a": "1", "b": "x=y"}
    with pytest.raises(SystemExit):
        sync.parse_args(["nokey"])


# ---------------------------------------------------------------- doctor

def doctor_nf(tmp_path, *, deps=True, hook_state="STATE_SUCCESS", sites=None, model=None, redirect=None, timescale=False):
    m = make_manifest(tmp_path)
    nf = fake()
    app = nf.app_rec("new-app", "9.9.9 (abc1234)")
    app["hooks"] = [dict(h) for h in m["hooks"]]
    if timescale:
        app["options"].append({"name": "timescale", "value": {"string": '{"host": "db.example"}'}})
    nf.store["new-app"] = app
    nf.files[("new-app", "/static/version.json")] = json.dumps({"version": "9.9.9"}).encode()
    nf.deps_installed = deps
    nf.sites = sites or []
    nf.model = model or []
    for h in m["hooks"]:
        nf.runs[("new-app", h["id"])] = [{"pid": 1, "state": hook_state if h["id"] == "fdd" else "STATE_SUCCESS",
                                          "results": {"g": {"error": {"message": "Cannot find package 'pg'"}} if hook_state != "STATE_SUCCESS" and h["id"] == "fdd" else {"events": []}}}]
    nf.probe_result = redirect or (0, {})
    return m, nf


def test_doctor_all_green(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path, sites=[{"id": "s", "latitude": 43.0, "longitude": -89.0}],
                      redirect=(302, {"Location": "https://h/api/v1/apps/static/new-app/"}), timescale=True)
    assert sync.cmd_doctor(nf, m) == 0
    out = capsys.readouterr().out
    for want in ("[PASS] auth", "[PASS] version", "[PASS] deps", "[PASS] hook fdd", "[PASS] weather coords: NF Sites API",
                 '[PASS] timescale: app option "timescale" parses', "[PASS] / redirect", "all checks passed"):
        assert want in out, out


def test_doctor_flags_failures(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path, hook_state="STATE_FAILED",
                      redirect=(302, {"Location": "https://h/api/v1/apps/static/old-a/"}))
    nf.deps_installed = False
    nf.files[("new-app", "/static/version.json")] = json.dumps({"version": "9.0.0"}).encode()
    assert sync.cmd_doctor(nf, m) == 1
    out = capsys.readouterr().out
    assert "[FAIL] version" in out and "[FAIL] hook fdd" in out and "Cannot find package" in out
    assert "[FAIL] weather coords" in out
    assert "[FAIL] / redirect" in out and "old-a" in out
    assert "[PASS] timescale: not configured" in out
    assert "[WARN] deps" in out and "PATCH /api/v1/apps/new-app/dependencies" in out


def test_doctor_weather_coords_from_the_modeled_site(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path, model=[{"pointType": "SITE", "attrs": {"geoCoord": "C(43.07,-89.4)"}}])
    sync.cmd_doctor(nf, m)
    assert "modeled Haystack site on the model layer" in capsys.readouterr().out


def test_doctor_is_read_only(tmp_path):
    m, nf = doctor_nf(tmp_path)
    sync.cmd_doctor(nf, m)
    assert all(c[0] == "GET" or c[1] == "/api/v1/point/query" for c in nf.log), nf.log


# ---------------------------------------------------------------- TLS

def test_ca_file_missing_is_an_error_and_none_means_default(tmp_path):
    assert sync.make_ssl_context(None) is None
    with pytest.raises(SystemExit, match="CA file not found"):
        sync.make_ssl_context(str(tmp_path / "nope.pem"))


def _self_signed(host_ip: str, tmp_path: Path):
    cryptography = pytest.importorskip("cryptography")  # noqa: F841
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nf-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host_ip))]), critical=False)
            .sign(key, hashes.SHA256()))
    crt, k = tmp_path / f"{host_ip}.crt", tmp_path / f"{host_ip}.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return crt, k


def _tls_server(crt: Path, key: Path):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(crt), str(key))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_pin_server_cert_trusts_only_the_presented_leaf_and_prints_its_fingerprint(tmp_path):
    crt, key = _self_signed("127.0.0.1", tmp_path)
    srv = _tls_server(crt, key)
    try:
        base = f"https://127.0.0.1:{srv.server_port}"
        # without pinning the self-signed cert is rejected: verification is on
        with pytest.raises(SystemExit, match="TLS certificate not trusted"):
            sync.Console(base, "u", "p").call("GET", "/x")
        ctx, fp = sync.pin_server_cert(base)
        import hashlib
        assert fp == hashlib.sha256(ssl.PEM_cert_to_DER_cert(crt.read_text())).hexdigest()
        assert sync.Console(base, "u", "p", ctx).call("GET", "/x") == {}
        # --ca-file does the same with the certificate on disk
        assert sync.Console(base, "u", "p", sync.make_ssl_context(str(crt))).call("GET", "/x") == {}
    finally:
        srv.shutdown()


def test_pin_server_cert_refuses_a_cert_whose_san_does_not_name_the_host(tmp_path):
    crt, key = _self_signed("10.1.2.3", tmp_path)   # SAN is another address than 127.0.0.1
    srv = _tls_server(crt, key)
    try:
        with pytest.raises(SystemExit, match="does not match the host"):
            sync.pin_server_cert(f"https://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()


def test_pin_needs_https():
    with pytest.raises(SystemExit, match="https"):
        sync.pin_server_cert("http://127.0.0.1:1")


def test_no_action_ever_sends_a_delete_on_a_point_route(tmp_path):
    for action in (lambda m, nf, clk: sync.cmd_remove_old(nf, m, yes=True),
                   lambda m, nf, clk: sync.cmd_uninstall(nf, m, yes=True),
                   lambda m, nf, clk: sync.cmd_install(nf, m, install_args("--remove-old", "--yes"), clk, clk.sleep),
                   lambda m, nf, clk: sync.cmd_doctor(nf, m)):
        m, nf, clk = make_manifest(tmp_path), fake(predecessors(), points=pts()), Clock()
        action(m, nf, clk)
        assert not [c for c in nf.log if c[0] == "DELETE" and "/point" in c[1]], nf.log
