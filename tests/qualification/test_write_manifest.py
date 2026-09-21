"""Offline verdict regressions; these do not test the deployed application's security.

Run: python3 -B -m unittest discover -s tests/qualification -v
"""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/qualification/write_manifest.py"
SPEC = importlib.util.spec_from_file_location("write_manifest", MODULE_PATH)
manifest_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest_tool)


class ManifestVerdictsTest(unittest.TestCase):
    def make_manifest(self, required):
        return manifest_tool.new_manifest(
            run_id="unit", environment_class="unit", hub_base="http://example.test",
            candidate_sha=None, harness_sha=None, required_gates=required,
        )

    def record(self, manifest, gate, status, reason=None):
        manifest_tool.record_gate(manifest, gate, status, failure_reason=reason)

    def test_every_security_gate_failure_reaches_rollup_and_overall(self):
        # Independent audit inventory: deleting a mapping in production must
        # fail this test, rather than shrinking the test loop with it.
        for gate in (
            "06_zap_baseline", "07_auth_role_matrix", "11_wave_l_tenant_mode",
            "12_wave_l_parquet_isolation", "13_wave_l_mqtts_namespace",
            "14_wave_l_tenant_ui_session", "15_wave_l_tenant_budgets",
            "16_wave_l_ab_isolation", "20_wave_n_tenant_acl",
            "22_wave_o_admin_datamodel_acl", "23_wave_o_security",
            "25_security_python_harness", "25b_security_post_stress",
            "26_security_mqtt_acl",
        ):
            with self.subTest(gate=gate):
                m = self.make_manifest(["00_hub_health_edges", gate])
                self.record(m, "00_hub_health_edges", "PASS")
                self.record(m, gate, "FAIL")
                manifest_tool.finalize(m)
                self.assertEqual(m["dimensions"]["security"], "FAIL")
                self.assertEqual(m["overall"]["status"], "FAIL")
                self.assertFalse(m["overall"]["fully_qualified"])

    def test_required_incomplete_security_is_never_qualified(self):
        for status in ("ERROR", "BLOCKED", "SKIPPED", None):
            with self.subTest(status=status):
                m = self.make_manifest(["06_zap_baseline", "25_security_python_harness"])
                self.record(m, "06_zap_baseline", "PASS")
                if status:
                    self.record(m, "25_security_python_harness", status)
                manifest_tool.finalize(m)
                self.assertEqual(m["dimensions"]["security"], status or "ERROR")
                self.assertEqual(m["overall"]["status"], "BLOCKED")
                self.assertFalse(m["overall"]["fully_qualified"])

    def test_unrecorded_future_gates_do_not_invent_coverage(self):
        m = self.make_manifest(["06_zap_baseline"])
        self.record(m, "06_zap_baseline", "PASS")
        manifest_tool.finalize(m)
        self.assertNotIn("25_security_python_harness", m["gates"])
        self.assertEqual(m["dimensions"]["security"], "PASS")
        # v1 means only declared required gates; it is not full security coverage.
        self.assertTrue(m["overall"]["fully_qualified"])

    def test_no_security_evidence_has_no_security_verdict(self):
        m = self.make_manifest(["00_hub_health_edges"])
        self.record(m, "00_hub_health_edges", "PASS")
        manifest_tool.finalize(m)
        self.assertIsNone(m["dimensions"]["security"])

    def test_continuity_and_pause_resume_are_transport_evidence(self):
        for gate in ("21_wave_n_mqtts_continuity", "35_mqtt_telemetry_pause_resume"):
            with self.subTest(gate=gate):
                m = self.make_manifest(["06_zap_baseline", gate])
                self.record(m, "06_zap_baseline", "PASS")
                self.record(m, gate, "FAIL")
                manifest_tool.finalize(m)
                self.assertEqual(m["dimensions"]["security"], "PASS")
                self.assertEqual(m["dimensions"]["transport_durability"], "FAIL")
                self.assertFalse(m["overall"]["fully_qualified"])

    def test_all_na_does_not_become_pass(self):
        m = self.make_manifest(["26_security_mqtt_acl"])
        self.record(m, "26_security_mqtt_acl", "NOT_APPLICABLE", "broker absent in fixture")
        manifest_tool.finalize(m)
        self.assertEqual(m["dimensions"]["security"], "NOT_APPLICABLE")
        self.assertEqual(m["overall"]["status"], "BLOCKED")
        self.assertFalse(m["overall"]["fully_qualified"])

    def test_empty_required_set_cannot_qualify(self):
        m = manifest_tool.finalize(self.make_manifest([]))
        self.assertEqual(m["overall"]["status"], "BLOCKED")
        self.assertFalse(m["overall"]["fully_qualified"])

    def test_na_requires_reason_but_does_not_block_other_passing_gates(self):
        for reason in (None, "", "  ", "broker absent in fixture"):
            with self.subTest(reason=reason):
                m = self.make_manifest(["06_zap_baseline", "26_security_mqtt_acl"])
                self.record(m, "06_zap_baseline", "PASS")
                self.record(m, "26_security_mqtt_acl", "NOT_APPLICABLE", reason)
                manifest_tool.finalize(m)
                self.assertEqual(m["overall"]["fully_qualified"], bool(reason and reason.strip()))

    def test_failed_security_is_not_masked_by_another_skipped_gate(self):
        m = self.make_manifest(["06_zap_baseline", "20_wave_n_tenant_acl"])
        self.record(m, "06_zap_baseline", "SKIPPED")
        self.record(m, "20_wave_n_tenant_acl", "FAIL")
        manifest_tool.finalize(m)
        self.assertEqual(m["dimensions"]["security"], "FAIL")
        self.assertEqual(m["overall"]["status"], "FAIL")

    def test_corrupt_status_is_an_error_in_dimension(self):
        m = self.make_manifest(["20_wave_n_tenant_acl"])
        self.record(m, "20_wave_n_tenant_acl", "PASS")
        m["gates"]["20_wave_n_tenant_acl"]["status"] = "UNKNOWN"
        manifest_tool.finalize(m)
        self.assertEqual(m["dimensions"]["security"], "ERROR")
        self.assertFalse(m["overall"]["fully_qualified"])

    def test_finalize_cli_exit_and_saved_report_agree(self):
        for status, expected_exit in (("PASS", 0), ("FAIL", 1), ("SKIPPED", 2), (None, 2)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "manifest.json"
                summary = Path(tmp) / "summary.md"
                m = self.make_manifest(["20_wave_n_tenant_acl"])
                if status:
                    self.record(m, "20_wave_n_tenant_acl", status)
                manifest_tool.save(path, m)
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = manifest_tool.main([
                        "finalize", "--manifest", str(path), "--summary-md", str(summary),
                    ])
                saved = json.loads(path.read_text())
                self.assertEqual(rc, expected_exit)
                self.assertEqual(saved["overall"]["fully_qualified"], expected_exit == 0)
                self.assertIn(f"Status: **{saved['overall']['status']}**", summary.read_text())

    def test_required_gate36_failure_prevents_full_qualification(self):
        for gate in ("36_mv_sql_oracle_twin", "36_model_ecm_qualification"):
            with self.subTest(gate=gate):
                m = self.make_manifest(
                    ["00_hub_health_edges", "36_mv_sql_oracle_twin", "36_model_ecm_qualification"]
                )
                for required in m["required_gates"]:
                    self.record(m, required, "FAIL" if required == gate else "PASS")
                manifest_tool.finalize(m)
                self.assertEqual(m["overall"]["status"], "FAIL")
                self.assertFalse(m["overall"]["fully_qualified"])

    def test_railway_field_requires_candidate_sha(self):
        m = manifest_tool.new_manifest(
            run_id="unit",
            environment_class="railway_field",
            hub_base="https://example.test",
            candidate_sha=None,
            harness_sha="abc123",
            required_gates=["00_hub_health_edges"],
        )
        self.record(m, "00_hub_health_edges", "PASS")
        manifest_tool.finalize(m)
        self.assertFalse(m["overall"]["fully_qualified"])
        self.assertIn("candidate_sha", m["overall"]["reason"])

    def test_missing_artifact_turns_pass_gate_into_error(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            m = self.make_manifest(["00_hub_health_edges"])
            manifest_tool.record_gate(
                m,
                "00_hub_health_edges",
                "PASS",
                artifact_paths=[str(missing)],
            )
            manifest_tool.finalize(m)
            self.assertEqual(m["gates"]["00_hub_health_edges"]["status"], "ERROR")
            self.assertFalse(m["overall"]["fully_qualified"])

    def test_railway_runner_requires_both_gate36_variants(self):
        runner = (
            Path(__file__).resolve().parents[2]
            / "scripts/nightly-ot-bench/run_railway_hub_stress.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--required 36_mv_sql_oracle_twin", runner)
        self.assertIn("--required 36_model_ecm_qualification", runner)


if __name__ == "__main__":
    unittest.main()
