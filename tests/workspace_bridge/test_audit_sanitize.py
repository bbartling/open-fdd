from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.audit import _sanitize_detail, sanitize_agent_tool_args  # noqa: E402


def test_sanitize_detail_redacts_token_in_nested_list():
    detail = {
        "items": [{"token": "secret-token", "ok": True}],
        "nested": {"authorization": "Bearer xyz", "path": "/api/foo"},
    }
    out = _sanitize_detail(detail)
    assert out["items"] == [{"ok": True}]
    assert "authorization" not in out["nested"]
    assert out["nested"]["path"] == "/api/foo"


def test_sanitize_agent_tool_args_keeps_non_prompt_fields(monkeypatch):
    monkeypatch.delenv("OFDD_AUDIT_LOG_PROMPTS", raising=False)
    out = sanitize_agent_tool_args("chat", {"message": "x" * 500, "site_id": "demo"})
    assert out["site_id"] == "demo"
    assert out["message_len"] == 500
    assert "message_hash" in out
