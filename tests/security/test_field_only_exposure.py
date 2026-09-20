"""Field-only OT exposure lint (UA-08, CI, no Docker)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from field_only_exposure import (  # noqa: E402
    EDGE_COMPOSE,
    EXPOSURE,
    lint_edge_compose,
    lint_exposure,
    run_config_lint,
)


class FieldOnlyExposureTest(unittest.TestCase):
    def test_assets_exist(self):
        self.assertTrue(EXPOSURE.is_file(), EXPOSURE)
        self.assertTrue(EDGE_COMPOSE.is_file(), EDGE_COMPOSE)

    def test_exposure_lint(self):
        data = json.loads(EXPOSURE.read_text(encoding="utf-8"))
        errs = lint_exposure(data)
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_compose_lint(self):
        errs = lint_edge_compose(EDGE_COMPOSE.read_text(encoding="utf-8"))
        self.assertEqual(errs, [], msg="\n".join(errs))

    def test_config_lint_report_ok(self):
        report = run_config_lint()
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))
        self.assertEqual(report["verdict"], "PASS")

    def test_exposure_rejects_required_local_central(self):
        data = json.loads(EXPOSURE.read_text(encoding="utf-8"))
        data["requires_local"] = ["central"]
        errs = lint_exposure(data)
        self.assertTrue(any("require" in e for e in errs))

    def test_compose_rejects_bundled_central(self):
        bad = EDGE_COMPOSE.read_text(encoding="utf-8") + "\n  openfdd-central:\n    image: x\n"
        errs = lint_edge_compose(bad)
        self.assertTrue(any("central" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
