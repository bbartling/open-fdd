"""Structural SI parity gate: P0 report-only; scoped P1/P2 always block (#1284 W3)."""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"


def _load_gate():
    spec = importlib.util.spec_from_file_location("si_parity_gate_testmod", STRESS / "si_parity_gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_parity_chain():
    spec = importlib.util.spec_from_file_location(
        "parity_chain_gate_testmod", STRESS / "si_cutover" / "parity_chain.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SiParityGateBlockingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = _load_gate()
        cls.pc = _load_parity_chain()

    def test_p0_errors_never_in_blocking_failures(self) -> None:
        p0 = self.pc.StageResult(
            "P0",
            5,
            ("P0 value_mismatch ('B', 'FC1', 'E', '2026-01-01'): a b",),
            (),
            (
                {
                    "kind": "value_mismatch",
                    "mismatch_reason": "mode_delay_default_vs_startup_delay",
                },
            ),
        )
        failures = self.gate._blocking_errors([p0], blocking=True, scope={"FC1"})
        self.assertEqual(failures, [])

    def _p2_goldens(self, statuses: list[str]) -> list[dict]:
        rows = [
            {
                "rule_id": "FC1",
                "equipment_id": "E",
                "utc_day": f"2026-01-0{i + 1}",
                "sql_si_status": status,
                "sql_si_fault_seconds": None if status == "pending_W4" else 60.0,
                "pandas_si_fault_seconds": 60.0,
                "sql_si_pending_reason": "FC1.eps_dsp ('inwc') non-SI"
                if status == "pending_W4"
                else None,
            }
            for i, status in enumerate(statuses)
        ]
        return [{"p2_si_pairs": rows}]

    def test_p2_pending_cells_are_not_comparisons(self) -> None:
        p2 = self.pc.run_p2_all_goldens(
            self._p2_goldens(["computed", "pending_W4", "pending_W4"]), scope={"FC1"}
        )
        self.assertEqual(p2.comparisons, 1)
        self.assertEqual(p2.pending, 2)
        self.assertTrue(any("eps_dsp" in note for note in p2.mismatch_table))

    def test_scoped_blocking_fails_on_pending_cells(self) -> None:
        p2 = self.pc.run_p2_all_goldens(
            self._p2_goldens(["computed", "pending_W4"]), scope={"FC1"}
        )
        failures = self.gate._blocking_errors([p2], blocking=True, scope={"FC1"})
        self.assertTrue(any("pending_W4" in f for f in failures), failures)

    def test_scoped_all_pending_has_zero_real_comparisons(self) -> None:
        p2 = self.pc.run_p2_all_goldens(self._p2_goldens(["pending_W4"]), scope={"FC1"})
        self.assertEqual(p2.comparisons, 0)
        self.assertTrue(self.gate._blocking_errors([p2], blocking=True, scope={"FC1"}))

    def test_report_only_full_matrix_reports_pending_without_blocking(self) -> None:
        p2 = self.pc.run_p2_all_goldens(self._p2_goldens(["computed", "pending_W4"]))
        self.assertEqual(p2.pending, 1)
        self.assertEqual(self.gate._blocking_errors([p2], blocking=False, scope=None), [])

    def test_p1_mismatch_with_mismatch_reason_still_blocks(self) -> None:
        p1 = self.pc.StageResult(
            "P1",
            1,
            ("P1 ('B', 'FC1', 'E', '2026-01-01'): ip=1 si=2",),
            (),
            ({"rule_id": "FC1", "mismatch_reason": "mode_delay_default_vs_startup_delay"},),
        )
        failures = self.gate._blocking_errors([p1], blocking=True, scope={"FC1"})
        self.assertEqual(len(failures), 1)

    def test_scoped_blocking_w4d_plant_passes(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--fixtures-only",
                "--blocking",
                "--family",
                "W4d_si_plant",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "W4d plant scope: P1/P2 for shipped SI SQL should PASS",
        )

    def test_scoped_blocking_w4e_sensor_util_passes(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--fixtures-only",
                "--blocking",
                "--family",
                "W4e_si_sensor_util",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "W4e sensor/weather/schedule/utility scope: P1/P2 for shipped SI SQL should PASS",
        )

    def test_scoped_blocking_passes_w4b_ahu_econ(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--fixtures-only",
                "--blocking",
                "--family",
                "W4b_ahu_econ",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "W4b AHU econ family: scoped P1/P2 gate should PASS",
        )

    def test_scoped_p1_mutation_still_fails_blocking(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--fixtures-only",
                "--blocking",
                "--rules",
                "FC1",
                "--inject-t1284-4-mutation",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(proc.returncode, 1, "T1284-4 P1 mismatch must fail blocking scope")

    def test_strict_p2_missing_sql_row_fails(self) -> None:
        sys.path.insert(0, str(STRESS))
        from si_cutover.si_parity_families import W4C_SI_ZONE_FAMILY, resolve_rule_scope

        scope = resolve_rule_scope(rules=None, family=W4C_SI_ZONE_FAMILY)
        goldens = copy.deepcopy(self.pc.load_all_ip_goldens())
        mock_conn = MagicMock()
        with patch.dict("os.environ", {"OPENFDD_DATABASE_URL": "postgres://local/test"}):
            with patch(
                "scripts.stress.si_cutover.ci_timescale_sql._load_parity_module"
            ) as load_mod:
                load_mod.return_value.connect_with_retry.return_value = mock_conn
                with patch(
                    "scripts.stress.si_cutover.ci_timescale_sql.run_sql_si_for_dataset",
                    return_value=([], []),
                ):
                    result = self.pc.run_p2_all_goldens(goldens, scope=scope, strict=True)
        self.assertTrue(
            result.errors,
            "strict W4c P2 must fail when Timescale returns no sql_si rows",
        )
        joined = " ".join(result.errors)
        self.assertTrue(
            "missing sql_si row" in joined or "pending_W4 after hydration" in joined,
            f"expected hydration failure, got: {result.errors[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
