"""#1437 / #1458 / #1459: FC mode-delay consolidation — pandas matches product SQL."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"
LEDGER = REPO / "tests" / "fixtures" / "si_cutover" / "expected_ip_change_ledger.json"

from tests.qualification.fc1_mode_delay_timeline_reference import (  # noqa: E402
    build_issue_1458_reproducer,
    build_mode_delay_grid_cases,
    build_synthetic_fc1_frame,
    compute_fc1_timeline,
    fc1_mode_stable_mutant_pre1437,
    grid_params,
)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _hand_mode_stable(fan_on: list[bool], delay_min: float, poll_s: float) -> list[bool]:
    from open_fdd.rules.mode_delay import fan_restart_stable, mode_delay_rows

    rows = mode_delay_rows(delay_min, poll_s)
    fan = pd.Series(fan_on)
    return fan_restart_stable(fan, rows).tolist()


def _series_bool_equal(case: unittest.TestCase, a: pd.Series, b: list[bool], msg: str = "") -> None:
    got = a.reindex(a.index[: len(b)]).iloc[: len(b)].fillna(False).astype(bool).tolist()
    case.assertEqual(got, b, msg=msg)


def _day_fault_seconds_run_rule(
    frame: pd.DataFrame,
    params: dict[str, float],
    poll: float,
    *,
    mode_stable_fn: Callable[..., pd.Series] | None = None,
    utc_day: str,
) -> float:
    from open_fdd.rules import run_rule
    from scripts.stress.si_cutover.capture_ip_baseline import daily_fault_and_covered_seconds

    import open_fdd.rules.cookbook_catalog as cb

    orig = cb._fc1_mode_stable
    if mode_stable_fn is not None:
        cb._fc1_mode_stable = mode_stable_fn
    try:
        res = run_rule(
            "FC1",
            frame,
            params=params,
            poll_seconds=poll,
            require_operational_gates=True,
        )
        self_conf = res.confirmed_fault
        if self_conf is None:
            raise AssertionError(res.notes or res.status)
        fault_by_day, _ = daily_fault_and_covered_seconds(
            self_conf, frame.index, poll_seconds=poll
        )
        return float(fault_by_day.get(utc_day, 0.0))
    finally:
        cb._fc1_mode_stable = orig


class Fc1ModeDelayTimelineGridPandasTest(unittest.TestCase):
    """Hand reference vs run_rule for the full mode-delay grid (pandas)."""

    CONFIRM_SECONDS = 300.0
    N_SAMPLES = 36

    def _frame_for_poll(self, poll: float) -> pd.DataFrame:
        frame = build_synthetic_fc1_frame(poll_seconds=poll, n_samples=self.N_SAMPLES)
        frame.attrs["equipment_type"] = "ahu"
        frame.attrs["equipment_id"] = "GRID_AHU"
        return frame

    def test_hand_grid_masks_and_seconds_match_run_rule(self) -> None:
        from open_fdd.rules import run_rule

        for case in build_mode_delay_grid_cases():
            poll = float(case["poll_seconds"])
            params = grid_params(case)
            frame = self._frame_for_poll(poll)
            ref = compute_fc1_timeline(
                index=frame.index,
                fan_status=frame["fan-status"].tolist(),
                duct_static=frame["duct-static-pressure"].tolist(),
                duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
                params=params,
                poll_seconds=poll,
                confirm_seconds=self.CONFIRM_SECONDS,
                require_operational_gate=False,
            )
            res = run_rule(
                "FC1",
                frame,
                params=params,
                poll_seconds=poll,
                require_operational_gates=False,
            )
            self.assertIsNotNone(res.raw_fault, msg=str(case))
            self.assertIsNotNone(res.confirmed_fault, msg=str(case))
            active = pd.Series(True, index=frame.index)
            _series_bool_equal(self, active, ref.eligible, msg=str(case))
            _series_bool_equal(
                self,
                res.raw_fault.reindex(frame.index).fillna(False),
                ref.raw,
                msg=str(case),
            )
            _series_bool_equal(
                self,
                res.confirmed_fault.reindex(frame.index).fillna(False),
                ref.confirmed,
                msg=str(case),
            )
            fault_total = sum(ref.fault_seconds_by_day.values())
            covered_total = sum(ref.covered_seconds_by_day.values())
            from scripts.stress.si_cutover.capture_ip_baseline import (
                daily_fault_and_covered_seconds,
            )

            f_days, c_days = daily_fault_and_covered_seconds(
                res.confirmed_fault, frame.index, poll_seconds=poll
            )
            self.assertAlmostEqual(sum(f_days.values()), fault_total, places=6, msg=str(case))
            self.assertAlmostEqual(sum(c_days.values()), covered_total, places=6, msg=str(case))


class Fc1ModeDelayTimelineGridPostgresTest(unittest.TestCase):
    """Rendered postgres FC1 vs run_rule across the mode-delay grid (SYNTH frame, IP params)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not cls.db_url:
            raise unittest.SkipTest("OPENFDD_DATABASE_URL required for postgres grid parity")
        cls.cfl = _load("cfl_grid", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        cls.cts = _load("cts_grid", STRESS / "si_cutover" / "ci_timescale_sql.py")
        parity = cls.cts._load_parity_module()
        cls.conn = parity.connect_with_retry(cls.db_url)
        cls.cts.apply_fdd_postgres_helpers(cls.conn)
        rules = {str(r["rule_id"]): r for r in cls.cfl.load_rule_registry()}
        cls.fc1_rule = rules["FC1"]
        from scripts.ci import unit_contract_lib as uc

        cls.params_ip, _ = cls.cfl.resolve_rule_params_ip_si(
            cls.fc1_rule, uc.load_json(uc.METRIC_UNITS)
        )
        cls.synth_spec = next(
            s for s in cls.cfl.iter_dataset_specs() if s.equipment_id == "AHU_CASE_FC1"
        )
        cls.synth_frame = cls.cfl.prepare_ip_frame(
            cls.synth_spec.source["frame"],
            building_id=cls.synth_spec.building_id,
            equipment_id=cls.synth_spec.equipment_id,
            equipment_type=cls.synth_spec.equipment_type,
        )
        cls.base_poll = cls.cts.infer_poll_seconds(cls.synth_frame.index)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "conn") and cls.conn is not None:
            cls.conn.close()

    def _params_for_case(self, case: dict[str, Any]) -> dict[str, float]:
        params = dict(self.params_ip)
        params["startup_delay_min"] = float(case["startup_delay_min"])
        mode = case.get("mode_delay_min")
        if mode is None:
            params.pop("mode_delay_min", None)
        else:
            params["mode_delay_min"] = float(mode)
        return params

    def test_hand_grid_daily_seconds_match_rendered_postgres(self) -> None:
        from open_fdd.rules import run_rule
        from scripts.stress.si_cutover.capture_ip_baseline import daily_fault_and_covered_seconds

        poll = float(self.base_poll)
        for case in build_mode_delay_grid_cases():
            if float(case.get("poll_seconds") or 0) != poll:
                continue
            if case.get("mode_delay_min") == 0.0 and float(case.get("startup_delay_min") or 0) > 0:
                continue
            params = self._params_for_case(case)
            res = run_rule(
                "FC1",
                self.synth_frame,
                params=params,
                poll_seconds=poll,
                require_operational_gates=True,
            )
            self.assertIsNotNone(res.confirmed_fault, msg=str(case))
            fault_by_day, _ = daily_fault_and_covered_seconds(
                res.confirmed_fault, self.synth_frame.index, poll_seconds=poll
            )
            pandas_fault = sum(fault_by_day.values())
            sql_rows, errs = self.cts.run_sql_ip_for_dataset(
                self.conn,
                spec=self.synth_spec,
                frame=self.synth_frame,
                equipment_id=self.synth_spec.equipment_id,
                rules=[self.fc1_rule],
                poll_seconds=poll,
                params_by_rule={"FC1": params},
            )
            self.assertEqual(errs, [], msg=f"{case}: {'; '.join(errs)}")
            sql_fault = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
            self.assertAlmostEqual(sql_fault, pandas_fault, places=6, msg=str(case))


class ModeDelayUtcMidnightHoldoffTest(unittest.TestCase):
    """Mode-delay holdoff with eligible-hold clip at UTC midnight."""

    def test_per_day_fault_seconds_match_reference_pandas_and_postgres(self) -> None:
        from open_fdd.rules import run_rule

        frame, params, poll = build_issue_1458_reproducer()
        utc_day = "2026-01-05"
        ref = compute_fc1_timeline(
            index=frame.index,
            fan_status=frame["fan-status"].tolist(),
            duct_static=frame["duct-static-pressure"].tolist(),
            duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
            params=params,
            poll_seconds=poll,
            confirm_seconds=300.0,
            require_operational_gate=True,
        )
        res = run_rule(
            "FC1",
            frame,
            params=params,
            poll_seconds=poll,
            require_operational_gates=True,
        )
        from scripts.stress.si_cutover.capture_ip_baseline import daily_fault_and_covered_seconds

        f_days, _ = daily_fault_and_covered_seconds(
            res.confirmed_fault, frame.index, poll_seconds=poll
        )
        ref_day = ref.fault_seconds_by_day.get(utc_day)
        pan_day = f_days.get(utc_day)
        self.assertIsNotNone(ref_day)
        self.assertAlmostEqual(pan_day, ref_day, places=6)
        db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not db_url:
            return
        cts = _load("cts_mid", STRESS / "si_cutover" / "ci_timescale_sql.py")
        cfl = _load("cfl_mid", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        from scripts.stress.si_cutover.ci_fixtures_lib import DatasetSpec

        parity = cts._load_parity_module()
        conn = parity.connect_with_retry(db_url)
        cts.apply_fdd_postgres_helpers(conn)
        try:
            rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
            spec = DatasetSpec(
                building_id="MODE_DELAY_MIDNIGHT",
                equipment_id=str(frame.attrs.get("equipment_id") or "AHU_CASE_FC1"),
                equipment_type="ahu",
                source={"frame": frame},
            )
            sql_rows, errs = cts.run_sql_ip_for_dataset(
                conn,
                spec=spec,
                frame=frame,
                equipment_id=spec.equipment_id,
                rules=[rules["FC1"]],
                poll_seconds=poll,
                params_by_rule={"FC1": params},
            )
            self.assertEqual(errs, [], msg="; ".join(errs))
            sql_by_day = {
                r["utc_day"]: float(r["fault_seconds"])
                for r in sql_rows
                if r.get("utc_day")
            }
            self.assertAlmostEqual(sql_by_day.get(utc_day), ref_day, places=6)
        finally:
            conn.close()


class ModeDelayMutantControlTest(unittest.TestCase):
    """Mutation control: frozen pre-#1437 _fc1_mode_stable must fail the reference grid."""

    def test_mutant_pre1437_differs_from_hand_reference(self) -> None:
        case = {"mode_delay_min": None, "startup_delay_min": 0.0, "poll_seconds": 300.0}
        params = grid_params(case)
        frame = build_synthetic_fc1_frame(poll_seconds=300.0, n_samples=36)
        frame.attrs["equipment_type"] = "ahu"
        ref = compute_fc1_timeline(
            index=frame.index,
            fan_status=frame["fan-status"].tolist(),
            duct_static=frame["duct-static-pressure"].tolist(),
            duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
            params=params,
            poll_seconds=300.0,
            confirm_seconds=300.0,
            require_operational_gate=False,
        )
        import open_fdd.rules.cookbook_catalog as cb
        from open_fdd.rules.base import confirm_fault
        from open_fdd.rules.cookbook_catalog import fc1

        orig = cb._fc1_mode_stable
        cb._fc1_mode_stable = fc1_mode_stable_mutant_pre1437
        try:
            raw = fc1(frame, params, 300.0)
            conf = confirm_fault(raw, poll_seconds=300.0, confirm_seconds=300.0)
            mutant_raw = raw.reindex(frame.index).fillna(False).astype(bool).tolist()
            mutant_conf = conf.reindex(frame.index).fillna(False).astype(bool).tolist()
        finally:
            cb._fc1_mode_stable = orig
        self.assertNotEqual(mutant_raw, ref.raw)
        self.assertNotEqual(sum(mutant_conf), sum(ref.confirmed))


class ModeDelayTimelineHandComputedTest(unittest.TestCase):
    """Independent reference timelines for mode-stable holdoff."""

    def test_default_10min_at_300s_poll(self) -> None:
        # Fan restarts at index 2; 10 min @ 300 s → 2-row window → stable from index 3.
        fan = [False, False, True, True, True, True]
        got = _hand_mode_stable(fan, 10.0, 300.0)
        self.assertEqual(got, [False, False, False, True, True, True])

    def test_explicit_zero_mode_startup_wins(self) -> None:
        fan = [False, True, True, True]
        # mode=0, startup=15 → effective 15 min @ 60 s → 15 rows; only last row stable after long fan-on
        from open_fdd.rules.mode_delay import effective_mode_delay_min, resolve_mode_delay_params

        eff = effective_mode_delay_min(resolve_mode_delay_params({"mode_delay_min": 0, "startup_delay_min": 15}))
        self.assertEqual(eff, 15.0)
        got = _hand_mode_stable(fan, eff, 60.0)
        self.assertFalse(got[1])
        self.assertFalse(got[2])

    def test_startup_gt_mode_negative_control(self) -> None:
        from open_fdd.rules.mode_delay import effective_mode_delay_min, resolve_mode_delay_params

        self.assertEqual(
            effective_mode_delay_min(
                resolve_mode_delay_params({"mode_delay_min": 5, "startup_delay_min": 15})
            ),
            15.0,
        )

    @staticmethod
    def _param_grid() -> list[tuple[float, float, float]]:
        delays = (0.0, 5.0, 10.0, 15.0)
        polls = (60.0, 300.0, 900.0)
        out: list[tuple[float, float, float]] = []
        for delay in delays:
            for poll in polls:
                out.append((delay, 0.0, poll))
        out.append((0.0, 15.0, 300.0))
        out.append((5.0, 15.0, 300.0))
        return out

    def test_fc1_mode_stable_matches_hand_reference(self) -> None:
        from open_fdd.rules import cookbook_catalog as cb
        from open_fdd.rules.mode_delay import effective_mode_delay_min, resolve_mode_delay_params

        idx = pd.date_range("2026-03-01", periods=8, freq="5min", tz="UTC")
        fan_status = [0, 0, 1, 1, 1, 1, 0, 1]
        d = pd.DataFrame(
            {
                "duct-static-pressure": [0.5] * 8,
                "duct-static-pressure-sp": [2.0] * 8,
                "fan-status": fan_status,
            },
            index=idx,
        )
        d.attrs["storage_abi"] = "metric-c-v2"
        for mode, startup, poll in self._param_grid():
            params = {
                "eps_vfd_spd": 0.13,
                "eps_dsp": 29.8608,
                "fan_on_min": 0.01,
                "startup_delay_min": startup,
            }
            if mode != float("nan"):
                if mode > 0 or startup > 0:
                    params["mode_delay_min"] = mode
            resolved = resolve_mode_delay_params(params)
            eff = effective_mode_delay_min(resolved)
            hand = _hand_mode_stable([bool(x) for x in fan_status], eff, poll)
            got = cb._fc1_mode_stable(d, params, poll).tolist()
            self.assertEqual(got, hand, msg=f"mode={mode} startup={startup} poll={poll}")

    def test_utc_midnight_clips_daily_seconds(self) -> None:
        from open_fdd.rules.base import confirm_fault
        from scripts.stress.si_cutover.capture_ip_baseline import daily_fault_and_covered_seconds

        start = datetime(2026, 1, 1, 23, 50, tzinfo=timezone.utc)
        idx = pd.date_range(start, periods=4, freq="5min", tz="UTC")
        raw = pd.Series([True, True, True, True], index=idx)
        confirmed = confirm_fault(raw, poll_seconds=300.0, confirm_seconds=0.0)
        fault_days, covered_days = daily_fault_and_covered_seconds(
            confirmed, idx, poll_seconds=300.0
        )
        self.assertAlmostEqual(fault_days.get("2026-01-01", 0.0), 600.0)
        self.assertAlmostEqual(fault_days.get("2026-01-02", 0.0), 300.0)
        self.assertEqual(covered_days.get("2026-01-01", 0.0), 600.0)
        self.assertEqual(covered_days.get("2026-01-02", 0.0), 300.0)


class ModeDelayFc1DefaultOmittedRegressionTest(unittest.TestCase):
    """Regression: omitted mode_delay_min must not silently behave as 0 (failed at 73a1c3ab)."""

    def test_omitted_mode_delay_uses_product_default_not_zero(self) -> None:
        from open_fdd.rules import cookbook_catalog as cb
        from open_fdd.rules.mode_delay import PRODUCT_MODE_DELAY_MIN_DEFAULT, resolve_mode_delay_params

        idx = pd.date_range("2026-04-01T08:00:00", periods=4, freq="5min", tz="UTC")
        d = pd.DataFrame(
            {
                "duct-static-pressure": [0.2, 0.2, 0.2, 0.2],
                "duct-static-pressure-sp": [1.0, 1.0, 1.0, 1.0],
                "fan-status": [0, 1, 1, 1],
            },
            index=idx,
        )
        d.attrs["storage_abi"] = "metric-c-v2"
        params = {"startup_delay_min": 0, "eps_vfd_spd": 0.13, "eps_dsp": 29.8608, "fan_on_min": 0.01}
        self.assertNotIn("mode_delay_min", params)
        resolved = resolve_mode_delay_params(params)
        self.assertEqual(resolved["mode_delay_min"], PRODUCT_MODE_DELAY_MIN_DEFAULT)
        stable = cb._fc1_mode_stable(d, params, 300.0)
        # 10 min @ 300 s → 2-row window; fan on from index 1 → stable from index 2
        self.assertEqual(stable.tolist(), [False, False, True, True])

    def test_explicit_zero_mode_with_zero_startup_has_no_holdoff(self) -> None:
        from open_fdd.rules import cookbook_catalog as cb

        idx = pd.date_range("2026-04-01", periods=3, freq="5min", tz="UTC")
        d = pd.DataFrame(
            {
                "duct-static-pressure": [0.2, 0.2, 0.2],
                "duct-static-pressure-sp": [1.0, 1.0, 1.0],
                "fan-status": [0, 1, 1],
            },
            index=idx,
        )
        d.attrs["storage_abi"] = "metric-c-v2"
        params = {
            "mode_delay_min": 0,
            "startup_delay_min": 0,
            "eps_vfd_spd": 0.13,
            "eps_dsp": 29.8608,
            "fan_on_min": 0.01,
        }
        stable = cb._fc1_mode_stable(d, params, 300.0)
        # rows=1 with zero delay: only samples with fan on are stable
        self.assertEqual(stable.tolist(), [False, True, True])


class ModeDelayPostgresParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not cls.db_url:
            raise unittest.SkipTest("OPENFDD_DATABASE_URL required for postgres SQL parity")
        cls.cfl = _load("cfl_mode_delay", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        cls.cts = _load("cts_mode_delay", STRESS / "si_cutover" / "ci_timescale_sql.py")
        parity = cls.cts._load_parity_module()
        cls.conn = parity.connect_with_retry(cls.db_url)
        cls.cts.apply_fdd_postgres_helpers(cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "conn") and cls.conn is not None:
            cls.conn.close()

    def _synth_fc1_spec(self):
        for spec in self.cfl.iter_dataset_specs():
            if spec.equipment_id == "AHU_CASE_FC1":
                return spec
        self.fail("AHU_CASE_FC1 dataset missing")

    def _fc1_params_ip(self, fc1_rule):
        from scripts.ci import unit_contract_lib as uc

        params_ip, _params_si = self.cfl.resolve_rule_params_ip_si(
            fc1_rule, uc.load_json(uc.METRIC_UNITS)
        )
        return params_ip

    def test_fc1_pandas_daily_matches_rendered_postgres_default_params(self) -> None:
        spec = self._synth_fc1_spec()
        rules = {str(r["rule_id"]): r for r in self.cfl.load_rule_registry()}
        fc1_rule = rules["FC1"]
        frame = self.cfl.prepare_ip_frame(
            spec.source["frame"],
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            equipment_type=spec.equipment_type,
        )
        poll = self.cts.infer_poll_seconds(frame.index)
        params = self._fc1_params_ip(fc1_rule)
        rows = self.cfl.run_rule_daily_rows(
            fc1_rule,
            frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params,
            poll_seconds=poll,
        )
        pandas_by_day = {r["utc_day"]: float(r["fault_seconds"]) for r in rows if r.get("utc_day")}

        sql_rows, errs = self.cts.run_sql_ip_for_dataset(
            self.conn,
            spec=spec,
            frame=frame,
            equipment_id=spec.equipment_id,
            rules=[fc1_rule],
            poll_seconds=poll,
            params_by_rule={"FC1": params},
        )
        self.assertEqual(errs, [], msg="; ".join(errs))
        sql_by_day = {r["utc_day"]: float(r["fault_seconds"]) for r in sql_rows if r.get("utc_day")}
        for day, pandas_fs in pandas_by_day.items():
            self.assertIn(day, sql_by_day, msg=f"missing SQL day {day}")
            self.assertEqual(
                round(pandas_fs, 6),
                round(sql_by_day[day], 6),
                msg=f"FC1 fault_seconds mismatch on {day}",
            )

    def test_fc1_omitted_mode_delay_matches_sql(self) -> None:
        spec = self._synth_fc1_spec()
        rules = {str(r["rule_id"]): r for r in self.cfl.load_rule_registry()}
        fc1_rule = rules["FC1"]
        frame = self.cfl.prepare_ip_frame(
            spec.source["frame"],
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            equipment_type=spec.equipment_type,
        )
        poll = self.cts.infer_poll_seconds(frame.index)
        params = dict(self._fc1_params_ip(fc1_rule))
        params.pop("mode_delay_min", None)
        rows = self.cfl.run_rule_daily_rows(
            fc1_rule,
            frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params,
            poll_seconds=poll,
        )
        pandas_total = sum(float(r.get("fault_seconds") or 0) for r in rows)
        sql_rows, errs = self.cts.run_sql_ip_for_dataset(
            self.conn,
            spec=spec,
            frame=frame,
            equipment_id=spec.equipment_id,
            rules=[fc1_rule],
            poll_seconds=poll,
            params_by_rule={"FC1": params},
        )
        self.assertEqual(errs, [], msg="; ".join(errs))
        sql_total = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
        self.assertEqual(round(pandas_total, 6), round(sql_total, 6))


class ExpectedIpChangeLedgerTest(unittest.TestCase):
    def test_ledger_schema_and_fc1_entry(self) -> None:
        body = json.loads(LEDGER.read_text(encoding="utf-8"))
        self.assertEqual(body.get("schema"), "openfdd-expected-ip-change-ledger-v1")
        entries = body.get("entries") or []
        self.assertTrue(entries)
        fc1 = next(e for e in entries if e.get("rule_id") == "FC1")
        self.assertIn("#1437", " ".join(fc1.get("issues") or []))
        self.assertNotEqual(
            fc1.get("frozen_pandas_ip_fault_seconds"),
            fc1.get("corrected_pandas_ip_fault_seconds"),
        )

    def test_issue_1458_reproducer_matches_ledger_numeric_story(self) -> None:
        """Documented #1458 reproducer: frozen IP 28500 s vs corrected pandas/SQL 28800 s."""
        body = json.loads(LEDGER.read_text(encoding="utf-8"))
        fc1 = next(e for e in body.get("entries") or [] if e.get("rule_id") == "FC1")
        frozen = float(fc1["frozen_pandas_ip_fault_seconds"])
        corrected = float(fc1["corrected_pandas_ip_fault_seconds"])
        self.assertEqual(frozen, 28500.0)
        self.assertEqual(corrected, 28800.0)

        frame, params, poll = build_issue_1458_reproducer()
        utc_day = "2026-01-05"
        # Frozen W0c pandas IP (pre-#1437 mode_stable with harness omit override).
        frozen_like = _day_fault_seconds_run_rule(
            frame, params, poll, mode_stable_fn=fc1_mode_stable_mutant_pre1437, utc_day=utc_day
        )
        self.assertAlmostEqual(frozen_like, frozen, places=6)
        # Corrected oracle + product SQL path (explicit catalog zero holdoff on this cell).
        corrected_params = dict(params)
        corrected_params["mode_delay_min"] = 0.0
        corrected_pandas = _day_fault_seconds_run_rule(
            frame, corrected_params, poll, mode_stable_fn=None, utc_day=utc_day
        )
        self.assertAlmostEqual(corrected_pandas, corrected, places=6)

        db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not db_url:
            return
        cts = _load("cts_1458", STRESS / "si_cutover" / "ci_timescale_sql.py")
        cfl = _load("cfl_1458", STRESS / "si_cutover" / "ci_fixtures_lib.py")
        from scripts.stress.si_cutover.ci_fixtures_lib import DatasetSpec

        parity = cts._load_parity_module()
        conn = parity.connect_with_retry(db_url)
        cts.apply_fdd_postgres_helpers(conn)
        try:
            rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
            spec = DatasetSpec(
                building_id="ISSUE_1458",
                equipment_id=str(frame.attrs.get("equipment_id") or "AHU_CASE_FC1"),
                equipment_type="ahu",
                source={"frame": frame},
            )
            sql_rows, errs = cts.run_sql_ip_for_dataset(
                conn,
                spec=spec,
                frame=frame,
                equipment_id=spec.equipment_id,
                rules=[rules["FC1"]],
                poll_seconds=poll,
                params_by_rule={"FC1": corrected_params},
            )
            self.assertEqual(errs, [], msg="; ".join(errs))
            sql_day = next(
                float(r["fault_seconds"])
                for r in sql_rows
                if r.get("utc_day") == utc_day
            )
            self.assertAlmostEqual(sql_day, corrected, places=6)
            self.assertAlmostEqual(corrected_pandas, sql_day, places=6)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
