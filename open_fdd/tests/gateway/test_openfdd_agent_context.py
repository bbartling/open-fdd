"""Tests for Open-FDD agent bootstrap context."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_fdd.gateway import openfdd_agent_context as ctxmod


def test_build_context_merges_bootstrap_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bootstrap = tmp_path / "boot.json"
    bootstrap.write_text(
        json.dumps({"notes": ["from file"], "custom": 1}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OFDD_AGENT_BOOTSTRAP_FILE", str(bootstrap))
    monkeypatch.setenv("OFDD_BRIDGE_URL", "http://127.0.0.1:9999")
    out = ctxmod.build_agent_bootstrap_context()
    assert out["bridge_base"] == "http://127.0.0.1:9999"
    assert out["custom"] == 1
    assert "from file" in out.get("notes", [])
