from __future__ import annotations

from open_fdd.assistant.readiness import build_readiness_payload


def test_build_readiness_payload_includes_links_and_follow_up() -> None:
    model = {
        "sites": [{"id": "s-1", "name": "Demo"}],
        "points": [
            {"site_id": "s-1", "external_id": "oat", "brick_type": "Outside_Air_Temperature_Sensor"},
            {"site_id": "s-1", "external_id": "x", "brick_type": "Point"},
        ],
    }
    out = build_readiness_payload(model)
    assert out["sites"][0]["name"] == "Demo"
    assert out["deep_links"]["plots"].endswith("/plots")
    assert "yes" in out["message_markdown"].lower() and "no" in out["message_markdown"].lower()
