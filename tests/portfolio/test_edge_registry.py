"""Tests for RCx Central edge registry and API extensions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from portfolio.central.edge_registry import (
    _validate_base_url,
    add_or_update_edge,
    delete_edge,
    list_edges_public,
)


def test_validate_base_url_rejects_file_scheme():
    with pytest.raises(ValueError):
        _validate_base_url("file:///etc/passwd")


def test_add_list_delete_edge(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_CONFIG", str(cfg))
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_DATA", str(tmp_path / "data"))

    add_or_update_edge(
        site_id="demo",
        name="Demo Edge",
        base_url="http://127.0.0.1:8765",
        auth_type="password",
        username="agent",
        password="secret",
    )
    edges = list_edges_public()
    assert any(e["site_id"] == "demo" for e in edges)
    assert edges[0]["has_password"]
    assert "secret" not in json.dumps(edges)

    delete_edge("demo")
    assert not any(e["site_id"] == "demo" for e in list_edges_public())


def test_central_edges_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_CONFIG", str(cfg))
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_DATA", str(tmp_path / "data"))

    from portfolio.central.api import app

    client = TestClient(app)
    assert client.get("/health").json()["service"] == "openfdd-rcx-central"
    bad = client.post("/api/central/edges", json={"site_id": "x", "base_url": "ftp://bad"})
    assert bad.status_code == 400
    ok = client.post(
        "/api/central/edges",
        json={"site_id": "acme", "name": "Acme", "base_url": "http://127.0.0.1:8765", "password": "x"},
    )
    assert ok.status_code == 200
    assert client.get("/api/central/edges").json()["count"] >= 1


def test_dash_title():
    text = (Path(__file__).resolve().parents[2] / "portfolio" / "dash" / "app.py").read_text()
    assert 'title="OpenFDD RCx Central"' in text
    assert "OpenFDD RCx Central" in text
    for tab in ("Edge Connections", "Mechanical Summary", "FDD Analytics", "RCx Report Builder"):
        assert tab in text
