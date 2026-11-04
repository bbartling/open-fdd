"""Offline tests for the finite requestor-only passive ZAP gate."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "scripts/qualification/zap/run_static_passive.py"
SPEC = importlib.util.spec_from_file_location("run_static_passive", PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

ORIGIN = "http://central:8080"
NONCE = "0123456789abcdef0123456789abcdef"
AUTH = "Bearer fixture-token-0123456789abcdef"
USER = "admin"
VERSION = "4.0.10+abcdef123456"


def _entry(url: str, *, auth: str = AUTH, status: int = 200, body: str = "") -> dict:
    headers = [{"name": "Authorization", "value": auth}]
    path = url.removeprefix(ORIGIN)
    if path == "/api/auth/me":
        phase = {"before": 0, "during": 1, "after": 2}
        marker = next((p for p in phase if p in body), None)
        if marker:
            headers.append({"name": mod.PROBE, "value": marker + "-" + NONCE})
        elif auth != AUTH:
            headers.append({"name": mod.PROBE, "value": "invalid-" + NONCE})
    if path == "/api/version":
        body = json.dumps({"ok": True, "service": "openfdd-central", "version": VERSION})
    elif path == "/api/auth/me" and auth != AUTH:
        body = '{"ok":false}'
    elif path == "/api/auth/me":
        body = '{"ok":true,"username":"admin","role":"admin"}'
    return {"_zapMessageType": 15,
            "request": {"method": "GET", "url": url, "headers": headers},
            "response": {"status": status, "headers": [{"name": "Content-Type", "value": "application/json"}],
                         "content": {"mimeType": "application/json", "text": body}}}


def fixture_har() -> bytes:
    entries = [_entry(ORIGIN + p, body="phase=" + phase)
               for phase, p in [("before", "/api/auth/me")]]
    entries += [_entry(ORIGIN + p) for p in mod.PATHS[1:5]]
    entries.append(_entry(ORIGIN + "/api/auth/me", body="phase=during"))
    entries += [_entry(ORIGIN + p) for p in mod.PATHS[5:]]
    entries.append(_entry(ORIGIN + "/api/auth/me", auth="Bearer invalid-static-passive", status=401))
    entries.append(_entry(ORIGIN + "/api/auth/me", body="phase=after"))
    for entry in entries:
        entry["_zapMessageType"] = 15
        entry["request"]["postData"] = {"mimeType": "", "text": "", "params": []}
    for path in ("", "/api", "/api/auth", "/api/fdd", "/api/providers", "/api/sites",
                 "/app", "/app/assets", "/app/assets/js"):
        node = _entry(ORIGIN + path, status=0)
        node["_zapMessageType"] = 0
        node["response"]["headers"] = []
        node["response"]["content"] = {"text": ""}
        node["request"]["postData"] = {"mimeType": "", "text": "", "params": []}
        entries.append(node)
    return json.dumps({"log": {"entries": entries}}).encode()


class StaticPassiveTests(unittest.TestCase):
    def test_plan_is_exact_finite_get_only_and_has_no_external_scan_jobs(self):
        plan = mod.build_plan(ORIGIN, NONCE, AUTH, Path("/tmp"))
        context = plan["env"]["contexts"][0]
        self.assertEqual(context["urls"], [ORIGIN])
        self.assertTrue(__import__("re").fullmatch(context["includePaths"][0], ORIGIN + "/app/"))
        self.assertFalse(__import__("re").fullmatch(context["includePaths"][0], "http://central:9999/app/"))
        jobs = plan["jobs"]
        reqs = [r for j in jobs if j["type"] == "requestor" for r in j["requests"]]
        self.assertEqual(len(reqs), 12)
        self.assertTrue(all(r["method"] == "GET" and r["url"].startswith(ORIGIN + "/") for r in reqs))
        self.assertEqual({j["type"] for j in jobs}, {"requestor", "passiveScan-wait", "export", "report"})
        self.assertTrue(all(r["headers"][0] == "Authorization:" + AUTH for r in reqs if "invalid" not in r["name"]))
        self.assertFalse(any("openapi" in str(j).lower() and j["type"] != "requestor" for j in jobs))

    def test_traffic_receipt_retains_counts_without_secret_headers(self):
        receipt = mod.summarize_traffic(fixture_har())
        self.assertEqual(receipt["observed_message_count"], 21)
        self.assertEqual(sum(r["count"] for r in receipt["traffic_summary"]), 21)
        self.assertNotIn(AUTH, json.dumps(receipt))
        self.assertNotIn("authorization", json.dumps(receipt).lower())

    def test_traffic_receipt_exposes_only_safe_zap_type_and_size_metadata(self):
        har = json.loads(fixture_har())
        first = har["log"]["entries"][0]
        first["request"]["postData"] = {"text": "synthetic-body"}
        receipt = mod.summarize_traffic(json.dumps(har).encode())
        first_group = next(row for row in receipt["traffic_summary"]
                           if row["path"] == "/api/auth/me" and row["status"] == 200
                           and row["request_body_bytes"] == len("synthetic-body"))
        self.assertEqual(first_group["zap_message_type"], 15)
        self.assertEqual(first_group["request_body_bytes"], len("synthetic-body"))
        self.assertEqual(first_group["response_body_bytes"], len(b'{"ok":true,"username":"admin","role":"admin"}'))
        self.assertEqual(first_group["request_header_count"], 2)
        self.assertEqual(first_group["response_header_count"], 1)

        # A synthetic Sites Tree folder reference has no real response. Keep it
        # visible as a distinct type/status/size group for diagnostic review.
        har["log"]["entries"].append({
            "_zapMessageType": 0,
            "request": {"method": "GET", "url": ORIGIN + "/api", "headers": []},
            "response": {"status": 0, "headers": [], "content": {"text": ""}},
        })
        receipt = mod.summarize_traffic(json.dumps(har).encode())
        structural = next(row for row in receipt["traffic_summary"] if row["path"] == "/api")
        self.assertEqual(structural["zap_message_type"], 0)
        self.assertEqual(structural["status"], 0)
        self.assertEqual(structural["response_body_bytes"], 0)
        self.assertEqual(structural["response_header_count"], 0)
        encoded = json.dumps(receipt)
        self.assertNotIn(AUTH, encoded)
        self.assertNotIn("synthetic-body", encoded)
        self.assertNotIn("admin", encoded)

    def test_valid_har_proves_three_auth_phases_and_bad_bearer(self):
        result = mod.validate_har(fixture_har(), origin=ORIGIN, nonce=NONCE,
                                  bearer=AUTH, expected_username=USER, expected_version=VERSION)
        self.assertEqual(result["auth_positive_phases"], ["before", "during", "after"])
        self.assertEqual(result["candidate_version"], "4.0.10+abcdef123456")
        self.assertEqual(result["wire_request_count"], 12)
        self.assertEqual(result["artifact_node_count"], 9)
        self.assertEqual(result["exported_har_entry_count"], 21)

    def test_temporary_records_are_not_a_status_zero_bypass(self):
        import copy
        original = json.loads(fixture_har())
        mutations = [
            lambda e: e["request"].update(url=ORIGIN + "/unexpected"),
            lambda e: e["response"].update(status=200),
            lambda e: e.update(_zapMessageType=15),
            lambda e: e.update(_zapMessageType=False),
            lambda e: e.update(_zapMessageType=0.0),
            lambda e: e["response"]["content"].update(text="unexpected body"),
            lambda e: e["response"].update(headers=[{"name":"X-Test","value":"1"}]),
            lambda e: e["request"].update(postData={"text":"unexpected body"}),
        ]
        for mutation in mutations:
            har = copy.deepcopy(original)
            mutation(har["log"]["entries"][-1])
            self._must_reject(json.dumps(har).encode())
        for kind in ("duplicate_node", "missing_node", "extra_wire", "missing_wire", "failed_wire"):
            har = copy.deepcopy(original)
            entries = har["log"]["entries"]
            if kind == "duplicate_node": entries.append(copy.deepcopy(entries[-1]))
            elif kind == "missing_node": entries.pop()
            elif kind == "extra_wire": entries.append(copy.deepcopy(entries[1]))
            elif kind == "missing_wire": entries.pop(1)
            else: entries[1]["response"]["status"] = 0
            self._must_reject(json.dumps(har).encode())
        har = copy.deepcopy(original)
        har["log"]["entries"][1]["request"]["postData"] = {"text": "not planned"}
        self._must_reject(json.dumps(har).encode())

    def _must_reject(self, raw: bytes):
        with self.assertRaises(mod.GateError):
            mod.validate_har(raw, origin=ORIGIN, nonce=NONCE, bearer=AUTH,
                             expected_username=USER, expected_version=VERSION)

    def test_missing_probe_fails(self):
        har = json.loads(fixture_har())
        har["log"]["entries"] = [e for e in har["log"]["entries"]
                                 if not any(h["name"] == mod.PROBE and h["value"].startswith("during-")
                                            for h in e["request"]["headers"])]
        self._must_reject(json.dumps(har).encode())

    def test_unexpected_port_fails(self):
        har = json.loads(fixture_har())
        har["log"]["entries"][1]["request"]["url"] = "http://central:9999/app/"
        self._must_reject(json.dumps(har).encode())

    def test_unexpected_method_fails(self):
        har = json.loads(fixture_har())
        har["log"]["entries"][1]["request"]["method"] = "POST"
        self._must_reject(json.dumps(har).encode())

    def test_invalid_bearer_accepted_fails(self):
        har = json.loads(fixture_har())
        bad = next(e for e in har["log"]["entries"] if any(h["name"] == mod.PROBE and h["value"].startswith("invalid-") for h in e["request"]["headers"]))
        bad["response"]["status"] = 200
        bad["response"]["content"]["text"] = '{"ok":true,"username":"admin"}'
        self._must_reject(json.dumps(har).encode())

    def test_bad_bearer_401_must_have_ok_false(self):
        har = json.loads(fixture_har())
        bad = next(e for e in har["log"]["entries"] if any(h["name"] == mod.PROBE and h["value"].startswith("invalid-") for h in e["request"]["headers"]))
        bad["response"]["content"]["text"] = '{"ok":true,"username":"admin"}'
        self._must_reject(json.dumps(har).encode())

    def test_bad_identity_fails(self):
        har = json.loads(fixture_har())
        first = next(e for e in har["log"]["entries"] if any(h["name"] == mod.PROBE and h["value"].startswith("before-") for h in e["request"]["headers"]))
        first["response"]["content"]["text"] = '{"ok":true,"username":"someone-else","role":"admin"}'
        self._must_reject(json.dumps(har).encode())

    def test_bad_nonce_fails(self):
        har = json.loads(fixture_har())
        for ent in har["log"]["entries"]:
            for h in ent["request"]["headers"]:
                if h["name"] == mod.PROBE and h["value"].startswith("after-"):
                    h["value"] = "after-wrongnonce00000000"
        self._must_reject(json.dumps(har).encode())

    def test_missing_or_truncated_har_fails(self):
        for value in (b"", b"{\"log\":", b"not json"):
            self._must_reject(value)

    def test_bad_version_identity_fails(self):
        har = json.loads(fixture_har())
        ent = next(e for e in har["log"]["entries"] if e["request"]["url"].endswith("/api/version"))
        ent["response"]["content"]["text"] = '{"ok":true,"service":"other","version":"4.0.10"}'
        self._must_reject(json.dumps(har).encode())

    def _report(self, alerts=None):
        return {"@programName": "ZAP", "@version": "2.16.0", "site": [{
            "@name": ORIGIN, "@host": "central", "@port": "8080", "@ssl": "false",
            "alerts": [] if alerts is None else alerts}]}

    def _alert(self, riskcode="0", riskdesc="Informational (Medium)", uri=None):
        return {"pluginid": "10049", "alertRef": "10049", "alert": "Storable and Cacheable Content",
                "name": "Storable and Cacheable Content", "riskcode": riskcode, "confidence": "2",
                "riskdesc": riskdesc, "instances": [{"uri": uri or ORIGIN + "/app/", "method": "GET",
                    "param": "", "attack": "", "evidence": ""}], "count": "1"}

    def test_alert_summary_has_explicit_zero_counts_and_scope_check(self):
        clean = mod._alert_summary(json.dumps(self._report()).encode(), origin=ORIGIN)
        self.assertEqual(clean["alert_counts_by_risk"],
                         {"Informational": 0, "Low": 0, "Medium": 0, "High": 0})
        report = self._report([self._alert()])
        result = mod._alert_summary(json.dumps(report).encode(), origin=ORIGIN)
        self.assertEqual(result["alert_counts_by_risk"]["Informational"], 1)
        self.assertEqual(result["alert_instances"], [{"rule_id": "10049",
                         "risk": "Informational", "method": "GET", "path": "/app/"}])
        self.assertFalse(result["alert_instances_truncated"])
        report["site"][0]["alerts"][0]["instances"][0]["uri"] = "https://outside.example/"
        with self.assertRaises(mod.GateError):
            mod._alert_summary(json.dumps(report).encode(), origin=ORIGIN)

    def test_missing_alert_fields_cannot_pass_as_clean(self):
        report = self._report([{"pluginid": "10001"}])
        with self.assertRaises(mod.GateError):
            mod._alert_summary(json.dumps(report).encode(), origin=ORIGIN)

    def test_high_medium_scan_findings_fail_and_low_info_need_review(self):
        self.assertEqual(mod.classify_scan({"High": 1, "Medium": 0, "Low": 0, "Informational": 0}), "FAIL")
        self.assertEqual(mod.classify_scan({"High": 0, "Medium": 1, "Low": 0, "Informational": 0}), "FAIL")
        self.assertEqual(mod.classify_scan({"High": 0, "Medium": 0, "Low": 1, "Informational": 0}), "REVIEW")
        self.assertEqual(mod.classify_scan({"High": 0, "Medium": 0, "Low": 0, "Informational": 0}), "PASS")

    def test_passive_queue_must_be_confirmed_drained(self):
        mod.require_passive_drain("Job passiveScan-wait started\nJob passiveScan-wait finished\n")
        with self.assertRaises(mod.GateError):
            mod.require_passive_drain("Job passiveScan-wait started\n")

    def test_scanner_progress_tail_scrubs_bearer_and_is_bounded(self):
        output = "before\nAuthorization: " + AUTH + "\nafter\n"
        result = mod.sanitize_progress(output, AUTH)
        self.assertEqual(len(result), 3)
        self.assertNotIn(AUTH, "\n".join(result))
        self.assertIn("<redacted-secret>", result[1])

    def test_stdout_capture_enforces_memory_cap(self):
        import subprocess
        proc = subprocess.Popen([sys.executable, "-c", "print('x' * 10000)"], stdout=subprocess.PIPE)
        with self.assertRaises(mod.CapturedScanError) as raised:
            mod._bounded_communicate(proc, timeout=5, max_bytes=100)
        self.assertIsNotNone(proc.returncode)
        self.assertLessEqual(len(raised.exception.output), 100)

    def test_duplicate_probe_and_wrong_probe_path_fail(self):
        har = json.loads(fixture_har())
        before = next(e for e in har["log"]["entries"] if any(h["name"] == mod.PROBE and h["value"].startswith("before-") for h in e["request"]["headers"]))
        before["request"]["headers"].append({"name": mod.PROBE, "value": "before-" + NONCE})
        self._must_reject(json.dumps(har).encode())
        har = json.loads(fixture_har())
        before = next(e for e in har["log"]["entries"] if any(h["name"] == mod.PROBE and h["value"].startswith("before-") for h in e["request"]["headers"]))
        before["request"]["url"] = ORIGIN + "/app/"
        self._must_reject(json.dumps(har).encode())

    @mock.patch.object(mod, "_inspect")
    def test_extra_owned_network_member_is_rejected(self, inspect):
        def container(cid, image, alias):
            return {"Id": cid, "Image": image, "State": {"Running": True},
                    "Config": {"Labels": {"openfdd.qualification.owner": "static-passive",
                                           "openfdd.qualification.run_nonce": NONCE}, "Env": []},
                    "HostConfig": {"PortBindings": None},
                    "NetworkSettings": {"Networks": {"qual-net": {"Aliases": [alias]}}}}
        net = {"Name": "qual-net", "Internal": True,
               "Labels": {"openfdd.qualification.owner": "static-passive", "openfdd.qualification.run_nonce": NONCE},
               "Containers": {"cid-central": {}, "cid-ts": {}, "cid-extra": {}}}
        central = container("cid-central", "sha256:" + "a" * 64, "central")
        timescale = container("cid-ts", "sha256:" + "b" * 64, "timescale")
        inspect.side_effect = [net, central, timescale]
        with self.assertRaises(mod.GateError):
            mod.validate_owned_stack(network="qual-net", central_container="central-c", timescale_container="ts-c",
                                      nonce=NONCE, central_image="sha256:" + "a" * 64,
                                      timescale_image="sha256:" + "b" * 64)

    @mock.patch.object(mod, "_inspect")
    def test_unpublished_two_member_stack_is_accepted(self, inspect):
        def container(cid, image, alias, env=None, bindings=None):
            return {"Id": cid, "Image": image, "State": {"Running": True},
                    "Config": {"Labels": {"openfdd.qualification.owner": "static-passive",
                                           "openfdd.qualification.run_nonce": NONCE}, "Env": env or []},
                    "HostConfig": {"PortBindings": bindings},
                    "NetworkSettings": {"Networks": {"qual-net": {"Aliases": [alias]}}}}
        net = {"Name": "qual-net", "Internal": True,
               "Labels": {"openfdd.qualification.owner": "static-passive", "openfdd.qualification.run_nonce": NONCE},
               "Containers": {"cid-central": {}, "cid-ts": {}}}
        central = container("cid-central", "sha256:" + "a" * 64, "central", ["OPENFDD_PROVIDER_SITES="])
        timescale = container("cid-ts", "sha256:" + "b" * 64, "timescale")
        inspect.side_effect = [net, central, timescale, central]
        mod.validate_owned_stack(network="qual-net", central_container="central-c", timescale_container="ts-c",
                                 nonce=NONCE, central_image="sha256:" + "a" * 64,
                                 timescale_image="sha256:" + "b" * 64)

    @mock.patch.object(mod, "_inspect")
    def test_host_port_binding_is_rejected(self, inspect):
        def container(cid, image, alias, bindings=None):
            return {"Id": cid, "Image": image, "State": {"Running": True},
                    "Config": {"Labels": {"openfdd.qualification.owner": "static-passive",
                                           "openfdd.qualification.run_nonce": NONCE}, "Env": []},
                    "HostConfig": {"PortBindings": bindings},
                    "NetworkSettings": {"Networks": {"qual-net": {"Aliases": [alias]}}}}
        net = {"Name": "qual-net", "Internal": True,
               "Labels": {"openfdd.qualification.owner": "static-passive", "openfdd.qualification.run_nonce": NONCE},
               "Containers": {"cid-central": {}, "cid-ts": {}}}
        central = container("cid-central", "sha256:" + "a" * 64, "central", {"8080/tcp": [{"HostPort": "8080"}]})
        timescale = container("cid-ts", "sha256:" + "b" * 64, "timescale")
        inspect.side_effect = [net, central, timescale]
        with self.assertRaises(mod.GateError):
            mod.validate_owned_stack(network="qual-net", central_container="central-c", timescale_container="ts-c",
                                     nonce=NONCE, central_image="sha256:" + "a" * 64,
                                     timescale_image="sha256:" + "b" * 64)

    @mock.patch.object(mod, "_inspect")
    @mock.patch.object(mod, "validate_images")
    def test_preflight_failure_writes_sanitized_status_without_reading_auth(self, validate_images, inspect):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "summary.json"
            args = SimpleNamespace(run_nonce=NONCE, central_image="sha256:" + "a" * 64,
                timescale_image="sha256:" + "b" * 64, zap_image=mod.ZAP_DIGEST,
                network="qual-net", central_container="central-c", timescale_container="ts-c",
                expected_username=USER, expected_version=VERSION, auth_header_file="/no/such/secret",
                output=output)
            validate_images.side_effect = mod.GateError("preflight denied")
            inspect.side_effect = mod.GateError("not created")
            summary = mod.run(args)
            self.assertEqual(summary["execution_status"], "ERROR")
            self.assertEqual(json.loads(output.read_text())["scan_verdict"], "NOT_ASSESSED")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    @mock.patch.object(mod, "_run")
    def test_missing_docker_image_fails_before_runtime(self, run):
        run.side_effect = mod.GateError("not present")
        with self.assertRaises(mod.GateError):
            mod.validate_images("sha256:" + "a" * 64, "sha256:" + "b" * 64,
                                mod.ZAP_DIGEST)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
