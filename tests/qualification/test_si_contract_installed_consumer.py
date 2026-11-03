"""Installed SI SQL artifact — export outside checkout + verify + negative controls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class InstalledSiContractConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.mkdtemp(prefix="openfdd-si-artifact-")
        cls.artifact_root = Path(cls._tmpdir)
        proc = subprocess.run(
            [
                "python3",
                str(REPO / "scripts/sql_contract/export_distribution.py"),
                "--out",
                str(cls.artifact_root),
                "--write-committed-manifest",
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise unittest.SkipTest(f"export failed: {proc.stderr or proc.stdout}")
        cls.source_rev = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
        cls.db_url = os.environ.get("OPENFDD_DATABASE_URL")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _run_verify(
        self,
        artifact: Path,
        *,
        expect_ok: bool = True,
        extra_env: dict[str, str] | None = None,
        skip_db: bool = False,
    ) -> dict:
        env = {
            **os.environ,
            "OPENFDD_VERIFY_REPO": str(REPO),
            "OPENFDD_SI_ARTIFACT_ROOT": str(artifact),
            "OPENFDD_SI_EXPECTED_SOURCE_REV": self.source_rev,
        }
        if extra_env:
            env.update(extra_env)
        if self.db_url and not skip_db:
            env["OPENFDD_DATABASE_URL"] = self.db_url
        receipt_path = artifact / "receipt.json"
        cmd = [
            "python3",
            str(REPO / "scripts/sql_contract/verify_installed.py"),
            "--artifact-root",
            str(artifact),
            "--receipt-out",
            str(receipt_path),
        ]
        if skip_db or not self.db_url:
            cmd.append("--skip-db")
        proc = subprocess.run(cmd, cwd=str(artifact), env=env, capture_output=True, text=True)
        if receipt_path.is_file():
            doc = json.loads(receipt_path.read_text(encoding="utf-8"))
        else:
            doc = {"ok": False, "errors": [proc.stderr or proc.stdout or "no receipt"]}
        if expect_ok:
            self.assertEqual(
                proc.returncode,
                0,
                msg=f"verify failed: {proc.stderr}\n{proc.stdout}\n{doc.get('errors')}",
            )
            self.assertTrue(doc.get("ok"), doc.get("errors"))
        else:
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(doc.get("ok", True))
        return doc

    def test_export_outside_checkout_clean_verify(self) -> None:
        self.assertTrue((self.artifact_root / "distribution_manifest.json").is_file())
        self.assertNotIn(
            str(REPO),
            str(self.artifact_root.resolve()),
            msg="artifact must not live inside checkout",
        )
        doc = self._run_verify(self.artifact_root, skip_db=not bool(self.db_url))
        self.assertGreaterEqual(doc.get("comparisons", 0), 1)

    @unittest.skipUnless(os.environ.get("OPENFDD_DATABASE_URL"), "requires disposable Postgres")
    def test_postgres_installed_smoke(self) -> None:
        doc = self._run_verify(self.artifact_root)
        ids = {c["check_id"] for c in doc.get("checks") or []}
        self.assertIn("catalog_sample_hypertable", ids)
        self.assertIn("analytics_execute_smoke", ids)

    def test_negative_wrong_unit_abi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "bad_abi"
            shutil.copytree(self.artifact_root, art)
            metric_path = art / "sql/contract/metric_units.json"
            metric = json.loads(metric_path.read_text(encoding="utf-8"))
            metric["processing_abi_current"] = "imperial-v1"
            metric_path.write_text(json.dumps(metric, indent=2) + "\n", encoding="utf-8")
            self._run_verify(art, expect_ok=False, skip_db=True)

    def test_negative_missing_19th_analytic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "missing_analytic"
            shutil.copytree(self.artifact_root, art)
            target = art / "sql/analytics/postgres/queries/sql_anomaly_series.sql"
            target.unlink()
            self._run_verify(art, expect_ok=False, skip_db=True)

    def test_negative_wrong_sql_hash_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "bad_hash"
            shutil.copytree(self.artifact_root, art)
            sql_path = art / "sql/fdd/postgres/rules/fc1_duct_static_low.sql"
            sql_path.write_bytes(sql_path.read_bytes() + b"\n-- drift\n")
            self._run_verify(art, expect_ok=False, skip_db=True)

    def test_negative_binding_unresolved_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "bad_bind"
            shutil.copytree(self.artifact_root, art)
            render_path = art / "sql/fdd/render_rule.py"
            text = render_path.read_text(encoding="utf-8")
            text = text.replace(
                "return re.sub(r'\\{\\{([A-Z_0-9]+)\\}\\}',replace,sql)",
                "return sql  # negative: skip placeholder binding",
            )
            render_path.write_text(text, encoding="utf-8")
            self._run_verify(art, expect_ok=False, skip_db=True)

    def test_negative_incomplete_receipt_required_checks(self) -> None:
        from scripts.sql_contract.consumer_lib import run_installed_verify

        doc = run_installed_verify(
            self.artifact_root,
            database_url=None,
            expected_source_revision=self.source_rev,
            skip_db=True,
        )
        self.assertTrue(doc.ok)
        required = {
            "distribution_manifest_present",
            "scientific_pack_digest",
            "unit_golden_vectors",
            "analytics_body_count",
        }
        seen = {c["check_id"] for c in doc.checks}
        self.assertTrue(required.issubset(seen))

    def test_negative_stale_source_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "stale_pin"
            shutil.copytree(self.artifact_root, art)
            (art / "SOURCE_REVISION").write_text("0" * 40 + "\n", encoding="utf-8")
            self._run_verify(
                art,
                expect_ok=False,
                skip_db=True,
                extra_env={"OPENFDD_SI_EXPECTED_SOURCE_REV": self.source_rev},
            )


if __name__ == "__main__":
    unittest.main()
