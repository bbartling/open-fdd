from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.mcp_rag import app as mcp_api
mcp_app_module = importlib.import_module("open_fdd.mcp_rag.app")


def _write_index(tmp_path: Path) -> Path:
    path = tmp_path / "rag_index.json"
    path.write_text(
        """
{
  "version": 1,
  "doc_count": 1,
  "docs": [
    {
      "chunk_id": "chunk-1",
      "source": "docs/howto/desktop_app.md",
      "section": "Desktop app",
      "content": "drivers bacnet weather onboard and csv ingest",
      "tags": ["docs", "markdown"],
      "endpoint_refs": ["/config/bacnet"],
      "length": 7
    }
  ],
  "idf": {"drivers": 2.0, "bacnet": 2.0},
  "postings": {"drivers": {"chunk-1": 1}, "bacnet": {"chunk-1": 1}}
}
""".strip(),
        encoding="utf-8",
    )
    return path


def test_mcp_manifest_contains_driver_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_app_module, "_idx", None)
    client = TestClient(mcp_api)
    response = client.get("/manifest")
    assert response.status_code == 200
    tools = {tool["name"] for tool in response.json().get("tools", [])}
    assert "search_docs" in tools
    assert "drivers_health" in tools
    assert "bacnet_config_set" in tools


def test_mcp_search_docs_reads_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    idx_path = _write_index(tmp_path)
    monkeypatch.setattr(mcp_app_module, "INDEX_PATH", idx_path)
    monkeypatch.setattr(mcp_app_module, "_idx", None)
    client = TestClient(mcp_api)
    response = client.post("/tools/search_docs", json={"query": "drivers", "top_k": 3})
    assert response.status_code == 200
    body = response.json()
    assert int(body.get("count", 0)) >= 1
    assert body.get("results", [])[0].get("chunk_id") == "chunk-1"


def test_mcp_action_tool_blocked_when_disabled() -> None:
    client = TestClient(mcp_api)
    response = client.post("/tools/drivers_health")
    assert response.status_code == 403
    assert "disabled" in str(response.json().get("detail", "")).lower()


def test_mcp_health_hints_loopback_and_typo_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    idx_path = _write_index(tmp_path)
    monkeypatch.setattr(mcp_app_module, "INDEX_PATH", idx_path)
    monkeypatch.setattr(mcp_app_module, "_idx", None)
    monkeypatch.setattr(mcp_app_module, "OFDD_API_URL", "http://127.0.0.1:8765")
    client = TestClient(mcp_api)
    res = client.get("/health")
    assert res.status_code == 200
    j = res.json()
    assert j.get("ok") is True
    assert "127.0.0.1:8090" in str(j.get("mcp_listen_hint", ""))
    assert "url_warnings" not in j

    monkeypatch.setattr(mcp_app_module, "OFDD_API_URL", "http://127.0.1:8765")
    monkeypatch.setattr(mcp_app_module, "_idx", None)
    res2 = client.get("/health")
    assert res2.status_code == 200
    j2 = res2.json()
    assert j2.get("url_warnings")
    assert "127.0.0.1" in j2["url_warnings"][0]

