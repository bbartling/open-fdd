"""BACnet override registry persistence and dashboard alerts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def registry_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import bacnet_toolshed.override_registry as reg

    overrides = tmp_path / "overrides"
    overrides.mkdir(parents=True)
    monkeypatch.setattr(reg, "overrides_dir", lambda: overrides)
    monkeypatch.setattr(reg, "_registry_path", lambda: overrides / "registry.json")
    monkeypatch.setattr(reg, "_export_path", lambda: overrides / "overrides_export.csv")
    monkeypatch.setenv("OFDD_OPERATOR_OVERRIDE_PRIORITY", "8")
    return reg


def test_save_device_scan_and_export(registry_tmp, monkeypatch: pytest.MonkeyPatch):
    reg = registry_tmp
    monkeypatch.setattr(reg, "list_devices_for_scan", lambda: [{"device_instance": 5007, "device_address": "2000:7"}])
    reg.save_device_scan(
        {
            "device_id": 5007,
            "address": "2000:7",
            "summary": {"points_with_override_count": 1},
            "points_with_overrides": [
                {
                    "object_identifier": "analog-input,1168",
                    "object_name": "OA-H",
                    "override_priority_levels": [8, 12],
                    "overrides": [
                        {"priority_level": 8, "type": "real", "value": 72.5},
                        {"priority_level": 12, "type": "real", "value": 1.0},
                    ],
                }
            ],
        }
    )
    st = reg.scan_status()
    assert st["operator_override_points"] == 1
    assert st["total_override_points"] == 1
    csv_text = reg.export_csv_text()
    assert "analog-input,1168" in csv_text
    assert ",8," in csv_text
    alerts = reg.override_alerts(operator_only=True)
    assert len(alerts) == 1
    assert "P8" in alerts[0]["title"]
    assert "72.5" in alerts[0]["title"]
    all_alerts = reg.override_alerts(operator_only=False)
    assert len(all_alerts) == 2
    llm = reg.slim_overrides_for_llm()
    assert llm["override_count"] == 2


def test_advance_cursor_rotates(registry_tmp):
    reg = registry_tmp
    data = reg._empty_registry()
    data["cursor"] = 0
    reg._save_registry(data)
    nxt = reg.advance_cursor(3)
    assert nxt == 1
    loaded = reg.load_registry()
    assert loaded["cursor"] == 1
