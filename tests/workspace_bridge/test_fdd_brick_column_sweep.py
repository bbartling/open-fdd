from __future__ import annotations

ZONE_RULE = """from open_fdd.arrow_runtime.cookbook import oob_mask

def apply_faults_arrow(table, cfg, context=None):
    return oob_mask(table, cfg)
"""


def test_fdd_runner_sweeps_all_brick_bound_columns(client, monkeypatch):
    from openfdd_bridge.feather_store import FeatherStore
    from openfdd_bridge.rule_store import RuleStore

    client.post(
        "/api/model/import",
        json={
            "payload": {
                "sites": [{"id": "s1", "name": "Sweep Site"}],
                "points": [
                    {
                        "id": f"dev-analog-input-{i}",
                        "site_id": "s1",
                        "brick_type": "Zone_Air_Temperature_Sensor",
                        "external_id": f"zone-{i}",
                    }
                    for i in (1, 2)
                ],
            },
            "replace": True,
        },
    )
    import pandas as pd

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=10, freq="5min", tz="UTC"),
            "site_id": ["s1"] * 10,
            "zone-1": [60.0] * 10,
            "zone-2": [90.0] * 10,
        }
    )
    FeatherStore().write_shard(df, source="bacnet", site_id="s1")
    RuleStore().upsert(
        {
            "id": "zone-oob-sweep",
            "name": "Zone OOB sweep",
            "enabled": True,
            "backend": "arrow",
            "code": ZONE_RULE,
            "fault_code": "VAV-C",
            "config": {
                "bounds_low": 65,
                "bounds_high": 78,
                "temp_unit": "imperial",
                "rolling_avg_minutes": 1,
            },
            "bindings": {"brick_types": ["Zone_Air_Temperature_Sensor"]},
        },
        saved_by="integrator",
    )
    from openfdd_bridge import fdd_runner

    summary = fdd_runner.run_batch(limit=100, persist=False, lookback_hours=0)
    run = next(r for r in summary["runs"] if r.get("rule_id") == "zone-oob-sweep")
    assert run["status"] == "ok"
    assert run.get("bound_columns", 0) >= 2
    assert run["flagged"] > 0
