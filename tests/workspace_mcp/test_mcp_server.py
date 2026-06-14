from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.bridge import BridgeClient
from mcp_server.config import McpConfig
from mcp_server.errors import HumanApprovalRequired
from mcp_server.rag import DocSearch
from mcp_server.sites import SiteRecord, SiteRegistry


def test_site_registry_redacts_secrets(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "sites": [
                    {
                        "site_id": "lab",
                        "base_url": "http://127.0.0.1:8765",
                        "username": "integrator",
                        "password": "secret-pass",
                        "token": "tok-abc",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reg = SiteRegistry(path, default_site_id="lab")
    payload = reg.redacted_payload()
    row = payload["sites"][0]
    assert row["password"] == "***"
    assert row["token"] == "***"
    assert "secret-pass" not in json.dumps(payload)


def test_bridge_client_url_and_auth_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=60):
        calls.append({"url": req.full_url, "headers": dict(req.header_items()), "method": req.method})
        if req.full_url.endswith("/api/auth/login"):
            return FakeResp(json.dumps({"token": "jwt-test"}).encode())
        return FakeResp(json.dumps({"ok": True}).encode())

    monkeypatch.setattr("mcp_server.bridge.urlopen", fake_urlopen)
    cfg = McpConfig(
        mode="edge",
        transport="stdio",
        host="127.0.0.1",
        port=8090,
        bridge_base_url="http://127.0.0.1:8765",
        rag_index_path=Path("/tmp/rag.json"),
        portfolio_sites_path=Path("/tmp/sites.json"),
        default_site_id="lab",
    )
    reg = SiteRegistry(
        cfg.portfolio_sites_path,
        edge_base_url=cfg.bridge_base_url,
        default_site_id="lab",
    )
    reg._sites["lab"] = SiteRecord(
        site_id="lab",
        base_url="http://127.0.0.1:8765",
        username="integrator",
        password="pw",
    )
    client = BridgeClient(cfg, reg)
    out = client.get("lab", "/health", auth_required=True)
    assert out["ok"] is True
    assert any(c["url"].endswith("/api/auth/login") for c in calls)
    health = [c for c in calls if c["url"].endswith("/health")][0]
    assert health["headers"].get("Authorization") == "Bearer jwt-test"


def test_human_approval_required() -> None:
    from mcp_server.server import apply_fdd_tuning, run_fdd_batch, save_rule

    for fn, kwargs in (
        (apply_fdd_tuning, {"site_id": "x", "human_approved": False}),
        (run_fdd_batch, {"site_id": "x", "human_approved": False}),
        (
            save_rule,
            {"site_id": "x", "rule_id": "r1", "code": "x=1", "config": {}, "human_approved": False},
        ),
    ):
        raw = fn(**kwargs)
        payload = json.loads(raw)
        assert payload["ok"] is False
        assert "human_approved" in payload["error"]


def test_rag_search_wrapper(repo_root: Path) -> None:
    index = repo_root / "workspace" / "data" / "mcp" / "rag_index.json"
    if not index.is_file():
        pytest.skip("rag index not present")
    docs = DocSearch(index)
    out = docs.search("BACnet poll", top_k=2)
    assert out["count"] >= 1
    assert out["results"][0]["content"]


def test_mcp_lists_tools() -> None:
    import asyncio

    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "health_check" in names
    assert "search_docs" in names
    assert "save_rule" in names
    assert "list_rules" in names
    assert "get_building_status" in names


def test_agent_guide_resource() -> None:
    import asyncio

    from mcp_server.server import mcp

    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "openfdd://agent-guide" in uris
