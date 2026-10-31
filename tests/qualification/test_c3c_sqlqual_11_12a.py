"""C3c SQL-QUAL-11 + 12A harness smoke tests."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class C3cMatrixTests(unittest.TestCase):
    def test_matrix_schema_and_pending_rows(self):
        from scripts.qualification.c3c_sqlqual_matrix import CheckCell, new_matrix

        matrix = new_matrix(identities={"probe": True})
        matrix.add(
            CheckCell(
                id="SQL-QUAL-12B",
                phase="C5",
                status="PENDING",
                summary="prereq",
            )
        )
        matrix.add(
            CheckCell(
                id="SQL-QUAL-11-growth-dense",
                phase="C3",
                status="PASS",
                summary="ok",
            )
        )
        self.assertEqual(matrix.counts_by_qual()["SQL-QUAL-11"]["PASS"], 1)
        self.assertEqual(matrix.counts_by_qual()["SQL-QUAL-12B"]["PENDING"], 1)
        self.assertEqual(matrix.exit_code(), 0)

    def test_ip_golden_baseline_readonly(self):
        from scripts.qualification.c3c_sqlqual_12a import _ip_golden_baseline_identity

        baseline = _ip_golden_baseline_identity()
        self.assertEqual(baseline["schema"], "si-cutover-ip-golden-v1")
        self.assertGreater(baseline["rule_row_count"], 0)


@unittest.skipUnless(
    os.environ.get("OPENFDD_TEST_DATABASE_URL", "").strip()
    or os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
    "OPENFDD_TEST_DATABASE_URL required for disposable Postgres C3c bench",
)
class C3cSqlQualDbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = (
            os.environ.get("OPENFDD_TEST_DATABASE_URL", "").strip()
            or os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        )

    def test_run_c3c_runner_quick(self):
        import subprocess

        out = ROOT / "reports" / "c3c" / "ci-smoke-matrix.json"
        proc = subprocess.run(
            [
                "python3",
                str(ROOT / "scripts/qualification/run_c3c_sqlqual_11_12a.py"),
                "--database-url",
                self.url,
                "--ci-quick",
                "--multi-equipment",
                "2",
                "--json-out",
                str(out),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=600,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("C3C SQL-QUAL DB bench completed", proc.stdout)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "c3-sqlqual-matrix-v1")
        qual = payload["summary_by_qual_id"]
        self.assertGreaterEqual(qual.get("SQL-QUAL-11", {}).get("PASS", 0), 4)
        self.assertEqual(qual.get("SQL-QUAL-12B", {}).get("PENDING", 0), 1)
        self.assertEqual(qual.get("SQL-QUAL-12C", {}).get("PENDING", 0), 1)


if __name__ == "__main__":
    unittest.main()
