"""Offline tests for C3c libpq migration client helpers."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class C3cLibpqTests(unittest.TestCase):
    def test_blocked_receipt_shape(self) -> None:
        from scripts.qualification.c3c_libpq import blocked_migration_client_receipt

        receipt = blocked_migration_client_receipt(missing=["psql", "pg_dump"])
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["missing_clients"], ["psql", "pg_dump"])

    def test_libpq_env_never_puts_password_in_argv(self) -> None:
        from scripts.qualification.c3c_libpq import libpq_subprocess_env, run_psql

        url = "postgresql://openfdd:secret@127.0.0.1:5432/openfdd"
        env = libpq_subprocess_env(database_url=url, base={})
        self.assertEqual(env["PGPASSWORD"], "secret")
        self.assertEqual(env["PGHOST"], "127.0.0.1")
        with mock.patch("scripts.qualification.c3c_libpq.pg_client_paths", return_value={"psql": "/bin/psql", "pg_dump": "/bin/pg_dump"}):
            with mock.patch("scripts.qualification.c3c_libpq.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=0)
                run_psql(database_url=url, dbname="postgres", args=["-c", "SELECT 1"])
        cmd = run.call_args[0][0]
        joined = " ".join(cmd)
        self.assertNotIn("secret", joined)
        self.assertNotIn("postgresql://", joined)
        self.assertEqual(run.call_args[1]["env"]["PGPASSWORD"], "secret")


class C3cCheckpointTests(unittest.TestCase):
    def test_matrix_atomic_write_roundtrip(self) -> None:
        from scripts.qualification.c3c_sqlqual_matrix import CheckCell, new_matrix
        import json
        import tempfile

        matrix = new_matrix(identities={"probe": True})
        matrix.add(
            CheckCell(
                id="SQL-QUAL-11-growth-dense",
                phase="C3",
                status="PASS",
                summary="ok",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matrix.json"
            matrix.write_json_atomic(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "c3-sqlqual-matrix-v1")
            self.assertEqual(payload["summary_by_qual_id"]["SQL-QUAL-11"]["PASS"], 1)


if __name__ == "__main__":
    unittest.main()
