"""Tests for rule source-expanded API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_expand_rule_source_falls_back_to_inline_code(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge.rule_source_expanded import expand_rule_source

    monkeypatch.setattr(
        "openfdd_bridge.rule_source_expanded.RuleStore",
        lambda: type(
            "S",
            (),
            {
                "get": lambda self, rid: {
                    "id": rid,
                    "name": "Temperature out of bounds",
                    "source_path": "/nonexistent/temperature_out_of_bounds.py",
                    "code": "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.less(table['oa-t'], 40)\n",
                },
            },
        )(),
    )
    monkeypatch.setattr("openfdd_bridge.rule_source_expanded.read_source", lambda _path: "")

    out = expand_rule_source(rule_id="temp-out-of-bounds")
    assert out["ok"] is True
    assert "apply_faults_arrow" in out["rule_source"]


def test_source_expanded_http_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "openfdd_bridge.rule_source_expanded.expand_rule_source",
        lambda rule_id: {
            "ok": True,
            "rule_id": rule_id,
            "rule_source": "def apply_faults_arrow(table, cfg, context=None):\n    return table",
            "imports": [],
            "warnings": [],
        },
    )
    res = client.get("/api/playground/rules/temp-out-of-bounds/source-expanded")
    assert res.status_code == 200
    assert res.json()["ok"] is True
