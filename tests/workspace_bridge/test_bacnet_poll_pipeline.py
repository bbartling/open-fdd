from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_ingest_long_poll_to_feather(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data = tmp_path / "data"
    ws = tmp_path / "workspace"
    comm = ws / "bacnet" / "commissioning"
    polls = ws / "bacnet" / "polls"
    comm.mkdir(parents=True)
    polls.mkdir(parents=True)
    data.mkdir(parents=True, exist_ok=True)
    (data / "model.json").write_text(
        '{"sites":[{"id":"local","name":"Local"}],"equipment":[],"points":'
        '[{"id":"5007-analog-input-1168","point_id":"5007-analog-input-1168","external_id":"oa-h","site_id":"local"}]}',
        encoding="utf-8",
    )
    (comm / "points_discovered.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,point_id\n"
        "5007,2000:7,analog-input,1168,OA-H,5007-analog-input-1168\n",
        encoding="utf-8",
    )
    (polls / "samples.csv").write_text(
        "timestamp_utc,site_id,building_id,system_id,point_id,series_id,device_instance,object_type,object_instance,value,units\n"
        "2026-01-01T12:00:00+00:00,local,local,bacnet,5007-analog-input-1168,s1,5007,analog-input,1168,72.5,degF\n"
        "2026-01-01T12:01:00+00:00,local,local,bacnet,5007-analog-input-1168,s1,5007,analog-input,1168,73.1,degF\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_ID", "local")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.bacnet_poll_ingest import ingest_poll_samples_to_feather  # noqa: E402
    from openfdd_bridge.feather_store import FeatherStore  # noqa: E402

    res = ingest_poll_samples_to_feather()
    assert res["ok"] is True
    assert "local" in res["sites"]
    df = FeatherStore().read_site("local", source="bacnet")
    assert df is not None
    assert "oa-h" in df.columns
    assert len(df) == 2


def test_bacnet_poll_loop_interval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws = tmp_path / "workspace"
    comm = ws / "bacnet" / "commissioning"
    comm.mkdir(parents=True)
    (comm / "points.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,enabled,poll_interval_s,point_id,site_id,building_id,system_id\n"
        "5007,2000:7,analog-input,1,SAT,1,60,5007-analog-input-1,demo,local,bacnet\n"
        "5007,2000:7,analog-input,2,RAT,1,300,5007-analog-input-2,demo,local,bacnet\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    from bacnet_toolshed.bacnet_poll_loop import enabled_point_count, poll_interval_s  # noqa: E402

    assert enabled_point_count() == 2
    assert poll_interval_s() == 60.0
