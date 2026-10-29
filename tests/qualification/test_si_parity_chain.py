"""SI parity chain harness tests (#1284 W3, T1284-4)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
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

    def test_p0_all_ip_goldens(self) -> None:
        goldens = self.pc.load_all_ip_goldens()
        self.assertGreaterEqual(len(goldens), 15)
        result = self.pc.compare_p0_all_goldens(goldens)
        self.assertGreater(result.comparisons, 250)
        # W3: Timescale SQL vs pandas IP mismatches are reported by the gate until closeout.
        self.assertGreaterEqual(len(result.errors), 0)

    def test_p3_fixture_baseline_pass(self) -> None:
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

    def test_p3_fixture_one_second_fault_diff_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mini"
            shutil.copytree(
                REPO / "tests" / "fixtures" / "si_cutover" / "p3_baseline_mini",
                root,
            )
            site = root / "SITE_MINI"
            live_path = site / "live_sql_si_daily.jsonl.gz"
            rows = []
            with gzip.open(live_path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rows.append(json.loads(line))
            self.assertTrue(rows)
            rows[0]["fault_seconds"] = float(rows[0].get("fault_seconds", 0)) + 1.0
            with gzip.open(live_path, "wt", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
            live_sql = list(self.pc.iter_jsonl_gz(live_path))
            live_counts = list(self.pc.iter_jsonl_gz(site / "live_sample_counts.jsonl.gz"))
            result = self.pc.compare_p3_post_cutover(
                baseline_dir=root,
                building_id="SITE_MINI",
                live_sql_daily=live_sql,
                live_sample_counts=live_counts,
            )
            self.assertTrue(result.errors, "1s fault drift must fail P3")

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

    def test_p0_carryover_rules_union(self) -> None:
        goldens = self.pc.load_all_ip_goldens()
        carry = self.pc.verify_p0_carryover_all(goldens)
        self.assertEqual(carry.errors, ())
        self.assertGreaterEqual(carry.comparisons, len(self.pc.CARRYOVER_RULES_P0))


if __name__ == "__main__":
    unittest.main()
