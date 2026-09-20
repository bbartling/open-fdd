"""UA-04: isolated ZAP runner must not persist JWT artifacts."""
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

    def test_fallback_does_not_satisfy_acceptance(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('AF_STATUS" == "FALLBACK"', text)
        self.assertIn("SUITE_PASS=false", text)


if __name__ == "__main__":
    unittest.main()
