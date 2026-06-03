from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture
def batch_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    model = json.loads((REPO / "workspace/data/bench_import_model.json").read_text(encoding="utf-8"))
    (data / "model.json").write_text(json.dumps(model), encoding="utf-8")
    rules = {
        "rules": [
            {
                "id": "rule-a",
                "name": "A",
                "enabled": True,
                "code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n",
                "config": {},
                "bindings": {"point_ids": ["5007-analog-input-1173"], "equipment_ids": [], "brick_types": []},
            },
            {
                "id": "rule-b",
                "name": "B",
                "enabled": True,
                "code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n",
                "config": {},
                "bindings": {"point_ids": ["5007-analog-input-10014"], "equipment_ids": [], "brick_types": []},
            },
        ]
    }
    (data / "rules_store.json").write_text(json.dumps(rules), encoding="utf-8")

    from openfdd_bridge.feather_store import FeatherStore  # noqa: E402

    ts = pd.date_range("2026-01-01", periods=24, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "oa-t": [70.0] * len(ts),
            "stat_zn-t": [68.0] * len(ts),
            "unused-wide": [1.0] * len(ts),
        }
    )
    store = FeatherStore(root=data / "feather_store")
    store.write_shard(df, source="bacnet", site_id="demo")
    store.compact(source="bacnet", site_id="demo")
    yield data


def test_run_batch_loads_feather_once_per_site(batch_env: Path):
    loads: list[str] = []
    real = __import__("openfdd_bridge.data_loader", fromlist=["load_frame_for_run"]).load_frame_for_run

    def _track(site_id: str | None = None, **kwargs):
        loads.append(str(site_id))
        return real(site_id, **kwargs)

    with patch("openfdd_bridge.fdd_runner.load_frame_for_run", side_effect=_track):
        from openfdd_bridge.fdd_runner import run_batch  # noqa: E402

        result = run_batch(persist=False, lookback_hours=1)
    assert result["site_runs"] == 2
    assert loads.count("demo") == 1
