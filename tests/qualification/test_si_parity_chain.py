"""SI parity chain harness tests (#1284 W3, T1284-4)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"


def _load_parity_chain():
    spec = importlib.util.spec_from_file_location(
        "parity_chain_testmod",
        STRESS / "si_cutover" / "parity_chain.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SiParityChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pc = _load_parity_chain()

    def test_p0_golden_selftest(self) -> None:
        golden = self.pc.load_ip_golden(self.pc.IP_GOLDENS_DIR / "SYNTH_SELFTEST.json")
        result = self.pc.compare_p0_ip_golden(golden)
        self.assertGreater(result.comparisons, 0)
        self.assertEqual(result.errors, ())

    def test_p3_fixture_baseline(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--stage",
                "P3",
                "--p3-fixture",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, "P3 fixture gate must PASS")

    def test_t1284_4_mutation_self_test(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(STRESS / "si_parity_gate.py"),
                "--mutation-self-test",
            ],
            cwd=str(REPO),
            check=False,
        )
        self.assertEqual(proc.returncode, 0)

    def test_p0_carryover_rules_in_golden(self) -> None:
        golden = self.pc.load_ip_golden(self.pc.IP_GOLDENS_DIR / "SYNTH_SELFTEST.json")
        carry = self.pc.verify_p0_carryover_coverage(golden)
        self.assertEqual(carry.errors, ())
        self.assertGreaterEqual(carry.comparisons, len(self.pc.CARRYOVER_RULES_P0))


if __name__ == "__main__":
    unittest.main()
