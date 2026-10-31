"""SQL407 / SQL-QUAL negative controls — verifier must reject bad harness inputs."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class Sql407VerifierRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pc = _load("pc_sql407", STRESS / "si_cutover" / "parity_chain.py")
        cls.cts = _load("cts_sql407", STRESS / "si_cutover" / "ci_timescale_sql.py")
        cls.bio = _load("bio_sql407", STRESS / "si_cutover" / "baseline_io.py")

    def _p3_row(self, **overrides):
        base = dict(
            building_id="QA_PARITY",
            rule_id="FC1",
            equipment_id="E",
            utc_day="2026-01-01",
            fault_seconds=300,
            covered_seconds=600,
            status="FAULT",
            pair_status="computed",
        )
        base.update(overrides)
        return base

    def _run_p3_probe(self, live_rows, counts):
        count = dict(building_id="QA_PARITY", table="sample", row_count=3)
        baseline = {
            "sql_fdd_daily": [self._p3_row()],
            "sample_counts": [count],
        }
        with mock.patch.object(Path, "is_dir", return_value=True), mock.patch.object(
            self.pc.bio, "verify_baseline_for_p3", return_value=({}, [])
        ), mock.patch.object(self.pc, "load_baseline_site_dir", return_value=baseline):
            return self.pc.compare_p3_post_cutover(
                baseline_dir=Path("/unused"),
                building_id="QA_PARITY",
                live_sql_daily=live_rows,
                live_sample_counts=counts or [count],
            )

    def test_sql407_01_p3_missing_all_live_sql_fails(self) -> None:
        result = self._run_p3_probe([], [dict(building_id="QA_PARITY", table="sample", row_count=3)])
        self.assertTrue(result.errors)
        self.assertIn("missing live SQL", " ".join(result.errors))

    def test_sql407_01_p3_changed_coverage_fails(self) -> None:
        result = self._run_p3_probe([self._p3_row(covered_seconds=900)], None)
        self.assertTrue(any("covered" in e for e in result.errors))

    def test_sql407_01_p3_changed_status_fails(self) -> None:
        result = self._run_p3_probe([self._p3_row(status="NOT_ASSESSED")], None)
        self.assertTrue(any("status" in e for e in result.errors))

    def test_sql407_01_p3_extra_sql_row_fails(self) -> None:
        result = self._run_p3_probe(
            [self._p3_row(), self._p3_row(equipment_id="FOREIGN")],
            None,
        )
        self.assertTrue(any("extra live" in e for e in result.errors))

    def test_sql407_01_p3_duplicate_live_key_fails(self) -> None:
        row = self._p3_row()
        result = self._run_p3_probe([row, row], None)
        self.assertTrue(any("duplicate" in e for e in result.errors))

    def test_sql407_01_p3_sample_count_only_match_still_requires_sql(self) -> None:
        result = self._run_p3_probe([], [dict(building_id="QA_PARITY", table="sample", row_count=3)])
        self.assertEqual(result.comparisons, 0)
        self.assertTrue(result.errors)

    def test_sql407_02_p1_recomputes_si_not_cache(self) -> None:
        from scripts.stress.si_cutover import ci_fixtures_lib as cfl

        site = "QA_PARITY"
        row = self._p3_row(building_id=site)
        golden = dict(building_id=site, pandas_fdd_daily=[row], pandas_si_daily=[dict(row)])
        with mock.patch.object(cfl, "load_rule_registry", return_value=[]), mock.patch.object(
            cfl, "expected_pandas_rule_ids", return_value=set()
        ), mock.patch.object(
            self.pc, "verify_golden_rule_attempted", return_value=self.pc.StageResult("coverage", 1, ())
        ), mock.patch.object(
            self.pc, "verify_current_p1_oracle_provenance", return_value=((), {})
        ), mock.patch.object(
            cfl, "recompute_si_daily_for_golden", return_value={self.pc.fdd_daily_key(row): 300.0}
        ) as recompute:
            result = self.pc.run_p1_ip_vs_si([golden], scope={"FC1"})
        self.assertEqual(recompute.call_count, 1)
        self.assertFalse(result.errors)

    def test_sql407_04_no_pandas_to_sql_self_credit(self) -> None:
        result = self.cts.p2_pair_for_si_row(
            rule_id="QA_UNSHIPPED",
            equipment_id="E",
            utc_day="2026-01-01",
            pandas_si_fault_seconds=300,
            sql_si_fault_seconds=0,
        )
        self.assertIsNone(result["sql_si_fault_seconds"])
        self.assertNotEqual(result["sql_si_status"], "computed")

    def test_sql407_03_aggregate_must_execute_with_overlay(self) -> None:
        class Cursor:
            def __init__(self):
                self.queries: list[str] = []

            def execute(self, query):
                self.queries.append(query)

            @property
            def description(self):
                return [
                    type("C", (), {"name": "equipment_id"})(),
                    type("C", (), {"name": "fault_hours"})(),
                    type("C", (), {"name": "covered_hours"})(),
                ]

            def fetchall(self):
                if self.queries[-1] == "OVERLAY":
                    return [("E", pd.Timestamp("2026-01-01T00:00:00Z"), True)]
                return [("E", 0.08333333333333333, 0.08333333333333333)]

        cur = Cursor()
        with mock.patch.object(self.cts, "render_rule_sql", return_value="ORIGINAL_AGGREGATE"), mock.patch.object(
            self.cts, "rewrite_fault_series", return_value="OVERLAY"
        ):
            rows, error = self.cts.execute_sql_rule_daily(
                cur,
                rule={"rule_id": "FC1", "sql_file": "fixture.sql"},
                building_id="QA",
                equipment_id="E",
                poll_seconds=300,
                index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min"),
            )
        self.assertIn("ORIGINAL_AGGREGATE", cur.queries)
        self.assertIn("OVERLAY", cur.queries)
        self.assertIsNone(error, error)
        self.assertTrue(rows)

    def test_sql407_03_aggregate_fault_mutation_fails(self) -> None:
        class Cursor:
            def __init__(self):
                self.queries: list[str] = []

            def execute(self, query):
                self.queries.append(query)

            @property
            def description(self):
                return [type("C", (), {"name": "equipment_id"})(), type("C", (), {"name": "fault_hours"})(), type("C", (), {"name": "covered_hours"})()]

            def fetchall(self):
                if self.queries[-1] == "OVERLAY":
                    return [("E", pd.Timestamp("2026-01-01T00:00:00Z"), True)]
                return [("E", 0.16666666666666666, 0.16666666666666666)]

        cur = Cursor()
        with mock.patch.object(self.cts, "render_rule_sql", return_value="AGG"), mock.patch.object(
            self.cts, "rewrite_fault_series", return_value="OVERLAY"
        ):
            _rows, error = self.cts.execute_sql_rule_daily(
                cur,
                rule={"rule_id": "FC1", "sql_file": "fixture.sql"},
                building_id="QA",
                equipment_id="E",
                poll_seconds=300,
                index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min"),
            )
        self.assertIsNotNone(error)
        self.assertIn("ORIGINAL_AGGREGATE", error)

    def test_sql407_03_aggregate_coverage_zero_fails(self) -> None:
        class Cursor:
            def __init__(self):
                self.queries: list[str] = []

            def execute(self, query):
                self.queries.append(query)

            @property
            def description(self):
                return [
                    type("C", (), {"name": "equipment_id"})(),
                    type("C", (), {"name": "fault_hours"})(),
                    type("C", (), {"name": "covered_hours"})(),
                ]

            def fetchall(self):
                if self.queries[-1] == "OVERLAY":
                    return [("E", pd.Timestamp("2026-01-01T00:00:00Z"), True)]
                return [("E", 300.0 / 3600.0, 0.0)]

        cur = Cursor()
        with mock.patch.object(self.cts, "render_rule_sql", return_value="AGG"), mock.patch.object(
            self.cts, "rewrite_fault_series", return_value="OVERLAY"
        ):
            _rows, error = self.cts.execute_sql_rule_daily(
                cur,
                rule={"rule_id": "FC1", "sql_file": "fixture.sql"},
                building_id="QA",
                equipment_id="E",
                poll_seconds=300,
                index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min"),
            )
        self.assertIsNotNone(error)
        self.assertIn("covered_seconds", error)

    def test_sql407_03_aggregate_coverage_nine_hundred_fails(self) -> None:
        class Cursor:
            def __init__(self):
                self.queries: list[str] = []

            def execute(self, query):
                self.queries.append(query)

            @property
            def description(self):
                return [
                    type("C", (), {"name": "equipment_id"})(),
                    type("C", (), {"name": "fault_hours"})(),
                    type("C", (), {"name": "covered_hours"})(),
                ]

            def fetchall(self):
                if self.queries[-1] == "OVERLAY":
                    return [("E", pd.Timestamp("2026-01-01T00:00:00Z"), True)]
                return [("E", 300.0 / 3600.0, 900.0 / 3600.0)]

        cur = Cursor()
        with mock.patch.object(self.cts, "render_rule_sql", return_value="AGG"), mock.patch.object(
            self.cts, "rewrite_fault_series", return_value="OVERLAY"
        ):
            _rows, error = self.cts.execute_sql_rule_daily(
                cur,
                rule={"rule_id": "FC1", "sql_file": "fixture.sql"},
                building_id="QA",
                equipment_id="E",
                poll_seconds=300,
                index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min"),
            )
        self.assertIsNotNone(error)
        self.assertIn("covered_seconds", error)

    def test_sql407_03_no_overlay_keeps_unknown_coverage(self) -> None:
        class Cursor:
            @property
            def description(self):
                return [
                    type("C", (), {"name": "equipment_id"})(),
                    type("C", (), {"name": "fault_hours"})(),
                ]

            def execute(self, _query):
                return None

            def fetchall(self):
                return [("E", 0.0)]

        cur = Cursor()
        with mock.patch.object(self.cts, "render_rule_sql", return_value="AGG"), mock.patch.object(
            self.cts, "rewrite_fault_series", return_value=None
        ):
            rows, error = self.cts.execute_sql_rule_daily(
                cur,
                rule={"rule_id": "FC1", "sql_file": "fixture.sql"},
                building_id="QA",
                equipment_id="E",
                poll_seconds=300,
                index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min"),
            )
        self.assertIsNone(error)
        self.assertEqual(rows[0].get("covered_seconds"), None)
        self.assertEqual(rows[0].get("pair_status"), "aggregate_fault_total_only")

    def test_sql407_02_p1_foreign_open_fdd_outside_repo_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            foreign = Path(tmp) / "foreign_open_fdd"
            pkg = foreign / "open_fdd"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text('__version__ = "5.0.0"\n', encoding="utf-8")
            (foreign / "pyproject.toml").write_text(
                '[project]\nversion = "5.0.0"\n', encoding="utf-8"
            )
            sys.path.insert(0, str(foreign))
            try:
                for name in list(sys.modules):
                    if name == "open_fdd" or name.startswith("open_fdd."):
                        del sys.modules[name]
                errors, evidence = self.pc.verify_current_p1_oracle_provenance()
                self.assertTrue(errors)
                self.assertIn("outside candidate repo", " ".join(errors))
                self.assertIn("resolved_open_fdd_file", evidence)
            finally:
                sys.path[:] = [p for p in sys.path if p != str(foreign)]
                for name in list(sys.modules):
                    if name == "open_fdd" or name.startswith("open_fdd."):
                        del sys.modules[name]

    def test_sql407_05_vacuous_rule_attempted_fails(self) -> None:
        golden = {
            "building_id": "B",
            "pandas_rules_attempted": ["FC1"],
            "pandas_fdd_daily": [],
            "sql_fdd_daily": [],
        }
        result = self.pc.verify_golden_rule_attempted(golden, {"FC1", "FC2"})
        self.assertTrue(result.errors)

    def test_sql407_06_p3_live_cli_blocked_without_fixture(self) -> None:
        import argparse

        gate = _load("gate_sql407", STRESS / "si_parity_gate.py")
        args = argparse.Namespace(
            p3_fixture=False,
            baseline_dir=Path("/tmp"),
            sites_config=Path("/tmp/sites.json"),
        )
        Path("/tmp/sites.json").write_text("[]", encoding="utf-8")
        code = gate.run_p3_cli(args)
        self.assertEqual(code, gate.EXIT_BLOCKED)


if __name__ == "__main__":
    unittest.main()
