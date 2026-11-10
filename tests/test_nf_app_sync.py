"""nf_app_sync.py `run`: deadline, still-running exit status and --resume, with a fake console and clock."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from pathlib import Path
import base64
import json
import os
import shutil
import socket
import subprocess
import time

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nf_app_sync", Path(__file__).resolve().parents[1] / "scripts" / "nf" / "hooks" / "nf_app_sync.py"
)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

MANIFEST = {
    "application": {"id": "open-fdd"},
    "hooks": [{"id": "fdd", "invokeTimeout": "300s"}, {"id": "sparql", "invokeTimeout": "60s"}],
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


class FakeConsole:
    """Starts runs with pid 4242+n; a run finishes `duration[hook]` seconds after its start."""

    def __init__(self, clock: FakeClock, duration: dict[str, float], final: str = "STATE_SUCCESS") -> None:
        self.clock, self.duration, self.final = clock, duration, final
        self.starts: list[str] = []
        self.started_at: dict[int, tuple[str, float]] = {}
        self.fail_polls = 0

    def call(self, method, path, body=None, ok_404=False):
        parts = path.split("?")[0].split("/")  # /api/v1/apps/<app>/hooks/<hook>[/runs]
        hook = parts[6]
        if method == "POST":
            pid = 4242 + len(self.starts)
            self.starts.append(hook)
            self.started_at[pid] = (hook, self.clock())
            return {"pid": pid}
        if self.fail_polls:
            self.fail_polls -= 1
            raise SystemExit("GET runs -> HTTP 502")
        runs = []
        for pid, (h, t0) in self.started_at.items():
            if h != hook:
                continue
            done = self.clock() - t0 >= self.duration.get(h, 0)
            runs.append({"pid": pid, "state": self.final if done else "STATE_RUNNING", "startTime": "t0",
                         "results": {"a": {"events": [{"ts": "x", "message": "ok"}]}} if done else {}})
        return {"runs": runs}


def run(console, clock, **kw):
    return sync.cmd_run(console, MANIFEST, clock=clock, sleep=clock.sleep, **kw)


def test_parse_duration():
    assert sync.parse_duration("300s") == 300
    assert sync.parse_duration("5m") == 300
    assert sync.parse_duration("1.5s") == 1.5
    assert sync.parse_duration("1h") == 3600
    assert sync.parse_duration(None) == sync.DEFAULT_INVOKE_TIMEOUT
    assert sync.parse_duration("soon") == sync.DEFAULT_INVOKE_TIMEOUT


def test_default_wait_is_invoke_timeout_plus_60():
    assert sync.default_wait({"invokeTimeout": "300s"}) == 360
    assert sync.default_wait({"invokeTimeout": "60s"}) == 120
    assert sync.default_wait({}) == sync.DEFAULT_INVOKE_TIMEOUT + 60


def test_run_that_succeeds_after_75_seconds_is_waited_for():
    # The old fixed 60 s wait reported this as a timeout (and a retry would have started a second run).
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 75})
    assert run(c, clock, only_hooks=["fdd"]) == 0
    assert c.starts == ["fdd"]
    assert 75 <= clock() - 1000 < 80


def test_wait_runs_out_reports_still_running_exit_3_and_never_restarts(capsys):
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 10_000})
    assert run(c, clock, only_hooks=["fdd"], wait=90) == sync.EXIT_STILL_RUNNING == 3
    assert c.starts == ["fdd"]  # started exactly once
    out = capsys.readouterr().out
    assert "still running" in out and "pid=4242" in out and "NOT restarted" in out and "--resume 4242" in out
    assert 90 <= clock() - 1000 <= 92


def test_failed_run_is_exit_1_not_3():
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 4}, final="STATE_FAILED")
    assert run(c, clock, only_hooks=["fdd"]) == sync.EXIT_FAILED == 1


def test_failure_beats_still_running_across_hooks():
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 10_000, "sparql": 2}, final="STATE_FAILED")
    assert run(c, clock, wait=30) == 1  # sparql failed; fdd still running


def test_resume_waits_on_an_existing_run_and_starts_nothing():
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 100})
    c.started_at[777] = ("fdd", clock())
    assert run(c, clock, only_hooks=["fdd"], resume=777) == 0
    assert c.starts == []
    # still running on resume: exit 3, still nothing started
    c2 = FakeConsole(clock, {"fdd": 10_000})
    c2.started_at[778] = ("fdd", clock())
    assert run(c2, clock, only_hooks=["fdd"], resume=778, wait=20) == 3
    assert c2.starts == []


def test_resume_needs_exactly_one_hook():
    clock = FakeClock()
    with pytest.raises(SystemExit, match="--resume needs exactly one hook"):
        run(FakeConsole(clock, {}), clock, resume=1)


def _app(engine="auto", timescale=None):
    opts = [{"name": "engine", "value": {"string": engine}}]
    if timescale is not None:
        opts.append({"name": "timescale", "value": {"string": timescale}})
    return {"options": opts, "hooks": []}


def test_timescale_schema_preflight_engine_selection_and_lite_skip(monkeypatch):
    assert sync.timescale_schema_check({})[0] == "SKIP"  # Lite has no engine/config
    assert sync.timescale_schema_check(_app("sqlite", "postgresql://db/x"))[0] == "SKIP"
    assert sync.timescale_schema_check(_app("pglite"), {"NF_TIMESCALE_PREFLIGHT_DSN": "postgresql://db/x"})[0] == "SKIP"
    assert sync.timescale_schema_check(_app("auto"))[0] == "SKIP"
    assert sync.timescale_schema_check(_app("timescale"))[0] == "FAIL"


@pytest.mark.parametrize(("stdout", "expected"), [("3\n", "PASS"), ("2\n", "FAIL"), ("\n", "FAIL")])
def test_timescale_schema_preflight_exact_version(stdout, expected, monkeypatch):
    monkeypatch.setattr(sync.shutil, "which", lambda _: "psql-test")
    seen = {}
    def run(args, **kwargs):
        seen.update(args=args, **kwargs)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="secret should not escape")
    app = _app("auto", "postgresql://alice:password@db.example/fdd?sslmode=require")
    level, message = sync.timescale_schema_check(app, {}, runner=run)
    assert level == expected
    assert "password" not in message
    assert "password" not in " ".join(seen["args"])
    assert "-w" in seen["args"]
    assert seen["env"]["PGPASSWORD"] == "password"
    assert "CONSOLE_PASSWORD" not in seen["env"]
    assert "BEGIN TRANSACTION READ ONLY" in seen["args"][-1]
    assert seen["timeout"] == 10


def test_timescale_schema_preflight_uses_password_env_without_logging(monkeypatch):
    monkeypatch.setattr(sync.shutil, "which", lambda _: "psql-test")
    seen = {}
    def run(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="3\n", stderr="")
    raw = json.dumps({"host": "db.example", "database": "fdd", "passwordEnv": "DB_SECRET"})
    level, message = sync.timescale_schema_check(_app("timescale", raw), {"DB_SECRET": "top-secret"}, runner=run)
    assert level == "PASS" and "top-secret" not in message
    assert seen["env"]["PGPASSWORD"] == "top-secret"


def test_timescale_schema_preflight_env_override_wins_and_failures_are_redacted(monkeypatch):
    monkeypatch.setattr(sync.shutil, "which", lambda _: "psql-test")
    seen = {}
    def run(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=2, stdout="", stderr="postgres://secret")
    level, message = sync.timescale_schema_check(
        _app("timescale", "postgresql://old:secret@old/db"),
        {"NF_TIMESCALE_PREFLIGHT_DSN": "postgresql://new:override@new/db"}, runner=run)
    assert level == "FAIL"
    assert "secret" not in message and "postgres://secret" not in message
    assert seen["env"]["PGHOST"] == "new"
    assert seen["env"]["PGPASSWORD"] == "override"
    monkeypatch.setattr(sync.shutil, "which", lambda _: None)
    assert "psql is unavailable" in sync.timescale_schema_check(_app("timescale", "postgresql://db/x"))[1]


def test_timescale_schema_version_matches_runtime_constant():
    source = Path(__file__).resolve().parents[1] / "nf-app" / "hooks" / "lib" / "timescale.js"
    import re
    match = re.search(r"const SCHEMA_VERSION = (\d+);", source.read_text(encoding="utf-8"))
    assert match and int(match.group(1)) == 3


@pytest.mark.parametrize(("verify_rc", "restored"), [(sync.EXIT_FAILED, True), (sync.EXIT_STILL_RUNNING, False)])
def test_install_verification_failure_restores_snapshot(monkeypatch, capsys, verify_rc, restored):
    app_id = "open-fdd"
    old_version = b'{"version":"5.0.10"}'
    class Console:
        def __init__(self):
            self.files = {"/hooks/fdd.js": b"old-hook", "/static/version.json": old_version}
            self.record = {"id": app_id, "status": sync.INSTALLED,
                           "files": [{"path": p} for p in self.files],
                           "options": [{"name": "version", "value": {"string": "5.0.10"}}],
                           "configuration": {"version": {"string": "5.0.10"}},
                           "hooks": [{"id": "fdd", "entryPoint": "/hooks/fdd.js", "config": {"old": True}}]}
            self.hooks = {"fdd": self.record["hooks"][0]}
        def apps(self): return [self.record]
        def app(self, _): return self.record
        def read_file(self, _, path, **kwargs): return self.files.get(path)
        def call(self, method, path, body=None, **kwargs):
            if "/files" in path:
                self.files[path.split("/files", 1)[1]] = base64.b64decode(body)
            elif path.endswith("/hooks") and method == "POST":
                self.hooks[body["id"]] = body
            elif path.endswith("/restart"):
                pass
            elif path == f"/api/v1/apps/{app_id}" and "options" in (body or {}).get("updateMask", []):
                self.record["options"] = body["options"]
            elif path == f"/api/v1/apps/{app_id}" and "configuration" in (body or {}).get("updateMask", []):
                self.record["configuration"] = body["configuration"]
            return {}
    c = Console()
    m = {"application": {"id": app_id}, "_dir": Path("."),
         "files": {"/hooks/fdd.js": "hooks/fdd.js"},
         "hooks": [{"id": "fdd", "entryPoint": "/hooks/fdd.js", "mode": "MODE_ON_REQUEST"}]}
    args = SimpleNamespace(skip_hooks=False, hooks=None, skip_deps=True, force=True, save_remote=None,
                           skip_verify_run=True, wait=None, remove_old=False, yes=False, _environ={})
    monkeypatch.setattr(sync, "preflight", lambda *_: {app_id: c.record})
    monkeypatch.setattr(sync, "timescale_schema_check", lambda *_: ("SKIP", ""))
    monkeypatch.setattr(sync, "version_info", lambda *_: {"version": "5.0.11", "commit": "new", "dirty": False})
    def push(*_args, **_kwargs):
        c.files["/hooks/fdd.js"] = b"new-hook"
        c.files["/static/version.json"] = b'{"version":"5.0.11"}'
        c.record["options"] = [{"name": "version", "value": {"string": "5.0.11"}}]
        c.record["configuration"] = {"version": {"string": "5.0.11"}}
        c.hooks["fdd"] = {"id": "fdd", "config": {"new": True}}
        return 0
    monkeypatch.setattr(sync, "cmd_push", push)
    monkeypatch.setattr(sync, "verify_install", lambda *_args, **_kwargs: verify_rc)
    assert sync.cmd_install(c, m, args) == verify_rc
    if restored:
        assert c.files == {"/hooks/fdd.js": b"old-hook", "/static/version.json": old_version}
        assert c.record["options"] == [{"name": "version", "value": {"string": "5.0.10"}}]
        assert c.record["configuration"] == {"version": {"string": "5.0.10"}}
        assert c.hooks["fdd"]["config"] == {"old": True}
        assert "previous files, settings and hooks restored" in capsys.readouterr().out
    else:
        assert c.files["/hooks/fdd.js"] == b"new-hook"
        assert "no rollback or predecessor removal" in capsys.readouterr().out


def test_verify_version_mismatch_does_not_start_scheduled_hooks(monkeypatch):
    monkeypatch.setattr(sync, "version_info", lambda *_: {"version": "5.0.11"})
    called = []
    monkeypatch.setattr(sync, "cmd_run", lambda *_args, **_kwargs: called.append(True) or sync.EXIT_STILL_RUNNING)
    c = SimpleNamespace(app=lambda _: {"options": []},
                        read_file=lambda *_args, **_kwargs: b'{"version":"5.0.10"}')
    m = {"application": {"id": "open-fdd"}, "_dir": Path("."),
         "hooks": [{"id": "fdd", "mode": "MODE_SCHEDULED"}]}
    assert sync.verify_install(c, m) == sync.EXIT_FAILED
    assert not called


@pytest.mark.skipif(not shutil.which("node"), reason="mock NF installer integration requires Node")
def test_install_mock_nf_forced_verify_failure_restores_previous_app(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    mock = root / "nf-app" / "dev" / "mock-nf.mjs"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([shutil.which("node"), str(mock), str(port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with sync.urllib.request.urlopen(base + "/api/v1/apps", timeout=0.2):
                    break
            except Exception:
                if proc.poll() is not None:
                    raise AssertionError("mock NF exited before becoming ready")
                time.sleep(0.05)
        old_version = b'{"version":"5.0.10","files":{}}'
        old_hook = {"id": "fdd", "entryPoint": "/hooks/fdd.js", "mode": "MODE_ON_REQUEST", "config": {"old": True}}
        initial = {"files": ["/hooks/fdd.js", "/static/version.json"],
                   "contents": {"/hooks/fdd.js": base64.b64encode(b"old-hook").decode(),
                                "/static/version.json": base64.b64encode(old_version).decode()},
                   "options": [{"name": "version", "value": {"string": "5.0.10"}}],
                   "configuration": {"version": {"string": "5.0.10"}}, "hooks": [old_hook]}
        req = sync.urllib.request.Request(base + "/api/v1/_mock/install/state", data=json.dumps(initial).encode(),
                                          headers={"Content-Type": "application/json"}, method="POST")
        sync.urllib.request.urlopen(req, timeout=2).read()
        c = sync.Console(base, "mock", "mock")
        (tmp_path / "fdd.js").write_bytes(b"new-hook")
        m = {"application": {"id": "open-fdd", "auth": {"mock": True}}, "_dir": tmp_path,
             "files": {"/hooks/fdd.js": "fdd.js"},
             "hooks": [{"id": "fdd", "entryPoint": "/hooks/fdd.js", "mode": "MODE_ON_REQUEST", "config": {"new": True}}]}
        monkeypatch.setattr(sync, "version_info", lambda *_: {"version": "5.0.11", "commit": "new", "dirty": False})
        args = SimpleNamespace(skip_hooks=False, hooks=None, skip_deps=True, force=True, save_remote=None,
                               skip_verify_run=True, wait=None, remove_old=False, yes=False,
                               _environ={})
        assert sync.cmd_install(c, m, args) == sync.EXIT_FAILED
        assert c.read_file("open-fdd", "/hooks/fdd.js") == b"old-hook"
        assert c.read_file("open-fdd", "/static/version.json") == old_version
        app = c.app("open-fdd")
        assert app["options"][0]["value"]["string"] == "5.0.10"
        assert app["configuration"]["version"]["string"] == "5.0.10"
        assert app["hooks"][0]["config"] == {"old": True}
        assert "auth" not in app, "guarded install leaves the app auth scopes untouched"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_transient_poll_errors_do_not_abort_or_restart():
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 20})
    c.fail_polls = 3
    assert run(c, clock, only_hooks=["fdd"]) == 0
    assert c.starts == ["fdd"]


def test_explicit_wait_overrides_default():
    clock = FakeClock()
    c = FakeConsole(clock, {"fdd": 200})
    assert run(c, clock, only_hooks=["fdd"], wait=100) == 3
    clock2 = FakeClock()
    assert run(FakeConsole(clock2, {"fdd": 200}), clock2, only_hooks=["fdd"], wait=500) == 0


def test_report_run_replaces_non_cp1252_event_and_ok_false_text(monkeypatch):
    class Cp1252Stdout:
        encoding = "cp1252"

        def __init__(self):
            self.parts = []

        def write(self, value):
            value.encode(self.encoding)  # faithfully model a cp1252 terminal's failure
            self.parts.append(value)

        def flush(self):
            pass

    out = Cp1252Stdout()
    monkeypatch.setattr(sync.sys, "stdout", out)
    run_data = {"state": "STATE_SUCCESS", "startTime": "now", "results": {"g": {
        "events": [
            {"ts": "now", "message": "event emoji 💥"},
            {"ts": "now", "message": '{"ok":false,"error":"failure 💥"}'},
        ]
    }}}
    assert sync.report_run(run_data) == sync.EXIT_FAILED
    output = "".join(out.parts)
    assert "event emoji ?" in output
    assert "hook returned ok:false: failure ?" in output


@pytest.mark.parametrize(("result", "event", "warn"), [
    ({"roles_skipped_by_unit": {"zone_flow": 1}}, "unrelated", True),
    ({}, "roles skipped by unit: 1 (zone_flow 1)", True),
    ({"roles_skipped_by_unit": {}}, "roles skipped by unit: 0", False),
])
def test_doctor_warns_only_when_latest_fdd_run_skipped_units(monkeypatch, tmp_path, capsys, result, event, warn):
    hook = {"id": "fdd", "entryPoint": "/hooks/fdd.js"}
    run = {"state": "STATE_SUCCESS", "results": {"g": {"result": result, "events": [{"message": event}]}}}
    console = SimpleNamespace(
        apps=lambda: [{"id": "open-fdd", "hooks": [hook]}],
        call=lambda *_: {"runs": [run]},
        read_file=lambda *_: b'{"version":"5.0.10"}',
        probe=lambda *_: (200, {}),
    )
    monkeypatch.setattr(sync, "version_info", lambda *_: {"version": "5.0.10"})
    monkeypatch.setattr(sync, "fdd_freshness", lambda *_: ("pass", "fresh"))
    monkeypatch.setattr(sync, "find_drift", lambda *_: {})
    monkeypatch.setattr(sync, "hand_edit_line", lambda *_: ("PASS", "hand edits", "none"))
    manifest = {"application": {"id": "open-fdd"}, "_dir": tmp_path, "hooks": [hook]}
    assert sync.cmd_doctor(console, manifest) == 0
    output = capsys.readouterr().out
    assert ("[WARN] fdd units: roles skipped by unit: 1 (zone_flow 1)" in output) is warn
