from __future__ import annotations

from openfdd_bridge.root_cause_hints import build_root_cause_hints


def test_multi_zone_fault_hints_ahu():
    alerts = [
        {"code": "VAV-C", "title": "Zone temp flatline", "severity": "warning"},
        {"code": "VAV-C", "title": "Zone temp OOB", "severity": "warning"},
    ]
    zone_snapshot = {
        "struggling_zones": [{"label": "VAV-1"}, {"label": "VAV-2"}],
        "systems": [{"ahu_name": "AHU-1", "median_recovery_f_per_min": 0.02}],
        "research": {},
        "fan_schedule": {},
    }
    brick = {"feeds_chains": ["Chiller-1 → feeds → AHU-1", "AHU-1 → feeds → VAV-1"]}
    out = build_root_cause_hints(alerts, site_id="demo", zone_snapshot=zone_snapshot, brick_graph=brick)
    assert out["pattern"] == "multi_zone_fault"
    assert out["zone_fault_count"] == 2
    assert any("AHU-1" in h for h in out["hints"])


def test_no_hints_single_fault():
    out = build_root_cause_hints([{"code": "AHU-B", "title": "Fan fault"}], site_id="demo")
    assert out["hints"] == []
