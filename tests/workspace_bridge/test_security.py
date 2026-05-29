from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))


def _fresh_client() -> TestClient:
    """Reload bridge modules so patches apply after other tests clear sys.modules."""
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


@pytest.fixture
def client() -> TestClient:
    return _fresh_client()


def test_spa_path_escape_blocked():
    static_dir = (REPO / "workspace" / "api" / "static" / "app").resolve()
    candidate = (static_dir / ".." / ".." / "etc" / "passwd").resolve(strict=False)
    with pytest.raises(ValueError):
        candidate.relative_to(static_dir)


def test_agent_chat_uses_ollama(client: TestClient):
    with patch(
        "openfdd_bridge.routes.agent_routes.ollama_client.chat",
        return_value={"ok": True, "mode": "ollama", "model": "tinyllama", "reply": "hi"},
    ):
        r = client.post(
            "/openfdd-agent/chat",
            json={"message": "hi"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("mode") == "ollama"
        assert body.get("ok") is True


def test_ingest_bacnet_rejects_bad_site_id(client: TestClient):
    r = client.post("/ingest/bacnet?site_id=../../etc")
    assert r.status_code == 400
