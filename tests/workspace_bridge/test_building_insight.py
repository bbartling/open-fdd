from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.building_insight import _fallback_sentence, get_building_insight  # noqa: E402


def test_fallback_sentence_no_alerts():
    text = _fallback_sentence({"alerts": [], "status": "ok", "traffic": "green"})
    assert "no active faults" in text.lower()


def test_fallback_sentence_with_alerts():
    text = _fallback_sentence(
        {
            "alerts": [{"title": "OA temp high", "severity": "warning"}],
            "status": "warning",
            "traffic": "yellow",
            "fdd_alert_count": 1,
        }
    )
    assert "OA temp high" in text


def test_get_building_insight_deterministic_when_ollama_down(monkeypatch):
    import openfdd_bridge.building_insight as mod

    monkeypatch.setattr(
        mod,
        "collect_status",
        lambda: {"alerts": [], "status": "ok", "traffic": "green", "fdd_alert_count": 0},
    )
    monkeypatch.setattr(mod.ollama_client, "health", lambda **_: {"ok": False, "error": "down"})
    monkeypatch.setattr(mod.ollama_client, "should_use_ollama", lambda: False)
    mod._CACHE.clear()
    mod._CACHE.update({"generated_at": 0.0, "sentence": "", "next_refresh_at": 0.0})
    out = get_building_insight(force=True)
    assert out["ok"] is True
    assert out["sentence"]
    assert out["source"] == "deterministic"
