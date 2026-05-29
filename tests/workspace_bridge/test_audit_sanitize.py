from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.audit import _sanitize_detail  # noqa: E402


def test_sanitize_detail_redacts_token_in_nested_list():
    detail = {
        "items": [{"token": "secret-token", "ok": True}],
        "nested": {"authorization": "Bearer xyz", "path": "/api/foo"},
    }
    out = _sanitize_detail(detail)
    assert out["items"] == [{"ok": True}]
    assert "authorization" not in out["nested"]
    assert out["nested"]["path"] == "/api/foo"
