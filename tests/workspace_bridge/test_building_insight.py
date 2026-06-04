from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.building_insight import _fallback_sentence, get_building_insight  # noqa: E402


def test_fallback_sentence_no_alerts():
    text = _fallback_sentence(
        {"alerts": [], "status": "ok", "traffic": "green"},
        {"summary_sentence": "Zone temps: ok."},
        {"summary_sentence": "Poll health: 2/2 healthy."},
    )
    assert "no active faults" in text.lower()


def test_fallback_sentence_with_alerts():
    text = _fallback_sentence(
        {
            "alerts": [{"title": "OA temp high", "severity": "warning"}],
            "status": "warning",
            "traffic": "yellow",
            "fdd_alert_count": 1,
        },
        {},
        {},
    )
    assert "OA temp high" in text or "alert" in text.lower()


def test_fault_sentences_from_alerts():
    from openfdd_bridge.building_insight import fault_sentences_from_alerts

    lines = fault_sentences_from_alerts(
        [{"code": "VAV-C", "title": "Zone temp OOB", "detail": "12 samples", "severity": "warning"}]
    )
    assert len(lines) == 1
    assert "VAV-C" in lines[0]


def test_compact_context_includes_zone_research(monkeypatch):
    import openfdd_bridge.building_insight as mod

    zone = {
        "summary_sentence": "Zone temps: test.",
        "research": {
            "site_flags": ["site_near_zero_recovery"],
            "site_median_recovery_f_per_min": 0.01,
            "minimal_setback_zone_count": 10,
            "llm_research_tasks": ["Check setback."],
            "opportunities": [{"topic": "energy_setback", "signal": "x", "suggestion": "y"}],
        },
    }
    ctx = mod._compact_context({"alerts": []}, zone, {"summary_sentence": "ok"})
    parsed = __import__("json").loads(ctx)
    assert "zone_research" in parsed
    assert parsed["zone_research"]["site_flags"]


def test_get_building_insight_deterministic_when_ollama_down(monkeypatch):
    import openfdd_bridge.building_insight as mod

    monkeypatch.setattr(
        mod,
        "collect_status",
        lambda: {"alerts": [], "status": "ok", "traffic": "green", "fdd_alert_count": 0},
    )
    monkeypatch.setattr(
        mod,
        "get_zone_temp_snapshot",
        lambda **_: {"summary_sentence": "Zone temps: test.", "worst_zones": [], "struggling_zones": []},
    )
    monkeypatch.setattr(
        mod,
        "get_device_poll_snapshot",
        lambda **_: {"summary_sentence": "Devices ok.", "offline_equipment": [], "flaky_equipment": []},
    )
    monkeypatch.setattr(mod.ollama_client, "health", lambda **_: {"ok": False, "error": "down"})
    monkeypatch.setattr(mod.ollama_client, "should_use_ollama", lambda: False)
    mod._CACHE.clear()
    mod._CACHE.update({"generated_at": 0.0, "sentence": "", "next_refresh_at": 0.0, "payload": {}})
    out = get_building_insight(force=True)
    assert out["ok"] is True
    assert out["sentence"]
    assert out["source"] == "deterministic"
    assert out.get("lookback_days") == 14
    assert "methodology" in out
