"""Commission agent must keep BACnet Application alive across Who-Is and point discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def commission_module(monkeypatch: pytest.MonkeyPatch):
    for name in list(sys.modules):
        if name == "bacnet_toolshed.commission_agent" or name.startswith("bacnet_toolshed.commission_agent."):
            del sys.modules[name]
    import bacnet_toolshed.commission_agent as agent  # noqa: E402

    monkeypatch.setattr(agent, "_bacnet_app", None)
    monkeypatch.setattr(agent, "_bacnet_app_cfg_key", None)
    return agent


def test_whois_then_point_discovery_reuses_live_app(commission_module, monkeypatch: pytest.MonkeyPatch):
    agent = commission_module
    calls: list[str] = []

    async def fake_whois(app, low, high):
        calls.append("whois")
        return [{"device_instance": 5007}]

    async def fake_pd(app, instance_id, device_address=None):
        calls.append(f"pd:{instance_id}:{device_address}")
        return {"device_instance": instance_id, "device_address": device_address or "x", "objects": [{"object_identifier": "ai,1", "name": "t"}]}

    monkeypatch.setattr(agent, "_cfg", lambda: {"BACNET_BIND": "192.168.1.1/24:47808"})
    monkeypatch.setattr(agent, "perform_who_is", fake_whois)
    monkeypatch.setattr(agent, "point_discovery", fake_pd)

    mock_app = object()
    monkeypatch.setattr(agent, "_bacnet_app_from_cfg", lambda cfg: mock_app)

    who = agent._sync_who_is(1, 4194303)
    assert who["count"] == 1
    assert calls == ["whois"]

    async def _run_pd(app):
        return await fake_pd(app, 5007, device_address="2000:7")

    result = agent._run_bacnet_sync(_run_pd)
    assert len(result["objects"]) == 1
    assert calls == ["whois", "pd:5007:2000:7"]
