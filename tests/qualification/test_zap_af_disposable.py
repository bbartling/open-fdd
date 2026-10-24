"""ZAP AF disposable runner: scanner-observed auth, strict evidence, scope, budgets, secrets.

No live ZAP: scanner output comes from recorded-shape fixtures under
``fixtures/zap_af/`` written by a fake scanner process.

Run: python3 -B -m unittest discover -s tests/qualification -v
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import http.server
import importlib.util
import io
import json
import os
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "scripts/qualification/zap/af_plan.yaml"
MODULE_PATH = ROOT / "scripts/qualification/zap/run_af_disposable.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "zap_af"

SPEC = importlib.util.spec_from_file_location("run_af_disposable", MODULE_PATH)
af = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = af
SPEC.loader.exec_module(af)

ORIGIN = "http://127.0.0.1:18080"
USERNAME = "admin"
GOOD_AUTH = "Bearer fixture-token-0123456789abcdef"
FAKE_ZAP = "/opt/fake/zap.sh"
PASSIVE_DONE = "Job passiveScan-wait started\nJob passiveScan-wait finished, time taken: 00:00:01\n"


def load_report(name: str, origin: str = ORIGIN) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8").replace("__ORIGIN__", origin))


def identity_body(username: str = USERNAME) -> str:
    return json.dumps({"ok": True, "username": username, "role": "admin", "auth_required": True})


def build_har(
    *,
    nonce: str,
    auth: str,
    origin: str = ORIGIN,
    probe_status: int = 200,
    probe_body: str | None = None,
    drop_probe_auth: bool = False,
    extra_entries: list[dict] | None = None,
) -> dict:
    text = (FIXTURES / "messages_template.har.tmpl").read_text(encoding="utf-8")
    body = identity_body() if probe_body is None else probe_body
    text = (
        text.replace("__ORIGIN__", origin)
        .replace("__NONCE__", nonce)
        .replace("__PROBE_STATUS__", str(probe_status))
        .replace("__PROBE_BODY__", json.dumps(body)[1:-1])
        .replace("__AUTH__", json.dumps(auth)[1:-1])
    )
    har = json.loads(text)
    if drop_probe_auth:
        for e in har["log"]["entries"]:
            hdrs = e["request"]["headers"]
            if any(h["name"] == af.PROBE_HEADER for h in hdrs):
                e["request"]["headers"] = [h for h in hdrs if h["name"].lower() != "authorization"]
    if extra_entries:
        har["log"]["entries"].extend(extra_entries)
    return har


def har_entry(url: str, *, status: int = 200, auth: str | None = None, location: str | None = None) -> dict:
    req_headers = [{"name": "Authorization", "value": auth}] if auth else []
    resp_headers = [{"name": "Location", "value": location}] if location else []
    return {
        "request": {"method": "GET", "url": url, "headers": req_headers},
        "response": {"status": status, "headers": resp_headers, "content": {"mimeType": "text/html", "text": ""}},
    }


def plan_nonce(work_dir: Path) -> str:
    plan = yaml.safe_load((work_dir / "af_plan.yaml").read_text(encoding="utf-8"))
    for job in plan["jobs"]:
        for req in job.get("requests") or []:
            for h in req.get("headers") or []:
                if h.startswith(af.PROBE_HEADER + ":before-"):
                    return h.split(":before-", 1)[1]
    raise AssertionError("no probe nonce in rendered plan")


class FakeScanner:
    """Stands in for run_owned_process; writes recorded-shape ZAP output."""

    def __init__(
        self,
        *,
        report: dict | bytes | None = None,
        har: str = "ok",
        har_kwargs: dict | None = None,
        rc: int = 0,
        stdout: str | None = None,
        timed_out: bool = False,
        cancelled: bool = False,
        leak_to_stdout: bool = False,
        leak_to_report: bool = False,
        har_mutator=None,
    ) -> None:
        self.report = load_report("report_clean.json") if report is None else report
        self.har = har
        self.har_kwargs = har_kwargs or {}
        self.rc = rc
        self.stdout = stdout
        self.timed_out = timed_out
        self.cancelled = cancelled
        self.leak_to_stdout = leak_to_stdout
        self.leak_to_report = leak_to_report
        self.har_mutator = har_mutator
        self.calls: list[tuple[list[str], dict, bytes | None]] = []
        self.scanner_env: dict | None = None

    def __call__(self, cmd, *, env, timeout_s, cwd=None, container_name=None, stdin_bytes=None):
        self.calls.append((list(cmd), dict(env), stdin_bytes))
        if cmd[:3] == ["docker", "image", "inspect"]:
            return af.ProcResult(returncode=0, stdout="[]", stderr="")
        is_zap = cmd[0] == FAKE_ZAP or (cmd[:2] == ["docker", "run"] and "zap.sh" in cmd)
        if not is_zap:
            return af.ProcResult(returncode=1, stdout="", stderr="unexpected command")
        self.scanner_env = dict(env)
        if cmd[0] == FAKE_ZAP:
            work = Path(cmd[-1]).parent
        else:
            mount = cmd[cmd.index("-v") + 1]
            work = Path(mount.split(":/zap/wrk", 1)[0])
        plan = yaml.safe_load((work / "af_plan.yaml").read_text(encoding="utf-8"))
        waits = sum(1 for j in plan["jobs"] if j["type"] == "passiveScan-wait")
        nonce = plan_nonce(work)
        scanner_header = env.get("ZAP_AUTH_HEADER_VALUE", "")
        if self.har != "none":
            har = build_har(nonce=nonce, auth=scanner_header, **self.har_kwargs)
            if not any(j["type"] == "openapi" for j in plan["jobs"]):
                # Follow the negative plan: only its three requestor probes.
                har["log"]["entries"] = [
                    e for e in har["log"]["entries"]
                    if any(h["name"] == af.PROBE_HEADER for h in e["request"]["headers"])
                ]
            if self.har == "broken_injection":
                har = build_har(
                    nonce=nonce,
                    auth=scanner_header,
                    probe_status=401,
                    probe_body=json.dumps({"ok": False, "error": "missing bearer"}),
                    drop_probe_auth=True,
                )
            if self.har_mutator is not None:
                self.har_mutator(har)
            (work / af.MESSAGES_FILE).write_text(json.dumps(har), encoding="utf-8")
        if self.report is not False:
            raw = self.report if isinstance(self.report, bytes) else json.dumps(self.report).encode()
            if self.leak_to_report:
                raw = raw.replace(b'"otherinfo": ""', b'"otherinfo": "' + scanner_header.encode() + b'"', 1)
            (work / af.REPORT_FILE).write_bytes(raw)
        out = PASSIVE_DONE * waits if self.stdout is None else self.stdout
        if self.leak_to_stdout:
            out += f"debug Authorization: {scanner_header}\n"
            out += f"debug token={scanner_header.split(' ', 1)[-1]}\n"
        return af.ProcResult(
            returncode=None if (self.timed_out or self.cancelled) else self.rc,
            stdout=out,
            stderr="",
            timed_out=self.timed_out,
            cancelled=self.cancelled,
        )


PREFLIGHT_OK = {
    "ok": True,
    "status": 200,
    "path": "/api/auth/me",
    "schema_ok": True,
    "identity_match": True,
    "role": "admin",
    "via": "urllib",
}


class ExecuteHarness(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.work = self.root / "work"
        self.work.mkdir()
        (self.work / "openapi.json").write_text(
            json.dumps({"openapi": "3.0.3", "info": {"title": "f", "version": "0"}, "paths": {}}),
            encoding="utf-8",
        )
        self.out = self.root / "evidence" / "verdict.json"
        af._CANCEL.clear()

    def tearDown(self) -> None:
        af._CANCEL.clear()
        self._td.cleanup()

    def env(self, **extra: str) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "ZAP_TARGET_ORIGIN": ORIGIN,
            "ZAP_AUTH_HEADER_VALUE": GOOD_AUTH,
            "OPENFDD_ZAP_EXPECTED_USERNAME": USERNAME,
            "ZAP_AF_WORK_DIR": str(self.work),
        }
        env.update(extra)
        return env

    def execute(
        self,
        scanner: FakeScanner,
        *,
        env: dict[str, str] | None = None,
        preflight: dict | None = None,
        mode: tuple[str, str] = ("zap.sh", FAKE_ZAP),
        negative_control: bool = False,
        dispositions: Path | None = None,
    ) -> tuple[int, dict]:
        patches = [
            mock.patch.dict(os.environ, env or self.env(), clear=True),
            mock.patch.object(af, "detect_zap", return_value=mode),
            mock.patch.object(af, "run_owned_process", side_effect=scanner),
            mock.patch.object(af, "fetch_auth_me_preflight", return_value=dict(preflight or PREFLIGHT_OK)),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ]
        if dispositions is not None:
            patches.append(mock.patch.object(af, "DISPOSITION_PATH", dispositions))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            rc = af.run_execute(self.out, negative_control=negative_control)
        return rc, json.loads(self.out.read_text(encoding="utf-8"))

    def all_artifact_bytes(self) -> list[tuple[Path, bytes]]:
        return [(p, p.read_bytes()) for p in self.root.rglob("*") if p.is_file()]


# --------------------------------------------------------------------------- #
# Plan hygiene
# --------------------------------------------------------------------------- #


class ZapAfPlanHygieneTest(unittest.TestCase):
    def test_repo_plan_is_clean(self):
        self.assertEqual(af.validate_af_plan(PLAN), [])
        raw = PLAN.read_text(encoding="utf-8")
        self.assertNotRegex(raw, r"Bearer\s+(?!\$\{)[A-Za-z0-9\-_\.=]+")
        self.assertNotRegex(raw, r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
        self.assertNotIn("${ZAP_AUTH_HEADER", raw)

    def _mutated(self, transform) -> list[str]:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "plan.yaml"
            bad.write_text(transform(PLAN.read_text(encoding="utf-8")), encoding="utf-8")
            return af.validate_af_plan(bad)

    def _mutated_yaml(self, fn) -> list[str]:
        def transform(raw: str) -> str:
            data = yaml.safe_load(raw)
            fn(data)
            return yaml.safe_dump(data, sort_keys=False) + "\n# ${ZAP_SCOPE_REGEX} ${ZAP_PROBE_NONCE}\n"

        return self._mutated(transform)

    def test_rejects_hardcoded_bearer_and_credential_reference(self):
        errs = self._mutated(lambda r: r + "\n# Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaaaaaaaaaa.bbbb\n")
        self.assertTrue(any("Bearer" in e or "JWT" in e for e in errs), errs)
        errs = self._mutated(lambda r: r + '\n# "${ZAP_AUTH_HEADER_VALUE}"\n')
        self.assertTrue(any("must not reference the scanner credential" in e for e in errs), errs)

    def test_rejects_unanchored_scope(self):
        errs = self._mutated(lambda r: r.replace('"${ZAP_SCOPE_REGEX}"', '"${ZAP_TARGET_ORIGIN}.*"'))
        self.assertTrue(any("includePaths" in e for e in errs), errs)

    def test_rejects_proxy_and_bounded_passive_wait(self):
        errs = self._mutated_yaml(lambda d: d["env"].__setitem__("proxy", {"hostname": "proxy.example", "port": 3128}))
        self.assertTrue(any("proxy" in e for e in errs), errs)

        def bound_wait(d):
            next(j for j in d["jobs"] if j["type"] == "passiveScan-wait")["parameters"]["maxDuration"] = 10

        errs = self._mutated_yaml(bound_wait)
        self.assertTrue(any("drain" in e for e in errs), errs)

    def test_rejects_missing_or_reordered_probes(self):
        errs = self._mutated_yaml(lambda d: d.__setitem__("jobs", [j for j in d["jobs"] if j.get("name") != "auth-probe-during"]))
        self.assertTrue(any("during auth probe" in e for e in errs), errs)

        def move_before_last(d):
            jobs = d["jobs"]
            before = jobs.pop(0)
            jobs.insert(3, before)

        errs = self._mutated_yaml(move_before_last)
        self.assertTrue(any("before / during / after" in e for e in errs), errs)

    def test_materialized_plan_scope_nonce_and_active_order(self):
        target = af.parse_disposable_origin(ORIGIN)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "af_plan.yaml"
            plan = af.materialize_plan(
                target=target,
                report_dir="/zap/wrk",
                active=True,
                nonce="n0nce",
                expected_username=USERNAME,
                max_seconds=600,
                dest=dest,
                secrets=af.SecretSet([GOOD_AUTH]),
            )
            text = dest.read_text(encoding="utf-8")
        self.assertNotIn("${", text)
        self.assertNotIn(GOOD_AUTH, text)
        ctx = plan["env"]["contexts"][0]
        self.assertEqual(ctx["includePaths"], [r"^http://127\.0\.0\.1:18080(?:[/?#].*)?$"])
        types = [j["type"] for j in plan["jobs"]]
        self.assertLess(types.index("activeScan"), max(i for i, j in enumerate(plan["jobs"]) if j.get("name") == "auth-probe-after"))
        self.assertIn(f"{af.PROBE_HEADER}:after-n0nce", text)
        self.assertEqual(af.expected_passive_waits(plan), 3)
        self.assertNotIn("maxDuration", plan["env"]["parameters"])
        for job in plan["jobs"]:
            if job["type"] == "passiveScan-wait":
                self.assertEqual(job["parameters"]["maxDuration"], 0)

    def test_redundant_global_duration_is_rejected_for_pinned_compatibility(self):
        errors = self._mutated_yaml(lambda d: d["env"]["parameters"].__setitem__("maxDuration", 600))
        self.assertTrue(any("pinned add-on compatibility" in error for error in errors), errors)


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #


class ZapAfScopeTest(unittest.TestCase):
    def test_hostile_or_non_canonical_origins_refused(self):
        hostile = [
            "http://evil.example",
            "https://openfdd.up.railway.app",
            "http://127.0.0.1.evil.example:18080",
            "http://web:8080",
            "http://user@127.0.0.1:18080",
            "http://127.0.0.1:18080/api",
            "http://127.0.0.1:18080?x=1",
            "http://127.0.0.1:18080#f",
            "ftp://127.0.0.1",
            "http://127.0.0.1:80",
            "HTTP://127.0.0.1:18080",
            "http://10.0.0.5:8080",
            "http://127.0.0.1 :18080",
            "http://127.0.0.1:18080\\@evil.example",
            "",
        ]
        for origin in hostile:
            with self.subTest(origin=origin):
                with self.assertRaises(af.ScopeError):
                    af.parse_disposable_origin(origin)
        with self.assertRaises(af.ScopeError):
            af.parse_disposable_origin("http://web:8080", docker_network="bridge")

    def test_disposable_origins_accepted(self):
        self.assertEqual(af.parse_disposable_origin("http://127.0.0.1:18080/").kind, "loopback")
        self.assertEqual(af.parse_disposable_origin("http://localhost:3000").kind, "loopback")
        self.assertEqual(af.parse_disposable_origin("http://[::1]:8080").origin, "http://[::1]:8080")
        t = af.parse_disposable_origin("http://web:8080", docker_network="openfdd-zap-af-1a2b3c")
        self.assertEqual(t.kind, "docker_network")

    def test_scope_regex_is_anchored_and_escaped(self):
        t = af.parse_disposable_origin(ORIGIN)
        self.assertTrue(t.in_scope(ORIGIN))
        self.assertTrue(t.in_scope(ORIGIN + "/api/x?y=1"))
        for url in (
            "http://127.0.0.1:180800/",
            "http://127.0.0.1:18080.evil.example/",
            "http://127x0x0x1:18080/",
            "https://127.0.0.1:18080/",
            "http://evil.example/?http://127.0.0.1:18080/",
        ):
            with self.subTest(url=url):
                self.assertFalse(t.in_scope(url))

    def test_child_env_strips_proxies_and_credentials(self):
        with mock.patch.dict(
            os.environ,
            {"HTTP_PROXY": "http://p:1", "https_proxy": "http://p:1", "ZAP_AUTH_HEADER_VALUE": GOOD_AUTH, "KEEP": "1"},
            clear=True,
        ):
            env = af.child_env()
        self.assertEqual(env, {"KEEP": "1"})


class _Handler(http.server.BaseHTTPRequestHandler):
    mode = "ok"

    def do_GET(self):  # noqa: N802
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://evil.example/api/auth/me")
            self.end_headers()
            return
        ok = self.headers.get("Authorization") == GOOD_AUTH
        username = "someone-else" if self.mode == "wrong_identity" else USERNAME
        body = identity_body(username).encode() if ok else b'{"ok":false,"error":"no"}'
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


class ZapAfPreflightLoopbackTest(unittest.TestCase):
    """Real loopback HTTP server; no ZAP."""

    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.target = af.parse_disposable_origin(f"http://127.0.0.1:{self.server.server_port}")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        _Handler.mode = "ok"

    def preflight(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://198.51.100.1:9"}, clear=False):
            return af.fetch_auth_me_preflight(
                target=self.target, auth_header=GOOD_AUTH, expected_username=USERNAME, budget=af.Budget(600, 10)
            )

    def test_preflight_ok_ignores_env_proxy(self):
        self.assertTrue(self.preflight()["ok"])

    def test_preflight_refuses_redirect(self):
        _Handler.mode = "redirect"
        res = self.preflight()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "redirect_refused")

    def test_preflight_wrong_identity(self):
        _Handler.mode = "wrong_identity"
        res = self.preflight()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "identity_mismatch")


class ZapAfHostileOriginExecuteTest(ExecuteHarness):
    def test_hostile_origin_fails_before_credentials(self):
        scanner = FakeScanner()
        with (
            mock.patch.object(af, "load_scanner_auth_header", side_effect=AssertionError("credential read")) as cred,
        ):
            rc, verdict = self.execute(scanner, env=self.env(ZAP_TARGET_ORIGIN="https://openfdd.up.railway.app"))
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("refused target before passing credentials", verdict["notes"])
        cred.assert_not_called()
        self.assertEqual(scanner.calls, [])

    def test_out_of_scope_traffic_and_redirect_fail(self):
        cases = {
            "out_of_scope": [har_entry("http://evil.example/collect", auth=GOOD_AUTH)],
            "redirect": [har_entry(ORIGIN + "/login", status=302, location="http://evil.example/")],
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                self.tearDown()
                self.setUp()
                rc, verdict = self.execute(FakeScanner(har_kwargs={"extra_entries": extra}))
                self.assertEqual(rc, 1)
                self.assertEqual(verdict["status"], "FAIL")
                self.assertIn("scanner-origin authentication not proven", verdict["notes"])
                self.assertIn("outside the target scope", verdict["notes"])


# --------------------------------------------------------------------------- #
# Scanner-origin auth evidence
# --------------------------------------------------------------------------- #


class ZapAfScannerAuthTest(ExecuteHarness):
    def test_clean_scan_passes_with_scanner_verified_auth(self):
        rc, verdict = self.execute(FakeScanner())
        self.assertEqual(rc, 0, verdict["notes"])
        self.assertEqual(verdict["status"], "PASS")
        self.assertEqual(verdict["suite"], "zap_af_authenticated_v2")
        self.assertTrue(verdict["scanner_auth_verified"])
        self.assertEqual(verdict["auth_proof"], "zap_message_history_probes_before_during_after")
        probes = verdict["scanner_auth"]["probes"]
        for phase in ("before", "during", "after"):
            self.assertTrue(probes[phase]["authorization_matches"])
            self.assertTrue(probes[phase]["identity_ok"])
        self.assertFalse(verdict["scanner_messages"]["retained"])
        self.assertFalse((self.work / af.MESSAGES_FILE).exists())

    def test_broken_scanner_credential_fails_despite_preflight_and_report_url(self):
        """Negative control: preflight OK + /api/auth/me in report is not authenticated coverage."""
        report = load_report("report_clean.json")
        self.assertIn("/api/auth/me", json.dumps(report))
        rc, verdict = self.execute(FakeScanner(report=report, har="broken_injection"))
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertTrue(verdict["auth_me_preflight"]["ok"])
        self.assertFalse(verdict["scanner_auth_verified"])
        self.assertIn("did not carry the scanner credential", verdict["notes"])

    def test_scanner_using_different_credential_fails(self):
        scanner = FakeScanner()
        original = af.zap_env

        def wrong_env(*, scanner_header, target):
            return original(scanner_header="Bearer some-other-valid-looking-token", target=target)

        with mock.patch.object(af, "zap_env", side_effect=wrong_env):
            rc, verdict = self.execute(scanner)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("did not carry the scanner credential", verdict["notes"])

    def test_wrong_identity_fails(self):
        rc, verdict = self.execute(FakeScanner(har_kwargs={"probe_body": identity_body("viewer-bot")}))
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("identity_mismatch", verdict["notes"])

    def test_missing_message_history_fails(self):
        rc, verdict = self.execute(FakeScanner(har="none"))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("message history", verdict["notes"])

    def test_preflight_failure_fails_before_scan(self):
        scanner = FakeScanner()
        rc, verdict = self.execute(scanner, preflight={"ok": False, "status": 401, "error": "non_200"})
        self.assertEqual(verdict["status"], "FAIL")
        self.assertEqual(scanner.calls, [])
        self.assertIsNone(verdict["high_alerts"])
        self.assertFalse(verdict["alert_counts_evaluated"])
        self.assertIsNone(verdict["scanner_error_count"])

    def test_zero_exit_is_not_a_known_scanner_error_count(self):
        rc, verdict = self.execute(FakeScanner())
        self.assertEqual(rc, 0)
        self.assertEqual(verdict["high_alerts"], 0)
        self.assertTrue(verdict["alert_counts_evaluated"])
        self.assertIsNone(verdict["scanner_error_count"])
        self.assertEqual(verdict["scanner_error_count_status"], "not_reported_by_traditional_json")
        self.assertFalse(verdict["budget"]["request_limit_preventive"])
        self.assertEqual(verdict["budget"]["request_limit_enforcement"], "post_scan_har_check")

    def test_auth_evidence_rejects_duplicate_or_stale_probes(self):
        def duplicate(har):
            extra = copy.deepcopy(har["log"]["entries"][0])
            extra["response"]["status"] = 401
            har["log"]["entries"].append(extra)

        def stale(har):
            extra = copy.deepcopy(har["log"]["entries"][0])
            next(h for h in extra["request"]["headers"] if h["name"] == af.PROBE_HEADER)["value"] = "before-old-run"
            har["log"]["entries"].append(extra)

        for mutate in (duplicate, stale):
            with self.subTest(case=mutate.__name__):
                self.tearDown()
                self.setUp()
                rc, verdict = self.execute(FakeScanner(har_mutator=mutate))
                self.assertEqual(rc, 1)
                self.assertEqual(verdict["status"], "FAIL")

    def test_synthesized_auth_object_in_report_is_rejected(self):
        report = load_report("report_clean.json")
        report["openfdd_auth_traffic"] = {"method": "GET", "path": "/api/auth/me", "status": 200, "origin": "scanner"}
        raw = json.dumps(report).encode()
        rc, verdict = self.execute(FakeScanner(report=raw))
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("unknown fields", verdict["notes"])
        self.assertEqual((self.work / af.REPORT_FILE).read_bytes(), raw)
        self.assertFalse(hasattr(af, "seed_scanner_auth_me_traffic"))

    def test_passive_queue_not_drained_fails(self):
        rc, verdict = self.execute(FakeScanner(stdout="Job passiveScan-wait started\n"))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("passive scan queue not confirmed drained", verdict["notes"])

    def test_request_budget_exceeded_fails(self):
        rc, verdict = self.execute(FakeScanner(), env=self.env(OPENFDD_ZAP_MAX_REQUESTS="3"))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("request budget exceeded", verdict["notes"])

    def test_scanner_nonzero_exit_fails(self):
        rc, verdict = self.execute(FakeScanner(rc=1))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("exited nonzero", verdict["notes"])

    def test_stale_scanner_output_in_work_dir_refused(self):
        (self.work / af.REPORT_FILE).write_text("{}", encoding="utf-8")
        scanner = FakeScanner()
        rc, verdict = self.execute(scanner)
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("stale evidence", verdict["notes"])
        self.assertEqual(scanner.calls, [])

    def test_verify_auth_me_response_strict(self):
        ok = af.verify_auth_me_response(
            status=200, body=identity_body().encode(), content_type="application/json", expected_username=USERNAME
        )
        self.assertTrue(ok["ok"])
        for kwargs, err in (
            ({"status": 401, "body": b"{}"}, "non_200"),
            ({"status": 200, "body": b"<html>", "content_type": "text/html"}, "non_json_content_type"),
            ({"status": 200, "body": b'{"ok":true}'}, "missing_identity"),
            ({"status": 200, "body": b'{"ok":false,"username":"admin","role":"admin"}'}, "missing_identity"),
            ({"status": 200, "body": identity_body("eve").encode()}, "identity_mismatch"),
        ):
            kwargs.setdefault("content_type", "application/json")
            with self.subTest(err=err):
                res = af.verify_auth_me_response(expected_username=USERNAME, **kwargs)
                self.assertFalse(res["ok"])
                self.assertEqual(res["error"], err)


class ZapAfNegativeControlModeTest(ExecuteHarness):
    def test_negative_control_detects_broken_scanner_credential(self):
        for status in (401, 403):
            with self.subTest(status=status):
                if status == 403:
                    self.tearDown()
                    self.setUp()
                scanner = FakeScanner(har_kwargs={
                    "probe_status": status,
                    "probe_body": json.dumps({"ok": False, "error": "invalid bearer"}),
                })
                rc, verdict = self.execute(scanner, negative_control=True)
                self.assertEqual(rc, 0, verdict["notes"])
                self.assertEqual(verdict["suite"], "zap_af_negative_control_v2")
                self.assertTrue(verdict["negative_control_detected"])
                self.assertEqual(verdict["scanner_auth"]["request_count"], 3)
                self.assertIsNone(verdict["high_alerts"])
                self.assertFalse(verdict["alert_counts_evaluated"])
                self.assertTrue(scanner.scanner_env["ZAP_AUTH_HEADER_VALUE"].startswith("Bearer openfdd-negative-control-"))
                self.assertNotIn(GOOD_AUTH, json.dumps(scanner.scanner_env))

    def test_bad_header_200_is_fail_not_an_inverted_auth_pass(self):
        rc, verdict = self.execute(FakeScanner(), negative_control=True)
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertEqual(verdict["scanner_auth"]["unexpected_success_count"], 3)
        self.assertTrue(verdict["scanner_auth"]["probes"]["before"]["authorization_matches"])
        self.assertNotIn("negative_control_detected", verdict)

    def test_any_200_body_is_fail_including_html_or_wrong_identity(self):
        for body in (identity_body("other-user"), "<html>login</html>", "{}"):
            with self.subTest(body=body):
                self.tearDown()
                self.setUp()
                rc, verdict = self.execute(FakeScanner(har_kwargs={"probe_body": body}), negative_control=True)
                self.assertEqual(verdict["status"], "FAIL")
                self.assertEqual(rc, 1)

    def test_negative_control_fails_if_broken_credential_looks_authenticated(self):
        original = af.zap_env

        def leaky(*, scanner_header, target):
            return original(scanner_header=GOOD_AUTH, target=target)

        with mock.patch.object(af, "zap_env", side_effect=leaky):
            rc, verdict = self.execute(FakeScanner(), negative_control=True)
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")

    def test_negative_control_without_probes_is_inconclusive(self):
        rc, verdict = self.execute(FakeScanner(har="none", rc=1), negative_control=True)
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("inconclusive", verdict["notes"])

    def test_unrelated_failure_is_never_evidence_of_auth_rejection(self):
        for status, body, rc in (
            (500, '{"ok":false}', 0),
            (0, "", 0),
            (302, "", 0),
            (401, "<html>error</html>", 0),
            (401, '{"ok":true,"username":"admin"}', 0),
            (401, '{"ok":false}', 1),
        ):
            with self.subTest(status=status, body=body, scanner_rc=rc):
                self.tearDown()
                self.setUp()
                scanner = FakeScanner(rc=rc, har_kwargs={"probe_status": status, "probe_body": body})
                result, verdict = self.execute(scanner, negative_control=True)
                self.assertEqual(result, 1)
                self.assertEqual(verdict["status"], "ERROR", verdict["notes"])
                self.assertIsNone(verdict["high_alerts"])

    def test_denial_needs_header_nonce_unique_order_scope_and_budget(self):
        def headers(har):
            return har["log"]["entries"][0]["request"]["headers"]

        def drop_header(har):
            headers(har)[:] = [h for h in headers(har) if h["name"].lower() != "authorization"]

        def wrong_header(har):
            next(h for h in headers(har) if h["name"].lower() == "authorization")["value"] = GOOD_AUTH

        def stale_nonce(har):
            next(h for h in headers(har) if h["name"] == af.PROBE_HEADER)["value"] = "before-old-run"

        def duplicate(har):
            har["log"]["entries"].append(copy.deepcopy(har["log"]["entries"][0]))

        def missing(har):
            har["log"]["entries"].pop()

        def reordered(har):
            har["log"]["entries"].reverse()

        def off_origin(har):
            har["log"]["entries"].append(har_entry("http://evil.example/leak", auth=GOOD_AUTH))

        def foreign_redirect(har):
            response = har["log"]["entries"][0]["response"]
            response["status"] = 302
            response["redirectURL"] = "http://evil.example/leak"

        for mutate in (drop_header, wrong_header, stale_nonce, duplicate, missing, reordered, off_origin, foreign_redirect):
            with self.subTest(case=mutate.__name__):
                self.tearDown()
                self.setUp()
                scanner = FakeScanner(har_kwargs={"probe_status": 401, "probe_body": '{"ok":false}'},
                                      har_mutator=mutate)
                rc, verdict = self.execute(scanner, negative_control=True)
                self.assertEqual(rc, 1)
                self.assertEqual(verdict["status"], "ERROR", verdict["notes"])
        self.tearDown()
        self.setUp()
        rc, verdict = self.execute(
            FakeScanner(har_kwargs={"probe_status": 401, "probe_body": '{"ok":false}'}),
            env=self.env(OPENFDD_ZAP_MAX_REQUESTS="2"), negative_control=True,
        )
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("request budget exceeded", verdict["notes"])

    def test_negative_plan_is_probe_only_with_no_positive_auth_expectations(self):
        scanner = FakeScanner(har_kwargs={"probe_status": 401, "probe_body": '{"ok":false}'})
        with mock.patch.object(af, "stage_openapi_spec", side_effect=AssertionError("not needed for probes")):
            rc, verdict = self.execute(scanner, env=self.env(OPENFDD_ZAP_AF_ACTIVE="1"), negative_control=True)
        self.assertEqual(rc, 0, verdict["notes"])
        plan = yaml.safe_load((self.work / "af_plan.yaml").read_text(encoding="utf-8"))
        self.assertEqual([j["type"] for j in plan["jobs"]], ["requestor"] * 3 + ["export", "report"])
        self.assertFalse(verdict["active_scan"])
        self.assertNotIn("verification", plan["env"]["contexts"][0]["authentication"])
        for job in plan["jobs"][:3]:
            self.assertNotIn("tests", job)
            self.assertNotIn("responseCode", job["requests"][0])


# --------------------------------------------------------------------------- #
# Strict alert parsing + per-instance dispositions
# --------------------------------------------------------------------------- #


class ZapAfStrictReportTest(ExecuteHarness):
    target = af.parse_disposable_origin(ORIGIN)

    def test_fixture_parses(self):
        rep = af.parse_traditional_report(load_report("report_medium_csp.json"), self.target)
        self.assertEqual(rep.by_risk()["Medium"], 1)
        inst = rep.instances[0]
        self.assertEqual(inst.key()[:4], ("10055", "GET", "/", "Content-Security-Policy"))

    def test_malformed_alerts_raise(self):
        base = load_report("report_medium_csp.json")

        def alert(d):
            return d["site"][0]["alerts"][0]

        def inst(d):
            return alert(d)["instances"][0]

        mutations = {
            "unknown_alert_field": lambda d: alert(d).__setitem__("bogus", "x"),
            "missing_pluginid": lambda d: alert(d).pop("pluginid"),
            "riskcode_not_numeric": lambda d: alert(d).__setitem__("riskcode", "medium"),
            "riskdesc_disagrees": lambda d: alert(d).__setitem__("riskdesc", "Low (High)"),
            "count_mismatch": lambda d: alert(d).__setitem__("count", "2"),
            "instances_not_list": lambda d: alert(d).__setitem__("instances", {}),
            "empty_instances": lambda d: (alert(d).__setitem__("instances", []), alert(d).__setitem__("count", "0")),
            "instance_unknown_field": lambda d: inst(d).__setitem__("extra", "1"),
            "instance_out_of_scope": lambda d: inst(d).__setitem__("uri", "http://evil.example/"),
            "instance_bad_method": lambda d: inst(d).__setitem__("method", "BREW"),
            "alert_not_object": lambda d: d["site"][0]["alerts"].__setitem__(0, "x"),
            "site_wrong_target": lambda d: d["site"][0].__setitem__("@name", "http://127.0.0.1:18081"),
            "unknown_root_field": lambda d: d.__setitem__("openfdd_auth_traffic", {}),
            "empty_site": lambda d: d.__setitem__("site", [{}]),
            "no_sites": lambda d: d.__setitem__("site", []),
            "systemic_not_bool": lambda d: alert(d).__setitem__("systemic", "false"),
        }
        for name, fn in mutations.items():
            with self.subTest(name=name):
                data = copy.deepcopy(base)
                fn(data)
                with self.assertRaises(af.EvidenceError):
                    af.parse_traditional_report(data, self.target)

    def test_malformed_report_is_error_not_skip(self):
        data = load_report("report_medium_csp.json")
        data["site"][0]["alerts"].append({"riskcode": "3"})
        rc, verdict = self.execute(FakeScanner(report=data))
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("malformed ZAP report", verdict["notes"])

    def test_stopping_insight_fails(self):
        data = load_report("report_clean.json")
        data["stoppingInsight"] = {"level": "High", "reason": "x", "site": ORIGIN, "key": "k", "description": "d", "statistic": 1}
        rc, verdict = self.execute(FakeScanner(report=data))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("stoppingInsight", verdict["notes"])

    def test_high_fails(self):
        data = load_report("report_medium_csp.json")
        a = data["site"][0]["alerts"][0]
        a.update(riskcode="3", riskdesc="High (High)")
        rc, verdict = self.execute(FakeScanner(report=data))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertEqual(verdict["high_alerts"], 1)


def disposition_for(instance: dict, **overrides) -> dict:
    d = {
        "id": "csp-root",
        "plugin_id": instance["plugin_id"],
        "method": instance["method"],
        "route": instance["route"],
        "param": instance["param"],
        "evidence_sha256": instance["evidence_sha256"],
        "alert_name": instance["alert_name"],
        "component": "openfdd-web",
        "owner": "qa",
        "rationale": "fixture",
        "expiry": "2999-12-31",
        "retest": "fixture",
        "candidate_binding": "fixture",
    }
    d.update(overrides)
    return d


class ZapAfDispositionTest(ExecuteHarness):
    target = af.parse_disposable_origin(ORIGIN)

    def csp_instance(self) -> dict:
        return af.parse_traditional_report(load_report("report_medium_csp.json"), self.target).instances[0].as_dict()

    def write_dispositions(self, items: list[dict], **root) -> Path:
        p = self.root / "dispositions.json"
        p.write_text(json.dumps({"schema_version": af.DISPOSITION_SCHEMA, "dispositions": items, **root}), encoding="utf-8")
        return p

    def test_repo_dispositions_load_strictly(self):
        self.assertEqual(af.load_dispositions(), [])

    def test_undispositioned_medium_fails(self):
        rc, verdict = self.execute(FakeScanner(report=load_report("report_medium_csp.json")))
        self.assertEqual(verdict["status"], "FAIL")
        self.assertEqual(verdict["medium_undispositioned"], 1)
        self.assertIn("unaccepted Medium", verdict["notes"])

    def test_exact_instance_disposition_passes(self):
        path = self.write_dispositions([disposition_for(self.csp_instance())])
        rc, verdict = self.execute(FakeScanner(report=load_report("report_medium_csp.json")), dispositions=path)
        self.assertEqual(rc, 0, verdict["notes"])
        self.assertEqual(verdict["medium_dispositions_applied"], ["csp-root"])

    def test_unaccepted_adjacent_instance_fails(self):
        path = self.write_dispositions([disposition_for(self.csp_instance())])
        data = load_report("report_medium_csp.json")
        alert = data["site"][0]["alerts"][0]
        adjacent = dict(alert["instances"][0], uri=ORIGIN + "/index.html")
        alert["instances"].append(adjacent)
        alert["count"] = "2"
        rc, verdict = self.execute(FakeScanner(report=data), dispositions=path)
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertEqual(verdict["medium_undispositioned"], 1)
        self.assertIn("/index.html", verdict["notes"])

    def test_changed_evidence_or_param_is_unaccepted(self):
        inst = self.csp_instance()
        disps = af.load_dispositions(self.write_dispositions([disposition_for(inst)]))
        rep = af.parse_traditional_report(load_report("report_medium_csp.json"), self.target)
        base = rep.instances[0]
        variants = [
            af.AlertInstance(**{**base.__dict__, "evidence_sha256": hashlib.sha256(b"other").hexdigest()}),
            af.AlertInstance(**{**base.__dict__, "param": "X-Frame-Options"}),
            af.AlertInstance(**{**base.__dict__, "method": "POST"}),
            af.AlertInstance(**{**base.__dict__, "name": "Other name"}),
        ]
        accepted, unaccepted = af.apply_dispositions(variants, disps)
        self.assertEqual(accepted, [])
        self.assertEqual(len(unaccepted), 4)

    def test_disposition_file_defects_raise(self):
        inst = self.csp_instance()
        cases = {
            "expired": [disposition_for(inst, expiry="2000-01-01")],
            "bad_expiry": [disposition_for(inst, expiry="12/31/2999")],
            "duplicate_id": [disposition_for(inst), disposition_for(inst, route="/x")],
            "duplicate_key": [disposition_for(inst), disposition_for(inst, id="other")],
            "unknown_field": [disposition_for(inst, extra="x")],
            "plugin_level_only": [{k: v for k, v in disposition_for(inst).items() if k not in ("route", "evidence_sha256")}],
            "bad_hash": [disposition_for(inst, evidence_sha256="abc")],
        }
        for name, items in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(af.EvidenceError):
                    af.load_dispositions(self.write_dispositions(items), today="2026-10-22")
        with self.assertRaises(af.EvidenceError):
            p = self.root / "d.json"
            p.write_text(json.dumps({"schema_version": "openfdd.zap_medium_disposition.v1", "dispositions": []}))
            af.load_dispositions(p)


# --------------------------------------------------------------------------- #
# Raw evidence immutability
# --------------------------------------------------------------------------- #


class ZapAfRawEvidenceTest(ExecuteHarness):
    def test_raw_report_is_write_once_and_hashed(self):
        raw = json.dumps(load_report("report_clean.json"), indent=1).encode()
        rc, verdict = self.execute(FakeScanner(report=raw))
        self.assertEqual(rc, 0, verdict["notes"])
        sha = hashlib.sha256(raw).hexdigest()
        self.assertEqual(verdict["raw_report"]["sha256"], sha)
        self.assertEqual((self.work / af.REPORT_FILE).read_bytes(), raw)
        archive = ROOT / verdict["raw_report"]["archive"] if not verdict["raw_report"]["archive"].startswith("/") else Path(verdict["raw_report"]["archive"])
        self.assertEqual(archive.read_bytes(), raw)
        self.assertFalse(os.stat(archive).st_mode & stat.S_IWUSR)
        derived = verdict["derived"]
        self.assertEqual(set(derived), {"alerts.derived.json", "auth_evidence.derived.json"})
        for meta in derived.values():
            p = Path(meta["path"]) if meta["path"].startswith("/") else ROOT / meta["path"]
            self.assertNotEqual(p.resolve(), archive.resolve())
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), meta["sha256"])
        with self.assertRaises(FileExistsError):
            af.write_once(archive, b"tamper")


# --------------------------------------------------------------------------- #
# Budgets, timeouts, cancel cleanup
# --------------------------------------------------------------------------- #


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True


_SPAWN_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(p.pid, flush=True)\n"
    "time.sleep(120)\n"
)


@unittest.skipUnless(hasattr(os, "killpg"), "POSIX process groups required")
class ZapAfProcessControlTest(unittest.TestCase):
    def tearDown(self):
        af._CANCEL.clear()

    def _wait_dead(self, pid: int) -> bool:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not _alive(pid):
                return True
            time.sleep(0.1)
        return False

    def test_timeout_kills_process_group_and_removes_container(self):
        with mock.patch.object(af, "_docker_rm_force") as rm:
            res = af.run_owned_process(
                [sys.executable, "-c", _SPAWN_GRANDCHILD],
                env=dict(os.environ),
                timeout_s=1.0,
                container_name="openfdd-zap-af-scan-test",
            )
        self.assertTrue(res.timed_out)
        self.assertIsNone(res.returncode)
        self.assertLess(res.duration_s, 20)
        rm.assert_called_once_with("openfdd-zap-af-scan-test")
        self.assertTrue(self._wait_dead(int(res.stdout.split()[0])), "grandchild survived timeout")

    def test_cancel_kills_process_group_and_removes_container(self):
        timer = threading.Timer(0.8, af._CANCEL.set)
        timer.start()
        try:
            with mock.patch.object(af, "_docker_rm_force") as rm:
                res = af.run_owned_process(
                    [sys.executable, "-c", _SPAWN_GRANDCHILD],
                    env=dict(os.environ),
                    timeout_s=60,
                    container_name="openfdd-zap-af-scan-cancel",
                )
        finally:
            timer.cancel()
        self.assertTrue(res.cancelled)
        rm.assert_called_once_with("openfdd-zap-af-scan-cancel")
        self.assertTrue(self._wait_dead(int(res.stdout.split()[0])), "grandchild survived cancel")

    def test_budget_config_validation(self):
        with self.assertRaises(af.ConfigError):
            af.load_budget({"OPENFDD_ZAP_MAX_WALL_SECONDS": "5"})
        with self.assertRaises(af.ConfigError):
            af.load_budget({"OPENFDD_ZAP_MAX_REQUESTS": "-1"})
        b = af.load_budget({})
        self.assertEqual((b.max_wall_seconds, b.max_requests), (af.DEFAULT_MAX_WALL_SECONDS, af.DEFAULT_MAX_REQUESTS))
        exhausted = af.Budget(60, 1, started=time.monotonic() - 61)
        with self.assertRaises(af.BudgetExceeded):
            exhausted.timeout(10)


class ZapAfExecuteTimeoutTest(ExecuteHarness):
    def test_scanner_timeout_fails_and_deletes_secret_bearing_history(self):
        rc, verdict = self.execute(FakeScanner(timed_out=True))
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("wall-clock budget exhausted", verdict["notes"])
        self.assertFalse((self.work / af.MESSAGES_FILE).exists())

    def test_scanner_cancel_is_error(self):
        rc, verdict = self.execute(FakeScanner(cancelled=True))
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("cancelled", verdict["notes"])
        self.assertFalse((self.work / af.MESSAGES_FILE).exists())

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX required")
    def test_sigterm_during_real_scanner_subprocess_cleans_up(self):
        fake = self.root / "zap.sh"
        fake.write_text(f"#!{sys.executable}\n" + _SPAWN_GRANDCHILD, encoding="utf-8")
        fake.chmod(0o700)
        stop = threading.Event()

        def send_sigterm_once_scanner_starts():
            while not stop.is_set():
                if (self.work / "af_plan.yaml").exists():
                    time.sleep(0.8)
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                time.sleep(0.05)

        timer = threading.Thread(target=send_sigterm_once_scanner_starts, daemon=True)
        with (
            mock.patch.dict(os.environ, self.env(OPENFDD_ZAP_AF_EXECUTE="1"), clear=True),
            mock.patch.object(af, "detect_zap", return_value=("zap.sh", str(fake))),
            mock.patch.object(af, "fetch_auth_me_preflight", return_value=dict(PREFLIGHT_OK)),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            timer.start()
            try:
                started = time.monotonic()
                rc = af.main(["--out", str(self.out)])
            finally:
                stop.set()
        verdict = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(rc, 1)
        self.assertEqual(verdict["status"], "ERROR")
        self.assertIn("cancelled", verdict["notes"])
        self.assertLess(time.monotonic() - started, 30)
        pid = int((self.work / "zap_af.stdout.log").read_text().split()[0])
        deadline = time.monotonic() + 10
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(_alive(pid), "scanner grandchild survived SIGTERM")


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #


class ZapAfSecretCanaryTest(ExecuteHarness):
    def canary(self) -> str:
        return f"Bearer openfdd-canary-{uuid.uuid4().hex}"

    def assert_canary_absent(self, canary: str, scanner: FakeScanner) -> None:
        token = canary.split(" ", 1)[1]
        for path, data in self.all_artifact_bytes():
            self.assertNotIn(token.encode(), data, f"canary leaked into {path}")
        for cmd, _env, _stdin in scanner.calls:
            self.assertFalse(any(token in part for part in cmd), f"canary in argv: {cmd[:4]}")

    def test_canary_never_reaches_argv_logs_or_artifacts(self):
        canary = self.canary()
        scanner = FakeScanner(leak_to_stdout=True)
        rc, verdict = self.execute(
            scanner, env=self.env(ZAP_AUTH_HEADER_VALUE=canary), mode=("docker", af._PINNED_ZAP_DIGEST)
        )
        self.assertEqual(rc, 0, verdict["notes"])
        self.assertEqual(scanner.scanner_env["ZAP_AUTH_HEADER_VALUE"], canary)
        zap_cmd = next(c for c, _e, _s in scanner.calls if c[:2] == ["docker", "run"])
        self.assertIn("ZAP_AUTH_HEADER_VALUE", zap_cmd)
        self.assert_canary_absent(canary, scanner)
        self.assertIn("<redacted", (self.work / "zap_af.stdout.log").read_text())

    def test_canary_in_raw_report_is_deleted_and_errors(self):
        canary = self.canary()
        scanner = FakeScanner(leak_to_report=True)
        rc, verdict = self.execute(scanner, env=self.env(ZAP_AUTH_HEADER_VALUE=canary))
        self.assertEqual(verdict["status"], "ERROR")
        self.assertFalse((self.work / af.REPORT_FILE).exists())
        self.assert_canary_absent(canary, scanner)

    def test_canary_on_failure_paths(self):
        canary = self.canary()
        for kwargs in ({"har": "broken_injection"}, {"timed_out": True}, {"rc": 3}):
            with self.subTest(**kwargs):
                self.tearDown()
                self.setUp()
                scanner = FakeScanner(leak_to_stdout=True, **kwargs)
                self.execute(scanner, env=self.env(ZAP_AUTH_HEADER_VALUE=canary))
                self.assert_canary_absent(canary, scanner)

    def test_private_credential_file(self):
        canary = self.canary()
        p = self.root / "auth"
        p.write_text(canary + "\n", encoding="utf-8")
        p.chmod(0o644)
        with self.assertRaises(af.ConfigError):
            af.load_scanner_auth_header({"ZAP_AUTH_HEADER_FILE": str(p)})
        p.chmod(0o600)
        self.assertEqual(af.load_scanner_auth_header({"ZAP_AUTH_HEADER_FILE": str(p)}), canary)
        link = self.root / "auth-link"
        link.symlink_to(p)
        with self.assertRaises(af.ConfigError):
            af.load_scanner_auth_header({"ZAP_AUTH_HEADER_FILE": str(link)})
        with self.assertRaises(af.ConfigError):
            af.load_scanner_auth_header({"ZAP_AUTH_HEADER_VALUE": "Bearer x\r\nX-Injected: 1"})

    def test_docker_preflight_passes_credential_on_stdin_not_argv(self):
        canary = self.canary()
        target = af.parse_disposable_origin("http://web:8080", docker_network="openfdd-zap-af-t1")
        captured = {}

        def fake(cmd, *, env, timeout_s, cwd=None, container_name=None, stdin_bytes=None):
            captured.update(cmd=cmd, env=env, stdin=stdin_bytes, name=container_name)
            body = identity_body()
            return af.ProcResult(0, f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{body}", "")

        with mock.patch.object(af, "run_owned_process", side_effect=fake):
            res = af.fetch_auth_me_preflight(
                target=target, auth_header=canary, expected_username=USERNAME, budget=af.Budget(600, 10),
                docker_network="openfdd-zap-af-t1",
            )
        self.assertTrue(res["ok"], res)
        token = canary.split(" ", 1)[1]
        self.assertFalse(any(token in part for part in captured["cmd"]))
        self.assertNotIn(token, json.dumps(captured["env"]))
        self.assertIn(token.encode(), captured["stdin"])
        self.assertIn("--max-redirs", captured["cmd"])
        self.assertTrue(captured["name"].startswith("openfdd-zap-preflight-"))


# --------------------------------------------------------------------------- #
# Selftest / idle
# --------------------------------------------------------------------------- #


class ZapAfSelftestTest(unittest.TestCase):
    def test_selftest_exits_blocked_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "zap_af_verdict.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = af.main(["--selftest", "--out", str(out)])
            self.assertEqual(rc, 2, "selftest must be BLOCKED (exit 2), never PASS")
            verdict = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(verdict["status"], "BLOCKED")
            self.assertTrue(verdict["plan_hygiene_ok"])
            self.assertEqual(verdict["suite"], "zap_af_authenticated_v2")
            self.assertIsNone(verdict["high_alerts"])
            self.assertIsNone(verdict["medium_alerts"])
            self.assertFalse(verdict["alert_counts_evaluated"])

    def test_scan_pass_cannot_claim_unevaluated_counts(self):
        verdict = af.build_verdict(
            status="PASS", mode="execute", plan_hygiene_ok=True,
            high_alerts=None, medium_alerts=None, zap_available=True,
            active_scan=False, notes="fixture", alert_counts_evaluated=False,
        )
        errors = af.verdict_schema_ok(verdict)
        self.assertTrue(any("evaluated" in e for e in errors))
        self.assertTrue(any("known" in e for e in errors))
        verdict.update(high_alerts=0, medium_alerts=0, alert_counts_evaluated=True)
        self.assertEqual(af.verdict_schema_ok(verdict), [])

    def test_bad_counts_cannot_be_serialized_as_valid_evidence(self):
        for count in (-1, True, "0"):
            verdict = af.build_verdict(
                status="ERROR", mode="execute", plan_hygiene_ok=True,
                high_alerts=count, medium_alerts=None, zap_available=True,
                active_scan=False, notes="fixture",
            )
            self.assertTrue(af.verdict_schema_ok(verdict))

    def test_execute_without_env_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "v.json"
            env = {k: v for k, v in os.environ.items() if k not in ("OPENFDD_ZAP_AF_EXECUTE", "ZAP_TARGET_ORIGIN", "ZAP_AUTH_HEADER_VALUE")}
            with (
                mock.patch.dict(os.environ, env, clear=True),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc = af.main(["--out", str(out)])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "BLOCKED")

    def test_verdict_redaction_keeps_json_valid(self):
        v = af.build_verdict(status="ERROR", mode="x", notes='plan contains hardcoded Bearer token"x', plan_hygiene_ok=False,
                             high_alerts=0, medium_alerts=0, zap_available=False, active_scan=False)
        self.assertEqual(v["notes"], "plan contains hardcoded Bearer <redacted>")


class ZapDigestPinTest(unittest.TestCase):
    def test_default_image_is_digest_pinned(self):
        self.assertTrue(af.zap_image_is_digest_pinned(af.DEFAULT_ZAP_IMAGE))

    def test_moving_tag_rejected_when_required(self):
        self.assertFalse(af.zap_image_is_digest_pinned("ghcr.io/zaproxy/zaproxy:stable"))


if __name__ == "__main__":
    unittest.main()
