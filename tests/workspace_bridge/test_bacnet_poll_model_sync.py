from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def model_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data = tmp_path / "data"
    comm = tmp_path / "bacnet" / "commissioning"
    comm.mkdir(parents=True)
    data.mkdir()
    (comm / "commission.env").write_text('site_id="demo"\nbuilding_id="local"\n', encoding="utf-8")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    yield data, comm


def test_sync_polling_auto_site(model_env, monkeypatch: pytest.MonkeyPatch):
    data, comm = model_env
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_ID", "demo")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.bacnet_poll_model_sync import sync_enabled_polling_to_model  # noqa: E402

    (comm / "points_discovered.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,description,"
        "present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,"
        "poll_interval_s,point_id,series_id\n"
        "5007,2000:7,analog-input,1,SAT,SAT,,,demo,local,bacnet,,,0,60,"
        "5007-analog-input-1,demo#local#bacnet#5007-analog-input-1\n",
        encoding="utf-8",
    )
    (comm / "points.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,description,"
        "present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,"
        "poll_interval_s,point_id,series_id\n"
        "5007,2000:7,analog-input,1,SAT,SAT,,,demo,local,bacnet,,,1,60,"
        "5007-analog-input-1,demo#local#bacnet#5007-analog-input-1\n",
        encoding="utf-8",
    )
    res = sync_enabled_polling_to_model(sync_ttl=True)
    assert res["points_added"] == 1
    assert (data / "data_model.ttl").is_file()
    ttl = (data / "data_model.ttl").read_text(encoding="utf-8")
    assert "ofdd:externalReference" in ttl
    assert "feather://bacnet/demo/" in ttl


def test_duplicate_device_blocked(model_env):
    _, comm = model_env
    from openfdd_bridge import bacnet_driver_store as store  # noqa: E402

    objs = [{"object_identifier": "analog-input,1", "name": "SAT"}]
    store.sync_discovery(device_instance=5007, device_address="2000:7", objects=objs, replace=True)
    with pytest.raises(ValueError, match="already in the driver"):
        store.sync_discovery(device_instance=5007, device_address="2000:7", objects=objs, replace=False)


def test_clear_bacnet_from_model(model_env):
    data, comm = model_env
    from openfdd_bridge.bacnet_poll_model_sync import (  # noqa: E402
        clear_bacnet_from_model,
        remove_device_from_model,
        sync_enabled_polling_to_model,
    )

    (data / "model.json").write_text(
        '{"sites":[{"id":"demo","name":"Demo"}],"equipment":[{"id":"manual-1","name":"Chiller"}],'
        '"points":[{"id":"manual-pt","equipment_id":"manual-1","description":"Manual"}]}',
        encoding="utf-8",
    )
    (comm / "points_discovered.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,description,"
        "present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,"
        "poll_interval_s,point_id,series_id\n"
        "5007,2000:7,analog-input,1,SAT,SAT,,,demo,local,bacnet,,,0,60,"
        "5007-analog-input-1,demo#local#bacnet#5007-analog-input-1\n"
        "5008,2000:8,analog-input,1,OAT,OAT,,,demo,local,bacnet,,,0,60,"
        "5008-analog-input-1,demo#local#bacnet#5008-analog-input-1\n",
        encoding="utf-8",
    )
    (comm / "points.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,description,"
        "present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,"
        "poll_interval_s,point_id,series_id\n"
        "5007,2000:7,analog-input,1,SAT,SAT,,,demo,local,bacnet,,,1,60,"
        "5007-analog-input-1,demo#local#bacnet#5007-analog-input-1\n"
        "5008,2000:8,analog-input,1,OAT,OAT,,,demo,local,bacnet,,,1,60,"
        "5008-analog-input-1,demo#local#bacnet#5008-analog-input-1\n",
        encoding="utf-8",
    )
    sync_enabled_polling_to_model(sync_ttl=False)
    res = remove_device_from_model(device_instance=5008, sync_ttl=False)
    assert res["equipment_removed"] == 1
    assert res["points_removed"] == 1

    clear = clear_bacnet_from_model(sync_ttl=True)
    assert clear["equipment_removed"] == 1
    assert clear["points_removed"] == 1
    assert (data / "data_model.ttl").is_file()
    model = __import__("json").loads((data / "model.json").read_text(encoding="utf-8"))
    assert len(model["equipment"]) == 1
    assert model["equipment"][0]["id"] == "manual-1"
    assert len(model["points"]) == 1
    assert model["points"][0]["id"] == "manual-pt"


def test_sync_removes_stale_enabled_points(model_env):
    data, comm = model_env
    from openfdd_bridge.bacnet_poll_model_sync import sync_enabled_polling_to_model  # noqa: E402

    (data / "model.json").write_text(
        '{"sites":[{"id":"demo","name":"Demo"}],"equipment":[{"id":"bacnet-5007","equipment_type":"BACnet_Device"}],'
        '"points":[{"id":"5007-analog-input-1","equipment_id":"bacnet-5007","bacnet_device_id":5007,'
        '"object_identifier":"analog-input,1","description":"SAT"},'
        '{"id":"5007-analog-input-2","equipment_id":"bacnet-5007","bacnet_device_id":5007,'
        '"object_identifier":"analog-input,2","description":"RAT"}]}',
        encoding="utf-8",
    )
    header = (
        "device_instance,device_address,object_type,object_instance,object_name,description,"
        "present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,"
        "poll_interval_s,point_id,series_id\n"
    )
    (comm / "points_discovered.csv").write_text(
        header
        + "5007,2000:7,analog-input,1,SAT,SAT,,,demo,local,bacnet,,,0,60,"
        "5007-analog-input-1,demo#local#bacnet#5007-analog-input-1\n",
        encoding="utf-8",
    )
    (comm / "points.csv").write_text(
        header
        + "5007,2000:7,analog-input,1,SAT,SAT,,,demo,local,bacnet,,,1,60,"
        "5007-analog-input-1,demo#local#bacnet#5007-analog-input-1\n",
        encoding="utf-8",
    )
    res = sync_enabled_polling_to_model(sync_ttl=False)
    assert res["points_removed"] == 1
    model = __import__("json").loads((data / "model.json").read_text(encoding="utf-8"))
    assert len(model["points"]) == 1
    assert model["points"][0]["object_identifier"] == "analog-input,1"
