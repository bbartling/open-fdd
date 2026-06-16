"""Building insight must not HTTP-500 when status collection fails."""

from __future__ import annotations

import pytest


def test_building_insight_returns_error_payload_on_collect_failure(monkeypatch: pytest.MonkeyPatch):
    import openfdd_bridge.building_insight as mod

    monkeypatch.setattr(mod, "collect_status", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = mod.get_building_insight(force=True)
    assert out.get("source") == "error"
    assert out.get("ok") is False
    assert "boom" in str(out.get("error") or "")
