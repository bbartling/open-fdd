"""Tests for /model-context docs endpoint."""

from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_model_context_docs_excerpt_returns_text_plain():
    r = client.get("/model-context/docs?mode=excerpt&max_chars=1200")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/plain")
    text = r.text
    assert "## Quick start" in text or "## What it does" in text


def test_model_context_docs_query_retrieval_returns_relevant_text():
    r = client.get("/model-context/docs?query=data-model%20export&top_k=4&max_chars=2500")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/plain")
    text = r.text.lower()
    assert "data-model" in text
    assert "export" in text


def test_model_context_docs_invalid_mode_returns_400():
    r = client.get("/model-context/docs?mode=not_a_mode")
    assert r.status_code == 400

