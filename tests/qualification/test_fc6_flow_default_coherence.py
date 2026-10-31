"""FC6 min_cfm_design default coherence: contract law + OA% threshold boundary (#1284)."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))
sys.path.insert(0, str(REPO / "scripts" / "ci"))

from tests.qualification.fc6_flow_boundary_reference import (  # noqa: E402
    DESIGN_L_S,
    build_fc6_boundary_cases,
    build_fc6_boundary_frame,
    fc6_si_params,
    rewrite_raw_fault_probe,
)
from tests.qualification.fc6_flow_boundary_reference import LPS_PER_CFM  # noqa: E402
from unit_contract_lib import REJECTED_LPS_PER_CFM  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class Fc6FlowDefaultContractTest(unittest.TestCase):
    def test_master_wrong_default_would_fail_boundary_law(self) -> None:
        wrong_default = 5000.0 * REJECTED_LPS_PER_CFM
        self.assertNotAlmostEqual(wrong_default, DESIGN_L_S, delta=1e-6)
        self.assertAlmostEqual(wrong_default, 2359.73725, places=6)
        self.assertAlmostEqual(DESIGN_L_S, 2359.735, places=6)


class Fc6BoundaryPandasMaskTest(unittest.TestCase):
    def test_raw_masks_below_equal_above_default_threshold(self) -> None:
        from open_fdd.rules import run_rule

        params = fc6_si_params(confirm_seconds=0.0)
        for case in build_fc6_boundary_cases():
            frame = build_fc6_boundary_frame(case)
            res = run_rule(
                "FC6",
                frame,
                params=params,
                poll_seconds=300.0,
                require_operational_gates=False,
            )
            self.assertIsNotNone(res.raw_fault, msg=case.case_id)
            got = bool(res.raw_fault.iloc[0])
            self.assertEqual(
                got,
                case.expect_raw_fault,
                msg=f"{case.case_id} pct_oa_target={case.pct_oa_target}",
            )


class Fc6BoundaryPostgresMaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not cls.db_url:
            raise unittest.SkipTest("OPENFDD_DATABASE_URL required for FC6 postgres boundary")
        cls.cfl = _load("cfl_fc6", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        cls.cts = _load("cts_fc6", STRESS / "si_cutover" / "ci_timescale_sql.py")
        parity = cls.cts._load_parity_module()
        cls.conn = parity.connect_with_retry(cls.db_url)
        cls.cts.apply_fdd_postgres_helpers(cls.conn)
        rules = {str(r["rule_id"]): r for r in cls.cfl.load_rule_registry()}
        cls.fc6_rule = rules["FC6"]
        cls.site_id = "FC6_FLOW_BOUNDARY_SITE"
        cls.equipment_id = "FC6_BOUNDARY"

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "conn") and cls.conn is not None:
            cls.conn.close()

    def _sql_raw_mask(self, frame: pd.DataFrame, params: dict[str, float]) -> list[bool]:
        from scripts.stress.si_cutover.product_sql_params import catalog_overrides_from_registry

        self.conn.rollback()
        cur = self.conn.cursor()
        try:
            self.cts.purge_site(cur, self.site_id)
            self.conn.commit()
            cur = self.conn.cursor()
            self.cts.seed_frame(
                cur,
                self.cts._load_parity_module(),
                site_id=self.site_id,
                equipment_id=self.equipment_id,
                equip_type="ahu",
                frame=frame,
                storage="si",
            )
            self.conn.commit()
            cur = self.conn.cursor()
            cols = self.cts.history_columns_for_rules(frame, [self.fc6_rule])
            self.cts.fill_history(cur, self.site_id, cols)
            overrides = catalog_overrides_from_registry(self.fc6_rule, params)
            sql = self.cts.render_rule_sql(
                self.fc6_rule,
                300.0,
                overrides=overrides,
                storage="si",
            )
            probe = rewrite_raw_fault_probe(sql, self.equipment_id)
            cur.execute(probe)
            rows = cur.fetchall()
        finally:
            cur.close()
        return [bool(row[2]) for row in rows]

    def test_postgres_raw_masks_match_pandas_at_default_design_flow(self) -> None:
        from open_fdd.rules import run_rule

        params = fc6_si_params(confirm_seconds=0.0)
        for case in build_fc6_boundary_cases():
            frame = build_fc6_boundary_frame(case)
            pandas_res = run_rule(
                "FC6",
                frame,
                params=params,
                poll_seconds=300.0,
                require_operational_gates=False,
            )
            sql_mask = self._sql_raw_mask(frame, params)
            self.assertEqual(len(sql_mask), len(frame.index), msg=case.case_id)
            pandas_mask = pandas_res.raw_fault.reindex(frame.index).fillna(False).astype(bool).tolist()
            self.assertEqual(sql_mask, pandas_mask, msg=case.case_id)
            self.assertEqual(
                sql_mask[0],
                case.expect_raw_fault,
                msg=f"{case.case_id} design_l_s={DESIGN_L_S} lps={LPS_PER_CFM}",
            )


if __name__ == "__main__":
    unittest.main()
