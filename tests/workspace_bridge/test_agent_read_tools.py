from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge import agent_tools  # noqa: E402


def test_operator_can_run_read_only_tool():
    out = agent_tools.run_tool("faults.lookup", {"code": "VAV-C"}, role="operator")
    assert out["code"] == "VAV-C"
    assert out["title"]


def test_operator_blocked_from_write_tool():
    with pytest.raises(agent_tools.ToolError, match="integrator or agent"):
        agent_tools.run_tool("model.add_site", {"name": "X"}, role="operator")


def test_model_graph_tool_returns_structure():
    out = agent_tools.run_tool("model.graph", {}, role="integrator")
    assert "site_id" in out
    assert "equipment" in out
