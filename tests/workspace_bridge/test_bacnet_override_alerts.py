"""Building status includes operator BACnet override alerts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_collect_status_includes_override_alerts(monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge import building_status

    monkeypatch.setattr(
        building_status,
        "bacnet_override_alerts",
        lambda operator_only=False: [
            {
                "id": "bacnet-override-5007-test",
                "severity": "warning",
                "title": "OVERRIDE device 5007 OA-H @ P8 = 72.5",
                "detail": "operator manual",
                "source": "bacnet_override",
            }
        ]
        if operator_only
        else [],
    )
    monkeypatch.setattr(building_status, "load_alerts", lambda: {"alerts": [], "status": "ok"})
    monkeypatch.setattr(building_status, "merge_auto_issues", lambda **kw: {"alerts": [], "status": "ok"})
    monkeypatch.setattr(building_status, "fdd_issues", lambda: [])
    monkeypatch.setattr(building_status, "model_health_summary", lambda m: {"configured": False})
    monkeypatch.setattr(building_status, "ModelService", lambda: type("M", (), {"load": lambda self: {}})())
    monkeypatch.setattr(building_status, "get_device_poll_snapshot", lambda force=False: {})
    monkeypatch.setattr(building_status, "poll_health_alerts", lambda snap: [])
    monkeypatch.setattr(building_status, "stack_health", lambda: {})

    status = building_status.collect_status()
    sources = [a.get("source") for a in status.get("alerts") or []]
    assert "bacnet_override" in sources
