"""Offline config/transport/report validation — no hub credentials."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.config import (  # noqa: E402
    ConfigError,
    assert_base_url_allowed,
    load_config,
    validate_origin,
)
from openfdd_security.evidence import (  # noqa: E402
    CheckResult,
    SecurityReport,
    validate_report_for_qualification,
    write_report,
)
from openfdd_security.inventory import (  # noqa: E402
    find_uninventoried_routes,
    load_inventory,
)
from openfdd_security.runner import run_probe  # noqa: E402


EXAMPLE = ROOT / "scripts/security/config/example_security_fixtures.json"


class ConfigTransportTest(unittest.TestCase):
    def test_example_config_loads(self):
        cfg = load_config(EXAMPLE)
        self.assertIn("http://127.0.0.1:18080", cfg.origin_allowlist)

    def test_inline_password_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            data = json.loads(EXAMPLE.read_text())
            data["identities"]["admin"]["password"] = "secret"
            p.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_unknown_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            data = json.loads(EXAMPLE.read_text())
            data["extra_evil"] = True
            p.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_origin_rejects_credentials_and_query(self):
        with self.assertRaises(ConfigError):
            validate_origin("http://user:pass@127.0.0.1:8080")
        with self.assertRaises(ConfigError):
            validate_origin("http://127.0.0.1:8080?x=1")

    def test_base_url_must_be_allowlisted(self):
        cfg = load_config(EXAMPLE)
        with self.assertRaises(ConfigError):
            assert_base_url_allowed("http://evil.example", cfg, "isolated_full")
        assert_base_url_allowed("http://127.0.0.1:18080", cfg, "isolated_full")

    def test_live_readonly_rejects_http(self):
        cfg = load_config(EXAMPLE)
        with self.assertRaises(ConfigError):
            assert_base_url_allowed("http://127.0.0.1:18080", cfg, "live_readonly")

    def test_dry_run_default_no_execute(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            report, _ = run_probe(
                config_path=EXAMPLE,
                base_url="http://127.0.0.1:18080",
                profile="isolated_full",
                suites=None,
                execute=False,
                dry_run=True,
                max_requests=None,
                timeout=None,
                deadline=None,
                rate=None,
                output_dir=out,
                allow_fixture_writes=False,
            )
            self.assertTrue(report.dry_run)
            self.assertFalse(report.executed)
            self.assertFalse(report.fully_qualified)
            self.assertTrue((out / "security_report.json").is_file())

    def test_unknown_suite_fails(self):
        with self.assertRaises(ConfigError):
            run_probe(
                config_path=EXAMPLE,
                base_url="http://127.0.0.1:18080",
                profile="isolated_full",
                suites=["not_a_suite"],
                execute=False,
                dry_run=True,
                max_requests=None,
                timeout=None,
                deadline=None,
                rate=None,
                output_dir=None,
                allow_fixture_writes=False,
            )

    def test_subset_not_full_profile(self):
        report, _ = run_probe(
            config_path=EXAMPLE,
            base_url="http://127.0.0.1:18080",
            profile="isolated_full",
            suites=["X"],
            execute=False,
            dry_run=True,
            max_requests=None,
            timeout=None,
            deadline=None,
            rate=None,
            output_dir=None,
            allow_fixture_writes=False,
        )
        self.assertFalse(report.full_profile)

    def test_report_hash_validation(self):
        report = SecurityReport(
            profile="isolated_full",
            executed=True,
            dry_run=False,
            full_profile=True,
        )
        report.add(
            CheckResult(
                check_id="t1", suite="X", title="t", status="PASS"
            )
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            meta = write_report(report, out)
            ok, reason = validate_report_for_qualification(
                out / "security_report.json",
                expected_profile="isolated_full",
                expected_sha256=meta["sha256"],
            )
            self.assertTrue(ok, reason)
            # Tamper
            p = out / "security_report.json"
            data = json.loads(p.read_text())
            data["notes"] = ["tampered"]
            p.write_text(json.dumps(data))
            ok2, reason2 = validate_report_for_qualification(
                p,
                expected_profile="isolated_full",
                expected_sha256=meta["sha256"],
            )
            self.assertFalse(ok2)
            self.assertIn("hash", reason2)

    def test_inventory_covers_current_routes_rs(self):
        routes_rs = ROOT / "services/central/src/routes.rs"
        missing = find_uninventoried_routes(routes_rs)
        self.assertEqual(
            missing,
            [],
            f"uninventoried routes (update inventory): {missing}",
        )
        inv = load_inventory()
        self.assertGreater(inv["route_count"], 50)


if __name__ == "__main__":
    unittest.main()
