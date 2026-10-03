"""UA-04 / Astra C-ZAP: isolated ZAP wrapper hygiene + single evaluator."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "qualification" / "run_isolated_zap_af.sh"


class IsolatedZapJwtHygieneTest(unittest.TestCase):
    def test_no_admin_jwt_persistence(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn(
            'echo "$TOKEN" >"$ART/admin.jwt"',
            text,
            "must not write admin.jwt to artifact dir",
        )
        self.assertIn("ephemeral env only", text)
        self.assertIn('rm -f "$ART/admin.jwt"', text)

    def test_artifact_dir_not_world_writable(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("chmod -R a+rwX", text)
        self.assertIn('chmod 700 "$ART"', text)
        # wrk may be 777 for ZAP uid mapping; ART must stay 700 (no JWT).
        self.assertIn('chmod 777 "$WRK"', text)

    def test_delegates_to_single_evaluator(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_af_disposable.py", text)
        self.assertIn("OPENFDD_ZAP_AF_EXECUTE=1", text)
        self.assertIn("OPENFDD_ZAP_REQUIRE_DIGEST=1", text)
        # A06/A07: no soft-pass fallback crawl / PASS_WITH_WARNINGS.
        self.assertNotIn("zap-baseline.py", text)
        self.assertNotIn("PASS_WITH_WARNINGS", text)
        self.assertNotIn("FALLBACK", text)
        self.assertNotIn("af_fallback", text)

    def test_disposable_web_plus_central(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("openfdd-web", text)
        self.assertIn("network-alias web", text)
        self.assertIn("http://web:8080", text)
        self.assertIn("@sha256:", text)


if __name__ == "__main__":
    unittest.main()
