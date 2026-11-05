"""Static checks for scripts/openfdd_demo_gate.sh (demo URL gate)."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "openfdd_demo_gate.sh"


class DemoGateRecipeTest(unittest.TestCase):
    def test_ghcr_mode_targets_central_static_app(self):
        text = GATE.read_text()
        self.assertIn("--ghcr-web", text)
        self.assertIn("openfdd-central", text)
        self.assertIn("ghcr_newest_by_created.py", text)
        self.assertIn('assert_static_app', text)
        self.assertIn("/app/assets/js/app.js", text)
        self.assertNotIn("openfdd-react-web-1 is not running", text)
        self.assertNotRegex(text, r'ghcr_newest_by_created\.py.*openfdd-web"\s*\)')
        self.assertNotIn('NEWEST="$("$ROOT/scripts/ghcr_newest_by_created.py" --json openfdd-web)"', text)

    def test_local_mode_still_checks_web_container(self):
        text = GATE.read_text()
        self.assertIn("--local-web", text)
        self.assertIn("OPENFDD_WEB_CONTAINER", text)
        self.assertIn("Unmerged", text)

    def test_requires_explicit_mode(self):
        text = GATE.read_text()
        self.assertIn('if [[ -z "$MODE" ]]; then', text)


if __name__ == "__main__":
    unittest.main()
