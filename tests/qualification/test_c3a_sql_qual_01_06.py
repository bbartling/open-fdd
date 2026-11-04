"""SQL-QUAL-01..06 C3a harness — disposable Postgres + negative controls."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STRESS = REPO / "scripts" / "stress"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SqlQualC3aHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = _load("c3a_harness", REPO / "scripts" / "qualification/c3a/sql_qual_harness.py")
        cls.rid = _load("c3a_rid", REPO / "scripts" / "qualification/c3a/runner_identities.py")
        cls.pc = _load("pc_c3a", STRESS / "si_cutover" / "parity_chain.py")
        cls.cts = _load("cts_c3a", STRESS / "si_cutover" / "ci_timescale_sql.py")
        cls.bio = _load("bio_c3a", STRESS / "si_cutover" / "baseline_io.py")

    def test_matrix_offline_qual_01_and_05_pass(self) -> None:
        no_db = {k: v for k, v in os.environ.items() if k != "OPENFDD_DATABASE_URL"}
        with mock.patch.dict(os.environ, no_db, clear=True):
            doc = self.harness.build_matrix(REPO)
        self.assertEqual(doc["schema"], self.harness.MATRIX_SCHEMA)
        self.assertFalse(doc["db_hydrated"])
        for check_id in (
            "SQL-QUAL-01",
            "SQL-QUAL-04",
            "SQL-QUAL-05",
        ):
            self.assertEqual(doc["summary"][check_id]["status"], "PASS", doc["summary"][check_id])
        self.assertEqual(doc["summary"]["SQL-QUAL-06"]["status"], "INCOMPLETE")

    def test_runner_substitution_wrong_version_fails(self) -> None:
        idents = self.rid.record_runner_identities(REPO)
        idents["runners"]["C"]["open_fdd_version"] = self.rid.RUNNER_A_VERSION
        errors = self.rid.verify_runner_substitution_guard(idents)
        self.assertTrue(any("4.4.9" in e for e in errors))

    def test_negative_p3_missing_sql(self) -> None:
        site = "QA_PARITY"
        row = dict(
            building_id=site,
            rule_id="FC1",
            equipment_id="E",
            utc_day="2026-01-01",
            fault_seconds=300,
            covered_seconds=600,
            status="FAULT",
            pair_status="computed",
        )
        with mock.patch.object(Path, "is_dir", return_value=True), mock.patch.object(
            self.pc.bio, "verify_baseline_for_p3", return_value=({}, [])
        ), mock.patch.object(self.pc, "load_baseline_site_dir", return_value={"sql_fdd_daily": [row]}):
            result = self.pc.compare_p3_post_cutover(
                baseline_dir=Path("/unused"),
                building_id=site,
                live_sql_daily=[],
                live_sample_counts=[{"building_id": site, "table": "sample", "row_count": 3}],
            )
        self.assertTrue(result.errors)

    def test_negative_p2_no_self_credit_unshipped(self) -> None:
        result = self.cts.p2_pair_for_si_row(
            rule_id="QA_UNSHIPPED",
            equipment_id="E",
            utc_day="2026-01-01",
            pandas_si_fault_seconds=300,
            sql_si_fault_seconds=0,
        )
        self.assertIsNone(result["sql_si_fault_seconds"])

    def test_expected_change_ledger_present(self) -> None:
        ledger = json.loads(
            (REPO / "scripts/qualification/c3a/expected_change_ledger.json").read_text(encoding="utf-8")
        )
        issues = {item["issue"] for item in ledger.get("issues") or []}
        self.assertIn(1469, issues)
        self.assertIn(1470, issues)
        self.assertIn(1477, issues)
        self.assertIn(1408, issues)
        self.assertIn(1284, issues)
        for item in ledger.get("issues") or []:
            self.assertFalse(
                item.get("waive_cd_agreement_on_nondefault"),
                f"issue {item.get('issue')} must not waive current C/D disagreement",
            )

    def test_daily_key_controls_pm01(self) -> None:
        rtm = _load("rtm_keys", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")

        def row(day: str = "2026-10-31", fault: float = 300, cov: float | None = 600) -> dict:
            return {
                "building_id": "SYN",
                "rule_id": "FC1",
                "equipment_id": "EQ",
                "utc_day": day,
                "pair_status": "computed",
                "fault_seconds": fault,
                "covered_seconds": cov,
            }

        one_side = rtm._compare_daily([row()], [])
        self.assertGreater(one_side.shape_mismatch, 0)
        self.assertEqual(one_side.compared_cells, 0)

        extra = rtm._compare_daily([row(), row("2026-11-01")], [row()])
        self.assertGreater(extra.shape_mismatch, 0)

        dup = rtm._compare_daily([row(fault=600), row()], [row()])
        self.assertGreater(dup.duplicate_keys, 0)

        cov = rtm._compare_daily([row(cov=None)], [row()])
        self.assertGreater(cov.numeric_mismatch, 0)

    def test_partial_required_cases_not_pass_pm02(self) -> None:
        rtm = _load("rtm_partial", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        rtm._frozen_ab_blocked = lambda: ("BLOCKED", "frozen")
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        frame = pd.DataFrame({"fan-status": [1.0, 1.0]}, index=idx)
        rtm._dataset_specs = lambda: [
            type("S", (), {"building_id": "COOKBOOK_FC1", "equipment_type": "ahu"})()
        ]
        rtm._si_context = lambda *a: (frame, frame, "EQ", 300.0)

        def exec_case(*_a, **k):
            if k.get("tuner_value") == 0:
                return rtm.CaseCompareResult(
                    daily=rtm.DailyCompareResult(compared_cells=1),
                    both_empty=False,
                )
            return rtm.CaseCompareResult(
                daily=rtm.DailyCompareResult(),
                errors=["injected PG execution error"],
            )

        rtm._execute_cd_case = exec_case
        out = rtm.run_matrix(object())
        self.assertNotEqual(out["status"], "PASS")
        self.assertTrue(out["errors"])
        fc1_rows = [
            r for r in out["evidence"]["per_rule_tuner_sample"] if r["rule_id"] == "FC1"
        ]
        self.assertTrue(fc1_rows)
        self.assertNotEqual(fc1_rows[0]["status"], "PASS")

    def test_nondefault_cd_disagreement_not_waived_pm03(self) -> None:
        rtm = _load("rtm_waiver", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        rtm._frozen_ab_blocked = lambda: ("BLOCKED", "frozen")
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        frame = pd.DataFrame({"fan-status": [1.0, 1.0]}, index=idx)
        rtm._dataset_specs = lambda: [
            type("S", (), {"building_id": "COOKBOOK_FC1", "equipment_type": "ahu"})()
        ]
        rtm._si_context = lambda *a: (frame, frame, "EQ", 300.0)

        def exec_case(*_a, **k):
            val = k.get("tuner_value")
            if val == 0:
                return rtm.CaseCompareResult(
                    daily=rtm.DailyCompareResult(compared_cells=1),
                    both_empty=False,
                )
            return rtm.CaseCompareResult(
                daily=rtm.DailyCompareResult(compared_cells=1, numeric_mismatch=1),
                both_empty=False,
            )

        rtm._execute_cd_case = exec_case
        out = rtm.run_matrix(object())
        self.assertEqual(out["status"], "FAIL")
        self.assertNotIn("ledger_waived", out["evidence"]["per_rule_tuner_totals"])

    def test_confirm_min_maps_to_registry_confirm_seconds(self) -> None:
        rtm = _load("rtm_confirm", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        cfl = _load("cfl_confirm", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        rule = next(r for r in cfl.load_rule_registry() if str(r.get("rule_id")) == "FC1")
        reg, err = rtm._registry_param_for_catalog_tuner(rule, "confirm_min")
        self.assertIsNone(err)
        self.assertEqual(reg, "confirm_seconds")
        _bad, bad_err = rtm._registry_param_for_catalog_tuner(rule, "not_a_real_tuner")
        self.assertIsNotNone(bad_err)
        uc = _load("uc_confirm", REPO / "scripts/ci/unit_contract_lib.py")
        metric = uc.load_json(uc.METRIC_UNITS)
        params_five = rtm._params_si_for_case(
            rule, metric, tuner_name="confirm_min", tuner_value=5.0
        )
        self.assertEqual(params_five.get("confirm_seconds"), 300.0)
        params_zero = rtm._params_si_for_case(
            rule, metric, tuner_name="confirm_min", tuner_value=0.0
        )
        self.assertEqual(params_zero.get("confirm_seconds"), 0.0)

    def test_sensor_fault_flag_mismatch_fails_full_compare(self) -> None:
        from scripts.qualification.c3b_sqlqual import qual_19_analytics_fresh as q19

        stem = "sensor_faults_staleness"
        base = [
            "E1",
            "sat",
            "E1.sat",
            12,
            "2026-01-05T12:00:00+00:00",
            20.0,
            22.0,
            0.5,
            "true",
        ]
        sql_row = list(base)
        sql_row[-1] = "false"
        oracle_match = list(base)
        oracle_match[-1] = "false"
        n_ok, err_ok = q19.compare_stem_rows(stem, [sql_row], [oracle_match], dataset_id="QA")
        self.assertGreater(n_ok, 0)
        self.assertFalse(err_ok, err_ok)
        oracle_mismatch = list(base)
        oracle_mismatch[-1] = "true"
        n_bad, err_bad = q19.compare_stem_rows(stem, [sql_row], [oracle_mismatch], dataset_id="QA")
        self.assertGreater(n_bad, 0)
        self.assertTrue(err_bad)

    def test_sv_rate_matrix_blocked_not_executed(self) -> None:
        rtm = _load("rtm_sv_rate", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        rows = rtm.build_matrix_rows()
        rate_rows = [r for r in rows if r.rule_id == "SV-RATE"]
        self.assertTrue(rate_rows)
        offline = rtm.run_matrix(None)
        blocked = [r for r in offline["evidence"]["per_rule_tuner"] if r["rule_id"] == "SV-RATE"]
        self.assertTrue(blocked)
        self.assertTrue(all(r["status"] == "BLOCKED" for r in blocked))
        self.assertTrue(all(r.get("executed", r.get("attempted", 0)) == 0 for r in blocked))

    def test_tuner_value_cases_include_default_boundary_nondefault(self) -> None:
        rtm = _load("rtm_cases", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        catalog = json.loads((REPO / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))
        entry = next(e for e in catalog["rules"] if e["rule_id"] == "SV-RANGE")
        pspec = entry["parameters"]["range_scale_temperature"]
        labels = {label for label, _ in rtm.tuner_value_cases(pspec)}
        self.assertIn("default", labels)
        self.assertIn("boundary", labels)
        self.assertIn("nondefault", labels)


@unittest.skipUnless(
    os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
    "OPENFDD_DATABASE_URL required for SQL-QUAL DB-backed checks",
)
class SqlQualC3aPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = _load("c3a_harness_pg", REPO / "scripts/qualification/c3a/sql_qual_harness.py")

    def test_db_matrix_02_03_pass(self) -> None:
        doc = self.harness.build_matrix(REPO)
        self.assertTrue(doc["db_hydrated"])
        for check_id in ("SQL-QUAL-02", "SQL-QUAL-03"):
            row = doc["summary"][check_id]
            self.assertEqual(row["status"], "PASS", row)
            self.assertGreater(row["comparisons"], 0)
        q6 = doc["summary"]["SQL-QUAL-06"]
        self.assertIn(q6["status"], ("FAIL", "INCOMPLETE", "PASS"), q6)
        if q6["status"] == "PASS":
            self.assertGreater(q6["comparisons"], 0)

    def test_matrix_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "matrix.json"
            doc = self.harness.write_matrix(out, REPO)
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema"], doc["schema"])
            self.assertIn("SQL-QUAL-06", loaded["summary"])


if __name__ == "__main__":
    unittest.main()
