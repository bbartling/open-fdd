"""Astra A01/A02 — selected OT Compose recipes (static, no live OT)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "security" / "validate_ot_compose_selection.py"


class OtComposeSelectionTest(unittest.TestCase):
    def test_selftest(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--selftest"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
