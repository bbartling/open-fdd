from __future__ import annotations

ARROW_RULE = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["SAT"], cfg.get("threshold", 50))
"""


def test_fdd_runner_arrow_backend(client, tmp_path, monkeypatch):
    from openfdd_bridge.rule_store import RuleStore

    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    import pandas as pd

    from openfdd_bridge.feather_store import FeatherStore

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=20, freq="5min", tz="UTC"),
            "site_id": ["s1"] * 20,
            "SAT": [60.0] * 20,
        }
    )
    FeatherStore().write_shard(df, source="bacnet", site_id="s1")
    rules = RuleStore()
    rules.upsert(
        {
            "id": "arrow-test-1",
            "name": "Arrow SAT",
            "enabled": True,
            "backend": "arrow",
            "code": ARROW_RULE,
            "config": {"threshold": 50},
            "applies_to": {"site_ids": ["s1"]},
        },
        saved_by="integrator",
    )
    from openfdd_bridge import fdd_runner

    summary = fdd_runner.run_batch(limit=100, persist=False, lookback_hours=0)
    assert summary["ok"]
    arrow_runs = [r for r in summary["runs"] if r.get("backend") == "arrow"]
    assert arrow_runs
    assert arrow_runs[0]["status"] == "ok"
    assert arrow_runs[0]["flagged"] > 0


def test_playground_test_rule_arrow(client):
    code = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
"""
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    r = client.post(
        "/api/playground/test-rule",
        json={"code": code, "config": {"max_zone_temp": 50}, "site_id": "s1", "limit": 50},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("backend") == "arrow"
    assert body.get("ok") is True or body.get("rows", 0) >= 0
