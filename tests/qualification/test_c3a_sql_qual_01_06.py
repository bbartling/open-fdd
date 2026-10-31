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
        self.assertIn(1408, issues)

    def test_sv_range_scale_ledger_waiver(self) -> None:
        rtm = _load("rtm_waiver", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        self.assertFalse(
            rtm.sv_range_scale_nondefault_ledger_waiver("SV-RANGE", "range_scale_temperature", "default")
        )
        self.assertTrue(
            rtm.sv_range_scale_nondefault_ledger_waiver("SV-RANGE", "range_scale_temperature", "min")
        )
        self.assertFalse(rtm.sv_range_scale_nondefault_ledger_waiver("FC1", "mode_delay_min", "min"))

    def test_confirm_min_maps_to_registry_confirm_seconds(self) -> None:
        rtm = _load("rtm_confirm", REPO / "scripts/qualification/c3a/rule_tuner_matrix.py")
        cfl = _load("cfl_confirm", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        rule = next(r for r in cfl.load_rule_registry() if str(r.get("rule_id")) == "FC1")
        reg, err = rtm._registry_param_for_catalog_tuner(rule, "confirm_min")
        self.assertIsNone(err)
        self.assertEqual(reg, "confirm_seconds")
        _bad, bad_err = rtm._registry_param_for_catalog_tuner(rule, "not_a_real_tuner")
        self.assertIsNotNone(bad_err)

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
        self.assertEqual(q6["status"], "PASS", q6)
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
