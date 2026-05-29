from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge import ollama_client  # noqa: E402
from openfdd_bridge.ollama_profiles import (  # noqa: E402
    OLLAMA_PROFILES,
    gpu_options_payload,
    normalize_ram_tier,
    profile_for_tier,
    tiers_payload,
)


def test_normalize_ram_tier_defaults_to_8gb():
    assert normalize_ram_tier(None) == "8gb"
    assert normalize_ram_tier("bogus") == "8gb"
    assert normalize_ram_tier("32GB") == "32gb"


def test_profiles_cover_all_tiers():
    assert set(OLLAMA_PROFILES) == {"8gb", "16gb", "32gb", "64gb"}
    assert profile_for_tier("8gb").model == "tinyllama"


def test_tiers_and_gpu_payloads():
    tiers = tiers_payload()
    assert tiers[0]["ram_tier"] == "8gb"
    assert any(t["model"] == "tinyllama" for t in tiers)
    gpu = gpu_options_payload()
    assert {g["id"] for g in gpu} == {"cpu", "auto", "gpu"}


def test_resolve_model_and_gpu(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_OLLAMA_RAM_TIER", "16gb")
    monkeypatch.delenv("OFDD_OLLAMA_MODEL", raising=False)
    assert ollama_client.resolve_model() == "llama3.2:1b"
    assert ollama_client.resolve_model(model="custom:7b") == "custom:7b"
    assert ollama_client.resolve_num_gpu(gpu_mode="gpu") == 99
    assert ollama_client.resolve_num_gpu(gpu_mode="auto") == -1
    assert ollama_client.resolve_num_gpu(gpu_mode="cpu") == 0


def test_configured_num_gpu_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_OLLAMA_NUM_GPU", "12")
    assert ollama_client.configured_num_gpu() == 12
    monkeypatch.delenv("OFDD_OLLAMA_NUM_GPU", raising=False)
    monkeypatch.setenv("OFDD_OLLAMA_GPU_MODE", "auto")
    assert ollama_client.configured_num_gpu() == -1


def _mock_httpx_client(*, get_json=None, post_json=None):
    mock_client = MagicMock()

    if get_json is not None:
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.json.return_value = get_json
        mock_client.get.return_value = get_resp

    if post_json is not None:
        post_resp = MagicMock()
        post_resp.raise_for_status = MagicMock()
        post_resp.json.return_value = post_json
        mock_client.post.return_value = post_resp

    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_health_ok():
    client = _mock_httpx_client(get_json={"models": [{"name": "tinyllama:latest"}]})
    with patch("openfdd_bridge.ollama_client.httpx.Client", return_value=client):
        result = ollama_client.health()
    assert result["ok"] is True
    assert "tinyllama:latest" in result["models_installed"]


def test_health_down():
    with patch(
        "openfdd_bridge.ollama_client.httpx.Client",
        side_effect=ConnectionError("refused"),
    ):
        result = ollama_client.health()
    assert result["ok"] is False
    assert "refused" in result["error"]


def test_chat_success():
    client = _mock_httpx_client(
        post_json={"message": {"content": "Check SAT trend in Rule Lab."}, "eval_count": 3},
    )
    with patch("openfdd_bridge.ollama_client.httpx.Client", return_value=client):
        result = ollama_client.chat("hello", ram_tier="8gb", gpu_mode="cpu")
    assert result["ok"] is True
    assert result["mode"] == "ollama"
    assert result["model"] == "tinyllama"
    assert result["num_gpu"] == 0
    assert "Rule Lab" in result["reply"]
    payload = client.post.call_args.kwargs["json"]
    assert payload["model"] == "tinyllama"
    assert payload["options"]["num_gpu"] == 0


def test_model_installed():
    client = _mock_httpx_client(get_json={"models": [{"name": "tinyllama:latest"}]})
    with patch("openfdd_bridge.ollama_client.httpx.Client", return_value=client):
        assert ollama_client.model_installed("tinyllama") is True
        assert ollama_client.model_installed("llama3.2:3b") is False
        assert ollama_client.model_installed("llama3.2") is False

    loose = _mock_httpx_client(get_json={"models": [{"name": "llama3.21:latest"}]})
    with patch("openfdd_bridge.ollama_client.httpx.Client", return_value=loose):
        assert ollama_client.model_installed("llama3.2") is False
        assert ollama_client.model_installed("llama3.2:3b") is False


def test_should_use_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_AI_BACKEND", "codex")
    assert ollama_client.should_use_ollama() is False
    monkeypatch.setenv("OFDD_AI_BACKEND", "ollama")
    assert ollama_client.should_use_ollama() is True
    monkeypatch.setenv("OFDD_AI_BACKEND", "auto")
    monkeypatch.setattr(ollama_client, "health", lambda timeout=3.0: {"ok": True})
    assert ollama_client.should_use_ollama() is True
    monkeypatch.setattr(ollama_client, "health", lambda timeout=3.0: {"ok": False})
    assert ollama_client.should_use_ollama() is False


def test_agent_chat_ollama_backend():
    from fastapi.testclient import TestClient

    from openfdd_bridge.main import create_app  # noqa: E402

    client = TestClient(create_app())
    with patch(
        "openfdd_bridge.routes.agent_routes.ollama_client.chat",
        return_value={"ok": True, "mode": "ollama", "model": "tinyllama", "reply": "ok"},
    ):
        r = client.post(
            "/openfdd-agent/chat",
            json={"message": "ping", "backend": "ollama", "ram_tier": "8gb", "gpu_mode": "cpu"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["mode"] == "ollama"
    assert body["reply"] == "ok"


def test_agent_context_includes_ollama_tiers():
    from fastapi.testclient import TestClient

    from openfdd_bridge.main import create_app  # noqa: E402

    client = TestClient(create_app())
    with patch(
        "openfdd_bridge.routes.agent_routes.ollama_client.health",
        return_value={"ok": False, "error": "down"},
    ):
        r = client.get("/openfdd-agent/context")
    assert r.status_code == 200
    body = r.json()
    assert body["ollama_tiers"]
    assert body["ollama_gpu_options"]
    assert body["ollama"]["ok"] is False
