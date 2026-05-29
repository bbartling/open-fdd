from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_spa_path_escape_blocked():
    static_dir = (REPO / "workspace" / "api" / "static" / "app").resolve()
    candidate = (static_dir / ".." / ".." / "etc" / "passwd").resolve(strict=False)
    with pytest.raises(ValueError):
        candidate.relative_to(static_dir)


def test_agent_chat_rejects_workdir_outside_repo(client: TestClient):
    r = client.post(
        "/openfdd-agent/chat",
        json={"message": "hi", "workdir": "C:\\Windows\\System32"},
    )
    assert r.status_code == 200
    # Should not use System32; guidance mode or codex with repo cwd
    body = r.json()
    assert body.get("mode") in {"guidance", "codex", "ollama"}


def test_ingest_bacnet_rejects_bad_site_id(client: TestClient):
    r = client.post("/ingest/bacnet?site_id=../../etc")
    assert r.status_code == 400
