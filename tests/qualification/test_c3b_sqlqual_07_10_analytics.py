"""C3b SQL-QUAL-07..10 + 19 analytics bodies (#1284, issue #1284 part)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class C3bMatrixOfflineTests(unittest.TestCase):
    def test_offline_matrix_has_nonzero_checks(self) -> None:
        from scripts.qualification.c3b_sqlqual.runner import run_matrix

        out = REPO / "reports" / "c3b_sqlqual_matrix_offline_selftest.json"
        matrix = run_matrix(db_url=None, matrix_path=out)
        self.assertTrue(out.is_file())
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], "openfdd-c3-sqlqual-matrix-v1")
        self.assertFalse(doc["db_hydrated"])
        ids = {c["id"] for c in doc["components"]}
        self.assertIn("SQL-QUAL-07", ids)
        self.assertIn("analytics-19-fresh-pg-oracle", ids)
        for comp in doc["components"]:
            self.assertGreater(comp["checks"], 0, comp["id"])
        failing = [c["id"] for c in doc["components"] if c["status"] == "FAIL"]
        self.assertFalse(failing, failing)
        self.assertIsNotNone(matrix)

    def test_runner_cli_prints_db_log_line_without_db(self) -> None:
        no_db_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENFDD_DATABASE_URL", "OPENFDD_TEST_DATABASE_URL")
        }
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(REPO / "scripts" / "qualification" / "c3b_sqlqual" / "runner.py"),
                "--matrix-out",
                "/tmp/c3b_matrix_cli.json",
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env=no_db_env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("C3b DB-backed checks:", proc.stdout)
        self.assertIn("hydrated=False", proc.stdout)


@unittest.skipUnless(
    os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
    "OPENFDD_DATABASE_URL required for C3b postgres matrix",
)
class C3bMatrixPostgresTests(unittest.TestCase):
    def test_db_matrix_passes_with_nonzero_db_comparisons(self) -> None:
        from scripts.qualification.c3b_sqlqual.runner import run_matrix

        out = REPO / "reports" / "c3b_sqlqual_matrix_ci.json"
        matrix = run_matrix(db_url=os.environ["OPENFDD_DATABASE_URL"], matrix_path=out)
        self.assertTrue(matrix.db_hydrated)
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(REPO / "scripts" / "qualification" / "c3b_sqlqual" / "runner.py"),
                "--require-db",
                "--matrix-out",
                str(out),
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            env={**os.environ, "OPENFDD_DATABASE_URL": os.environ["OPENFDD_DATABASE_URL"]},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("C3b DB-backed checks:", proc.stdout)
        self.assertIn("hydrated=True", proc.stdout)
        self.assertRegex(proc.stdout, r"db_comparisons=[1-9]")
        doc = json.loads(out.read_text(encoding="utf-8"))
        pg_cell = next(
            c
            for comp in doc["components"]
            for c in comp["cells"]
            if c["check_id"] == "19_pg_fresh_sql_vs_oracle_all_bodies"
        )
        self.assertEqual(pg_cell["status"], "PASS")
        self.assertGreater(pg_cell["comparisons"], 0)
        for comp in doc["components"]:
            if comp["id"].startswith("SQL-QUAL"):
                self.assertNotEqual(comp["status"], "FAIL", comp)


if __name__ == "__main__":
    unittest.main()
