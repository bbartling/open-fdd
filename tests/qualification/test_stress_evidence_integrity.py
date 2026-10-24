"""Offline controls for scope, execution evidence and semantic data-path gates."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

STRESS = Path(__file__).resolve().parents[2] / "scripts/stress"
sys.path.insert(0, str(STRESS))
import helpers
import test_stress_gate_fail_closed as legacy

PASSING_CHILD = legacy.PASSING_CHILD


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, STRESS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate03 = load("stress03_integrity", "03_sparql_zone_dataframe.py")
gate08 = load("stress08_integrity", "08_sql_vs_pandas_sparql.py")
gate09 = load("stress09_integrity", "09_analytics_sql_vs_pandas.py")
gate10 = load("stress10_integrity", "10_model_crud_helpers.py")


class EvidenceProtocolTest(unittest.TestCase):
    setUp = legacy.RunGateFailClosedTest.setUp
    tearDown = legacy.RunGateFailClosedTest.tearDown
    write = legacy.RunGateFailClosedTest.write
    run_gate = legacy.RunGateFailClosedTest.run_gate

    def variant(self, change):
        extra = f"{change}\nwith open(os.environ['OPENFDD_STRESS_RESULT_FILE'], 'w') as fh:\n    json.dump(body, fh)\nsys.exit(0)"
        self.write("01_sparql_model.py", PASSING_CHILD.replace("sys.exit(0)", extra))

    def test_replayed_nonce_fails(self):
        self.variant("body['run_id'] = 'prior-run'")
        code, _ = self.run_gate()
        self.assertEqual(code, 1)

    def test_foreign_site_or_target_fails(self):
        for field in ("building_id", "base_url", "script", "script_sha256"):
            with self.subTest(field=field):
                self.variant(f"body[{field!r}] = 'wrong'")
                self.assertEqual(self.run_gate()[0], 1)

    def test_zero_assertions_not_pass(self):
        self.variant("body.update(checks=[], assertion_count=0, comparison_count=0)")
        self.assertEqual(self.run_gate()[0], 2)

    def test_duplicate_or_missing_required_assertion(self):
        self.variant("body['checks'][0]['id'] = body['checks'][1]['id']")
        self.assertEqual(self.run_gate()[0], 1)
        self.variant("body['checks'][0]['id'] = 'unrelated'")
        self.assertEqual(self.run_gate()[0], 2)

    def test_count_forgery_and_boolean_count_rejected(self):
        for value in (True, 999, -1):
            with self.subTest(value=value):
                self.variant(f"body['assertion_count'] = {value!r}")
                self.assertEqual(self.run_gate()[0], 1)

    def test_candidate_observation_must_match(self):
        self.variant("body['observed_version'] = 'old+candidate'")
        self.assertEqual(self.run_gate("--expected-version", "4.0.3+candidate")[0], 1)

    def test_password_not_forwarded_on_child_argv(self):
        self.variant("assert '--password' not in sys.argv")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.run_gate("--password", "unit-test-only")[0], 0)


class HttpBoundaryTest(unittest.TestCase):
    def test_foreign_request_and_userinfo_never_transmitted(self):
        http = helpers.HttpClient("http://127.0.0.1:99")
        with mock.patch.object(http._opener, "open") as send:
            with self.assertRaises(ValueError):
                http.request("GET", "https://foreign.invalid/api/auth/me", headers={"Authorization": "test-only"})
            send.assert_not_called()
        with self.assertRaises(ValueError):
            helpers.HttpClient("http://name:secret@127.0.0.1")

    def test_request_limit_is_preventive(self):
        http = helpers.HttpClient("http://127.0.0.1:99", max_requests=1)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status, response.headers = 200, {}
        response.read.return_value = b"{}"
        with mock.patch.object(http._opener, "open", return_value=response) as send:
            http.request("GET", "/api/health")
            with self.assertRaisesRegex(RuntimeError, "before transmission"):
                http.request("GET", "/api/health")
            self.assertEqual(send.call_count, 1)

    def test_response_budget(self):
        http = helpers.HttpClient("http://127.0.0.1:99", max_response_bytes=2)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"abc"
        with mock.patch.object(http._opener, "open", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "byte budget"):
                http.request("GET", "/api/health")

    def test_redirect_not_followed(self):
        self.assertIsNone(helpers._NoRedirect().redirect_request(None, None, 302, "", {}, "https://foreign.invalid"))

    def test_auth_error_body_is_not_printed(self):
        http = helpers.HttpClient("http://127.0.0.1:99")
        with mock.patch.object(http, "request", return_value=(401, {}, b"credential-that-must-not-be-logged")):
            with self.assertRaises(SystemExit) as error:
                helpers.login(http, password="unit-only")
            self.assertNotIn("credential-that", str(error.exception))

    def test_truncated_sparql_rejected(self):
        http = helpers.HttpClient("http://127.0.0.1:99")
        for location in ("results", "meta"):
            body = {"ok": True, location: {"truncated": True, "rows": []}}
            with mock.patch.object(http, "request", return_value=(200, {}, json.dumps(body).encode())):
                with self.assertRaisesRegex(RuntimeError, "truncated"):
                    helpers.post_sparql(http, {}, building_id="synthetic", query="SELECT ?s WHERE {?s ?p ?o}")


class ScientificCoverageTest(unittest.TestCase):
    def test_fixed_grid_oracle_blocks_unsupported_cadence(self):
        import pandas as pd
        for frequency, blocked in (("5min", False), ("1min", True)):
            with self.subTest(frequency=frequency):
                samples = [{"ts": t.isoformat(), "val": 70.0} for t in pd.date_range("2026-01-01", periods=20, freq=frequency, tz="UTC")]
                body = {"history": {"samples": samples, "ok": True, "max_points": 2000}}
                rows = [{"column": "opaque", "canonicalRole": "discharge-air-temp"}]
                with mock.patch.object(gate08, "point_resolve", return_value=body):
                    kwargs = dict(building_id="synthetic", equipment_id="E", needed=("discharge-air-temp",), role_rows=rows)
                    if blocked:
                        with self.assertRaisesRegex(gate08.MissingFixture, "300-second"):
                            gate08._build_df_from_resolve(None, {}, **kwargs)
                    else:
                        self.assertEqual(len(gate08._build_df_from_resolve(None, {}, **kwargs)), 20)

    def test_multiple_role_candidates_require_approval(self):
        rows = [{"column": col, "canonicalRole": "discharge-air-temp"} for col in ("opaqueA", "opaqueB")]
        with self.assertRaisesRegex(gate08.MissingFixture, "ambiguous"):
            gate08._build_df_from_resolve(None, {}, building_id="synthetic", equipment_id="E", needed=("discharge-air-temp",), role_rows=rows)

    def test_error_row_cannot_match_zero_oracle(self):
        row = {"rule_id": "FC1", "equipment_id": "E", "fault_hours": 0, "status": "ERROR"}
        self.assertEqual(gate08.compare_sql_to_oracle([row], "FC1", "E", 0)[0], "FAIL")

    def test_role_prefix_does_not_select_setpoint_as_sensor(self):
        self.assertIsNone(gate08._guess_role("sat_backup", "", ("discharge-air-temp",)))
        self.assertIsNone(gate08._guess_role("sat_sp", "", ("discharge-air-temp",)))
        self.assertEqual(gate08._guess_role("sat_sp", "", ("discharge-air-temp-sp",)), "discharge-air-temp-sp")

    def test_explicit_point_history_failure_cannot_hide_behind_fallback(self):
        with mock.patch.object(gate03, "point_resolve", return_value={"history": {"samples": []}}), \
             mock.patch.object(gate03, "historian_query") as fallback:
            df, _, _ = gate03.fetch_point_dataframe(None, {}, building_id="synthetic", equipment_id="E", column="x", point_iri="urn:opaque:physical")
            self.assertIsNone(df)
            fallback.assert_not_called()

    def test_no_samples_is_blocked_not_pass(self):
        args = SimpleNamespace(base_url="http://127.0.0.1:9", building_id="synthetic", user="test", password="test")
        point = {"equipmentId": "E", "column": "c", "point": "urn:opaque:point"}
        with mock.patch.object(gate03, "parse_connection", return_value=args), \
             mock.patch.object(gate03, "client"), mock.patch.object(gate03, "wait_until_ready"), \
             mock.patch.object(gate03, "login", return_value={}), \
             mock.patch.object(gate03, "post_sparql", return_value=[point]), \
             mock.patch.object(gate03, "fetch_point_dataframe", return_value=(None, {}, False)), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate03.main([]), 2)

    def test_comfort_uses_active_preset_contract_and_all_samples(self):
        row = {"equipment_id": "E", "comfort_pct": 100.0, "n": 3}
        responses = [{"rows": []}, {"analytics": {"points": [row]}}]
        with mock.patch.object(gate09, "analytics_post", side_effect=responses) as request, \
             mock.patch.object(gate09, "post_sparql", return_value=[{"equipmentId": "E", "column": "opaque", "canonicalRole": "zone-air-temp"}]), \
             mock.patch.object(gate09, "_samples_for_key", return_value=[{"val": 72}] * 3), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate09._check_comfort(None, {}, "synthetic", minimum=1), 0)
            self.assertEqual(request.call_args.args[3]["series"]["preset_id"], "zone_comfort_rank")

    def test_equal_percentage_with_different_coverage_fails(self):
        with mock.patch.object(gate09, "post_sparql", return_value=[{"equipmentId": "E", "column": "c", "canonicalRole": "zone-air-temp"}]), \
             mock.patch.object(gate09, "_samples_for_key", return_value=[{"val": 72}]), \
             contextlib.redirect_stdout(io.StringIO()):
            failure, count = gate09._comfort_for_row(None, {}, "synthetic", {"equipment_id": "E", "comfort_pct": 100, "n": 100})
            self.assertIn("coverage differs", failure)
            self.assertEqual(count, 0)

    def test_viewer_denial_is_not_crud_functionality_pass(self):
        args = SimpleNamespace(base_url="http://127.0.0.1:9", building_id="synthetic", user="test", password="test")
        http = mock.MagicMock()
        http.request.return_value = (403, {}, b'{"ok":false}')
        with mock.patch.object(gate10, "parse_connection", return_value=args), \
             mock.patch.object(gate10, "client") as client, \
             mock.patch.object(gate10, "wait_until_ready"), mock.patch.object(gate10, "login", return_value={}), \
             contextlib.redirect_stdout(io.StringIO()):
            client.return_value.__enter__.return_value = http
            self.assertEqual(gate10.main([]), 2)


if __name__ == "__main__":
    unittest.main()
