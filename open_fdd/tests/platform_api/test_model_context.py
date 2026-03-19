"""Tests for /model-context docs endpoint."""

import pytest
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app


@pytest.fixture
def docs_txt_path(tmp_path, monkeypatch):
    """CI and fresh clones omit pdf/open-fdd-docs.txt (gitignored); point at a tiny fixture file."""
    p = tmp_path / "open-fdd-docs.txt"
    p.write_text(
        "# Home\n\n## Quick start\n\n"
        "Use GET /data-model/export and PUT /data-model/import.\n\n"
        "# Data model\n\n"
        "The data-model export lists points for external tagging.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OFDD_DOCS_PATH", str(p))
    yield p
    monkeypatch.delenv("OFDD_DOCS_PATH", raising=False)


@pytest.fixture
def client(docs_txt_path):
    """Fresh TestClient after OFDD_DOCS_PATH is set (import-time wiring stays the same)."""
    return TestClient(app)


def test_model_context_docs_excerpt_returns_text_plain(client):
    r = client.get("/model-context/docs?mode=excerpt&max_chars=1200")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/plain")
    text = r.text
    assert "## Quick start" in text or "## What it does" in text


def test_model_context_docs_query_retrieval_returns_relevant_text(client):
    r = client.get("/model-context/docs?query=data-model%20export&top_k=4&max_chars=2500")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/plain")
    text = r.text.lower()
    assert "data-model" in text
    assert "export" in text


def test_model_context_docs_invalid_mode_returns_400(client):
    r = client.get("/model-context/docs?mode=not_a_mode")
    assert r.status_code == 400


def test_model_context_docs_missing_file_returns_404(tmp_path, monkeypatch):
    """404 when OFDD_DOCS_PATH points at a missing file (do not rely on repo gitignore)."""
    missing = tmp_path / "definitely-not-there.txt"
    monkeypatch.setenv("OFDD_DOCS_PATH", str(missing))
    c = TestClient(app)
    r = c.get("/model-context/docs?mode=excerpt")
    assert r.status_code == 404
