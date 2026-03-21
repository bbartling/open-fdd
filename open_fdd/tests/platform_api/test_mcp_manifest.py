"""Tests for GET /mcp/manifest discovery endpoint."""

from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app
from open_fdd.platform.api.mcp_bridge import SCHEMA_VERSION

client = TestClient(app)


def test_mcp_manifest_structure():
    r = client.get("/mcp/manifest")
    assert r.status_code == 200
    data = r.json()
    assert data.get("schema_version") == SCHEMA_VERSION
    assert data.get("server", {}).get("name") == "open-fdd"
    resources = data.get("resources") or []
    assert any("openfdd://docs" in str(res.get("uri", "")) for res in resources)
    tools = data.get("tools") or []
    paths = {t.get("http", {}).get("path") for t in tools if isinstance(t, dict)}
    assert "/model-context/docs" in paths
    assert "/data-model/export" in paths
    assert "/data-model/import" in paths
    assert "/capabilities" in paths
