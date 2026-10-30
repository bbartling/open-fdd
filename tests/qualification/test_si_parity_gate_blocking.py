"""Structural SI parity gate: P0 report-only; scoped P1/P2 always block (#1284 W3)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

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

    def test_scoped_blocking_passes_despite_p0_fc1_mismatches(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--fixtures-only",
                "--blocking",
                "--family",
                "W4b_fc1_duct_static",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "W4b FC1 scope: P0 mismatches are report-only; P1 clean should PASS",
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


if __name__ == "__main__":
    unittest.main()
