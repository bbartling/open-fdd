from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_commission_agent_cfg_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    comm = tmp_path / "commissioning"
    comm.mkdir()
    (comm / "commission.env").write_text(
        "SITE_ID=demo\nBUILDING_ID=local\nBACNET_BIND=192.168.1.10/24\n"
        "BACNET_NAME=OpenFddEdge\nBACNET_INSTANCE=599999\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.chdir(REPO)
    from bacnet_toolshed import commission_agent  # noqa: E402

    monkeypatch.setattr(commission_agent, "commissioning_dir", lambda: comm)
    monkeypatch.setattr(commission_agent, "ENV_FILE", comm / "commission.env")
    cfg = commission_agent._cfg()
    assert cfg["BACNET_BIND"].startswith("192.168.1.10/24")
    assert cfg["BACNET_INSTANCE"] == "599999"


def test_stack_poll_health_uses_commission_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    ws = tmp_path / "workspace"
    comm = ws / "bacnet" / "commissioning"
    comm.mkdir(parents=True)
    (comm / "points.csv").write_text("device_instance,enabled\n5007,1\n", encoding="utf-8")
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("OPENFDD_MCP_ENABLED", "0")

    from openfdd_bridge import stack_health as sh  # noqa: E402

    monkeypatch.setattr(
        sh,
        "commission_health",
        lambda: (200, {"ok": True}),
    )
    monkeypatch.setattr(
        sh,
        "commission_status",
        lambda: (200, {"bacnet_bind": "192.168.1.10/24"}),
    )
    monkeypatch.setattr(
        sh,
        "commission_poll_status",
        lambda: (
            200,
            {
                "ok": True,
                "enabled_points": 2,
                "interval_s": 60,
                "samples": 2,
                "error": "",
                "at": "2026-05-30T16:26:07Z",
            },
        ),
    )
    monkeypatch.setattr(sh, "_parse_poll_at", lambda _at: 5.0)

    svc = sh._bacnet_poll_service()
    assert svc["status"] == "green"
    assert "2 point(s)" in svc["detail"]

    monkeypatch.setattr(sh, "commission_poll_status", lambda: (503, {"error": "down"}))
    monkeypatch.setattr(sh, "commission_health", lambda: (503, {"ok": False}))
    svc_down = sh._bacnet_poll_service()
    assert svc_down["status"] == "red"
    assert "commission agent down" in svc_down["detail"]
