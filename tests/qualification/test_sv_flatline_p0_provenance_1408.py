"""#1408: Document SV-FLATLINE P0 IP golden mismatches before changing SQL or goldens."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"
PROVENANCE = REPO / "tests" / "fixtures" / "si_cutover" / "sv_flatline_p0_provenance.json"
GOLDEN = REPO / "tests" / "fixtures" / "si_cutover" / "ip_goldens" / "SYNTH_VAV_CASE_VAV_1.json"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))


class SvFlatlineP0ProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from si_cutover import parity_chain as pc

        cls.pc = pc
        cls.doc = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_provenance_schema_lists_seven_cells(self) -> None:
        self.assertEqual(self.doc.get("schema"), "openfdd-sv-flatline-p0-provenance-v1")
        cells = self.doc.get("p0_mismatch_cells") or []
        self.assertEqual(len(cells), 7)

    def test_p0_stage_reports_exactly_seven_sv_flatline_mismatches(self) -> None:
        p0 = self.pc.compare_p0_all_goldens([self.golden])
        sv_lines = [line for line in p0.errors if "SV-FLATLINE" in line]
        self.assertEqual(len(sv_lines), 7)

    def test_frozen_ip_golden_rows_match_provenance_table(self) -> None:
        pandas_by_day = {
            str(r["utc_day"]): float(r["fault_seconds"])
            for r in self.golden.get("pandas_fdd_daily") or []
            if r.get("rule_id") == "SV-FLATLINE" and r.get("utc_day")
        }
        sql_by_day = {
            str(r["utc_day"]): float(r["fault_seconds"])
            for r in self.golden.get("sql_fdd_daily") or []
            if r.get("rule_id") == "SV-FLATLINE" and r.get("utc_day")
        }
        for row in self.doc["p0_mismatch_cells"]:
            day = row["utc_day"]
            self.assertAlmostEqual(pandas_by_day[day], row["frozen_pandas_ip_fault_seconds"], places=3)
            self.assertAlmostEqual(sql_by_day[day], row["frozen_sql_ip_fault_seconds"], places=3)

    def test_si_p2_pairs_agree_on_same_golden(self) -> None:
        """SI runner C/D on this fixture agrees; P0 IP split does not."""
        for row in self.golden.get("p2_si_pairs") or []:
            if row.get("rule_id") != "SV-FLATLINE":
                continue
            if not str(row.get("utc_day", "")).startswith("2026-01-0"):
                continue
            pan = float(row.get("pandas_si_fault_seconds") or 0)
            sql = float(row.get("sql_si_fault_seconds") or 0)
            self.assertEqual(row.get("sql_si_status"), "computed")
            self.assertAlmostEqual(pan, sql, places=3)

    def test_p0_mismatch_is_not_mode_delay_classification(self) -> None:
        from si_cutover import ci_fixtures_lib as cfl
        from scripts.stress.si_cutover.product_sql_params import p0_value_mismatch_reason

        rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
        rule = rules["SV-FLATLINE"]
        params = cfl.rule_params_from_registry(rule)
        self.assertIsNone(p0_value_mismatch_reason("SV-FLATLINE", params))

    def test_current_pandas_oracle_differs_from_stale_pandas_ip_capture(self) -> None:
        from si_cutover import ci_fixtures_lib as cfl, ci_timescale_sql as cts

        spec = next(s for s in cfl.iter_dataset_specs() if s.equipment_id == "VAV_CASE_VAV_1")
        frame = cfl.prepare_ip_frame(
            spec.source["frame"],
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            equipment_type=spec.equipment_type,
        )
        rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
        rule = rules["SV-FLATLINE"]
        params = cfl.rule_params_from_registry(rule)
        poll = cts.infer_poll_seconds(frame.index)
        rows = cfl.run_rule_daily_rows(
            rule,
            frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params,
            poll_seconds=poll,
        )
        current = {
            str(r["utc_day"]): float(r.get("fault_seconds") or 0)
            for r in rows
            if str(r.get("utc_day", "")).startswith("2026-01-0")
        }
        frozen = {
            row["utc_day"]: row["frozen_pandas_ip_fault_seconds"]
            for row in self.doc["p0_mismatch_cells"]
            if row["frozen_pandas_ip_fault_seconds"] > 0
        }
        self.assertTrue(current)
        for day, stale in frozen.items():
            self.assertIn(day, current)
            self.assertNotAlmostEqual(current[day], stale, places=3)


if __name__ == "__main__":
    unittest.main()
