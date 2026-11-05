"""Final-image scanner scope must include the Phase 5D split images."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "security" / "trivy_ghcr_digests.sh"


class TrivyImageScopeTest(unittest.TestCase):
    def test_all_scope_includes_both_split_connectors(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("images=(central web mqtt fieldbus bacnet-modbus haystack mcp caddy)", text)
        self.assertIn("bacnet-modbus|haystack", text)

    def test_split_refs_use_immutable_candidate_tag_path(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('ghcr.io/bbartling/openfdd-${name}:${TAG}', text)
        self.assertIn('${name}.ref', text)


if __name__ == "__main__":
    unittest.main()
