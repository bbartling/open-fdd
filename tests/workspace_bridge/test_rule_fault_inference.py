from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

RULE = (
    "def evaluate(row, cfg, prev_row=None, rows=None):\n"
    "    spread = row.get('spread_1h')\n"
    "    return spread is not None and float(spread) < 0.1\n"
)


def test_deterministic_flatline_guess():
    from openfdd_bridge.rule_fault_inference import infer_fault_codes_for_rule  # noqa: E402

    with patch("openfdd_bridge.ollama_client.chat", return_value={"ok": False, "error": "offline"}):
        with patch(
            "openfdd_bridge.rule_fault_inference.build_applicable_payload",
            return_value={"site_id": "demo", "families": [], "assigned_rules": []},
        ):
            out = infer_fault_codes_for_rule(name="OA-T flatline 1h", code=RULE, site_id="demo")
    assert out["fault_codes"]
    assert out["source"] == "deterministic"


def test_infer_route(client: TestClient):
    r = client.post("/api/rules/infer-fault-codes", json={"name": "x", "code": RULE})
    assert r.status_code == 200
    assert "fault_codes" in r.json()


def test_save_auto_infers_when_no_fault_codes(client: TestClient):
    with patch(
        "openfdd_bridge.rule_fault_inference.infer_fault_codes_for_rule",
        return_value={
            "ok": True,
            "fault_codes": ["VAV-C"],
            "fault_code": "VAV-C",
            "narrative": "Sensor flatline rule maps to VAV-C.",
            "source": "ollama",
            "ollama_ok": True,
        },
    ):
        r = client.post(
            "/api/rules/save",
            json={"name": "Flatline", "mode": "rule", "code": RULE, "config": {}},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["rule"]["fault_codes"] == ["VAV-C"]
    assert body.get("fault_inference", {}).get("narrative")
