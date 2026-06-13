"""Tests for sites.json path resolution (empty config must not shadow legacy)."""

from __future__ import annotations

import json
from pathlib import Path

from portfolio.central.paths import sites_path


def test_empty_config_falls_back_to_legacy(tmp_path, monkeypatch):
    root = tmp_path / "portfolio"
    root.mkdir()
    cfg = root / "config"
    cfg.mkdir()
    (cfg / "sites.json").write_text(json.dumps({"sites": []}), encoding="utf-8")
    (root / "sites.json").write_text(
        json.dumps({"sites": [{"site_id": "lab", "name": "Lab", "base_url": "http://127.0.0.1:8765"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_CONFIG", str(cfg))
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_DATA", str(root / "data"))

    import portfolio.central.paths as mod

    monkeypatch.setattr(mod, "portfolio_root", lambda: root)
    assert sites_path() == root / "sites.json"
