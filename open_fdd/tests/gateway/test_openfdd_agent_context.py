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
    assert any("MCP RAG is REST" in n for n in out.get("notes", []))


def test_build_context_bootstrap_merges_nested_endpoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bootstrap = tmp_path / "boot.json"
    bootstrap.write_text(
        json.dumps({"endpoints": {"readiness": "http://override.example/assistant/readiness"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OFDD_AGENT_BOOTSTRAP_FILE", str(bootstrap))
    monkeypatch.setenv("OFDD_BRIDGE_URL", "http://127.0.0.1:8888")
    out = ctxmod.build_agent_bootstrap_context()
    ep = out["endpoints"]
    assert ep["readiness"] == "http://override.example/assistant/readiness"
    assert "bridge_health" in ep
    assert ep["bridge_health"] == "http://127.0.0.1:8888/health"


def test_format_context_includes_optional_mcp_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BRIDGE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OFDD_MCP_REST_BASE", "http://127.0.0.1:8090")
    ctx = ctxmod.build_agent_bootstrap_context()
    assert ctx.get("toolshed", {}).get("scratch_rel") == "toolshed/scratch"
    md = ctxmod.format_agent_context_markdown(ctx)
    assert "Toolshed (file writes)" in md
    assert "toolshed/scratch" in md
    assert "MCP RAG (optional)" in md
    assert "/manifest" in md
    assert "search_docs" in md
    assert "search_api_capabilities" in md
    assert "timeseries/clean-metrics" in md
    assert "plots/site-frame" in md or "plots_site_frame" in md
