"""Container revision metadata for stack troubleshooting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_stack_revisions_reads_env(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge import container_revisions

    monkeypatch.setenv("OPENFDD_IMAGE_TAG", "2026.06.07-edge")
    monkeypatch.setenv("OPENFDD_BUILD_GIT_SHA", "abc1234")
    monkeypatch.setenv("OPENFDD_BUILD_TIME", "2026-06-05T12:00:00Z")
    monkeypatch.setattr(
        container_revisions,
        "commission_health",
        lambda timeout=None: (200, {"ok": True}),
    )
    payload = container_revisions.stack_revisions()
    assert payload["image_tag"] == "2026.06.07-edge"
    assert payload["git_sha"] == "abc1234"
    assert len(payload["services"]) >= 3
    bridge = next(s for s in payload["services"] if s["id"] == "bridge")
    assert bridge["image"] == "openfdd-bridge:2026.06.07-edge"
