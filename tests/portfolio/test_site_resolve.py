"""Tests for auto site_id resolution from Edge URL + name."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from portfolio.central.site_resolve import derive_site_id, normalize_base_url, resolve_site_id


def test_normalize_base_url_strips_path_and_trailing_slash():
    assert normalize_base_url("http://100.122.106.124/") == "http://100.122.106.124"
    assert normalize_base_url("100.122.106.124") == "http://100.122.106.124"


def test_derive_site_id_from_name():
    assert derive_site_id(base_url="http://10.0.0.1", name="Acme GL36 Lab") == "acme"


def test_resolve_site_id_matches_existing_url(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "sites.json").write_text(
        json.dumps(
            {
                "sites": [
                    {"site_id": "acme", "name": "Acme", "base_url": "http://100.122.106.124", "username": "integrator"}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_CONFIG", str(cfg))
    assert resolve_site_id(base_url="http://100.122.106.124/", name="Anything") == "acme"


def test_resolve_site_id_requires_url():
    with pytest.raises(ValueError):
        resolve_site_id(base_url="", name="Acme")
