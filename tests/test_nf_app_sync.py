"""nf_app_sync.py `run`: deadline, still-running exit status and --resume, with a fake console and clock."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from pathlib import Path

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
