from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_ensure_default_site(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_ID", "edge-1")
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_NAME", "Edge box")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.model_service import ModelService  # noqa: E402
    from openfdd_bridge.site_defaults import ensure_default_site  # noqa: E402
    from openfdd_bridge.ttl_service import TtlService  # noqa: E402

    svc = ModelService()
    sid = ensure_default_site(svc, TtlService())
    assert sid == "edge-1"
    model = svc.load()
    assert model["sites"][0]["id"] == "edge-1"
    assert model["sites"][0]["name"] == "Edge box"


def test_rule_source_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_source import read_source, write_source  # noqa: E402

    path = write_source(rule_id="abc", name="SAT High", code="def evaluate(row, cfg, **kw):\n    return False\n")
    assert Path(path).is_file()
    assert "evaluate" in read_source(path)
