from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.device_poll_health import compute_device_poll_health  # noqa: E402


def test_dedupe_equipment_by_bacnet_device():
    model = {
        "sites": [{"id": "s1"}],
        "equipment": [
            {"id": "vav-a", "site_id": "s1", "name": "Trane Vav 12035", "bacnet_device_id": 12035},
            {"id": "vav-b", "site_id": "s1", "name": "Trane Vav 12035 Zone", "bacnet_device_id": 12035},
            {"id": "vav-c", "site_id": "s1", "name": "VAV-3", "bacnet_device_id": 12036},
        ],
        "points": [
            {"id": "p1", "site_id": "s1", "equipment_id": "vav-a", "external_id": "zn-a", "brick_type": "Zone_Air_Temperature_Sensor"},
            {"id": "p2", "site_id": "s1", "equipment_id": "vav-b", "external_id": "flow-a", "brick_type": "Air_Flow_Sensor"},
            {"id": "p3", "site_id": "s1", "equipment_id": "vav-c", "external_id": "zn-c", "brick_type": "Zone_Air_Temperature_Sensor"},
        ],
    }
    end = pd.Timestamp.now(tz="UTC")
    ts = pd.date_range(end=end, periods=60, freq="5min")
    fresh = [72.0 + (i % 3) * 0.1 for i in range(60)]
    df = pd.DataFrame({"timestamp": ts, "zn-a": fresh, "flow-a": fresh, "zn-c": fresh})
    snap = compute_device_poll_health(
        model,
        "s1",
        df,
        poll_csv_fresh_override=False,
        live_poll_age_s_override=999_999.0,
    )
    assert snap["equipment_row_count"] == 3
    assert snap["physical_device_count"] == 2
    assert len(snap["equipment"]) == 2


def test_fdd_issues_use_equipment_names(monkeypatch, tmp_path):
    from openfdd_bridge import fdd_results as fr

    model = {
        "equipment": [{"id": "vav1", "site_id": "acme", "name": "Trane Vav 12035"}],
        "points": [
            {
                "id": "12035-analog-input-1",
                "site_id": "acme",
                "equipment_id": "vav1",
                "external_id": "stat_zn-t",
                "brick_type": "Zone_Air_Temperature_Sensor",
            }
        ],
    }
    monkeypatch.setattr(fr, "_model_for_fdd", lambda: model)
    monkeypatch.setattr(fr, "load_results", lambda: {
        "runs": [
            {
                "rule_id": "acme-zn-t-flatline-1h",
                "rule_name": "Zone temp flatline 1h",
                "site_id": "acme",
                "status": "ok",
                "flagged": 3,
                "rows": 100,
                "fault_code": "VAV-C",
                "equipment_family": "VAV-C",
                "analytics": {"flagged_columns": ["stat_zn-t"]},
            }
        ]
    })
    issues = fr.fdd_issues()
    assert issues
    assert "Trane Vav 12035" in issues[0]["title"]
    assert issues[0].get("equipment_name") == "Trane Vav 12035"
