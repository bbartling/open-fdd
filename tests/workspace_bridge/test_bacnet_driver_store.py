from __future__ import annotations

import csv
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
def driver_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    comm = tmp_path / "bacnet" / "commissioning"
    comm.mkdir(parents=True)
    (comm / "commission.env").write_text('site_id="test-site"\nbuilding_id="test-bldg"\n', encoding="utf-8")
    discovered = comm / "points_discovered.csv"
    points = comm / "points.csv"
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge import bacnet_driver_store as store  # noqa: E402

    yield store, discovered, points


def test_sync_discovery_and_tree(driver_tmp):
    store, discovered, points = driver_tmp
    res = store.sync_discovery(
        device_instance=5007,
        device_address="192.168.1.10",
        objects=[
            {"object_identifier": "analog-input,1", "name": "SAT"},
            {"object_identifier": "binary-value,2", "name": "Enable"},
        ],
    )
    assert res["rows_added"] == 2
    assert discovered.is_file()
    tree = store.driver_tree()
    assert len(tree["devices"]) == 1
    dev = tree["devices"][0]
    assert dev["device_instance"] == "5007"
    assert dev["point_count"] == 2
    assert dev["poll_count"] == 0
    assert not points.is_file() or points.stat().st_size == 0


def test_sync_discovery_persists_commandable(driver_tmp):
    store, discovered, _points = driver_tmp
    store.sync_discovery(
        device_instance=100,
        device_address="10.0.0.1",
        objects=[
            {"object_identifier": "analog-input,1", "name": "SAT", "commandable": False},
            {"object_identifier": "analog-value,2", "name": "Setpoint", "commandable": True},
        ],
    )
    with discovered.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_oid = {f"{r['object_type']},{r['object_instance']}": r for r in rows}
    assert by_oid["analog-input,1"]["commandable"] == "0"
    assert by_oid["analog-value,2"]["commandable"] == "1"
    tree = store.driver_tree()
    pts = {p["object_identifier"]: p for p in tree["devices"][0]["points"]}
    assert pts["analog-input,1"]["commandable"] is False
    assert pts["analog-value,2"]["commandable"] is True

    store.sync_discovery(
        device_instance=100,
        device_address="10.0.0.1",
        objects=[{"object_identifier": "analog-input,1", "name": "SAT", "commandable": True}],
        replace=True,
    )
    tree2 = store.driver_tree()
    ai = next(p for p in tree2["devices"][0]["points"] if p["object_identifier"] == "analog-input,1")
    assert ai["commandable"] is True


def test_driver_tree_pv_only_for_enabled_poll_points(driver_tmp):
    store, discovered, points = driver_tmp
    store.sync_discovery(
        device_instance=100,
        device_address="2000:7",
        objects=[
            {"object_identifier": "analog-input,1", "name": "Polled"},
            {"object_identifier": "analog-input,2", "name": "Idle"},
        ],
    )
    with discovered.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row["object_instance"] == "1":
            row["present_value"] = "72.5"
        if row["object_instance"] == "2":
            row["present_value"] = "68.0"
    with discovered.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    tree = store.driver_tree()
    polled = next(p for p in tree["devices"][0]["points"] if p["object_identifier"] == "analog-input,1")
    idle = next(p for p in tree["devices"][0]["points"] if p["object_identifier"] == "analog-input,2")
    assert polled["present_value"] == ""
    assert idle["present_value"] == ""
    store.set_point_poll(point_id=polled["point_id"], enabled=True, poll_interval_s=60)
    store.record_ondemand_present_value(
        device_instance=100,
        object_identifier="analog-input,1",
        present_value="73.1",
    )
    tree2 = store.driver_tree()
    polled2 = next(p for p in tree2["devices"][0]["points"] if p["object_identifier"] == "analog-input,1")
    idle2 = next(p for p in tree2["devices"][0]["points"] if p["object_identifier"] == "analog-input,2")
    assert polled2["present_value"] == "73.1"
    assert idle2["present_value"] == ""
    store.record_ondemand_present_value(
        device_instance=100,
        object_identifier="analog-input,2",
        present_value="69.2",
    )
    tree3 = store.driver_tree()
    idle3 = next(p for p in tree3["devices"][0]["points"] if p["object_identifier"] == "analog-input,2")
    assert idle3["present_value"] == "69.2"
    assert idle3["enabled"] is False


def test_set_point_poll_intervals(driver_tmp):
    store, _, points = driver_tmp
    store.sync_discovery(
        device_instance=100,
        device_address="10.0.0.1",
        objects=[{"object_identifier": "analog-value,1", "name": "Zone Temp"}],
    )
    tree = store.driver_tree()
    pid = tree["devices"][0]["points"][0]["point_id"]
    store.set_point_poll(point_id=pid, enabled=True, poll_interval_s=300)
    tree2 = store.driver_tree()
    pt = tree2["devices"][0]["points"][0]
    assert pt["enabled"] is True
    assert pt["poll_interval_s"] == 300
    assert pt["poll_label"] == "5 min"
    assert points.is_file()
    with points.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["enabled"] == "1"
    assert rows[0]["poll_interval_s"] == "300"

    with pytest.raises(ValueError, match="poll_interval_s"):
        store.set_point_poll(point_id=pid, enabled=True, poll_interval_s=120)


def test_remap_device_address_and_instance(driver_tmp):
    store, discovered, points = driver_tmp
    store.sync_discovery(
        device_instance=5007,
        device_address="192.168.1.10",
        objects=[{"object_identifier": "analog-input,1", "name": "SAT"}],
    )
    pid = store.driver_tree()["devices"][0]["points"][0]["point_id"]
    store.set_point_poll(point_id=pid, enabled=True, poll_interval_s=60)
    store.remap_device(device_instance=5007, new_device_instance=5008, new_device_address="2000:7")
    tree = store.driver_tree()
    assert len(tree["devices"]) == 1
    dev = tree["devices"][0]
    assert dev["device_instance"] == "5008"
    assert dev["device_address"] == "2000:7"
    assert dev["points"][0]["point_id"] == "5008-analog-input-1"
    with points.open(newline="", encoding="utf-8") as fh:
        poll = list(csv.DictReader(fh))
    assert poll[0]["point_id"] == "5008-analog-input-1"


def test_delete_point_and_device(driver_tmp):
    store, discovered, points = driver_tmp
    store.sync_discovery(
        device_instance=200,
        device_address="10.0.0.2",
        objects=[
            {"object_identifier": "analog-input,1", "name": "A"},
            {"object_identifier": "analog-input,2", "name": "B"},
        ],
    )
    tree = store.driver_tree()
    pid = tree["devices"][0]["points"][0]["point_id"]
    store.set_point_poll(point_id=pid, enabled=True, poll_interval_s=60)
    store.delete_point(point_id=pid)
    tree2 = store.driver_tree()
    assert len(tree2["devices"][0]["points"]) == 1
    assert points.is_file()
    with points.open(newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 0

    store.delete_device(device_instance=200)
    assert store.driver_tree()["devices"] == []
    with discovered.open(newline="", encoding="utf-8") as fh:
        assert list(csv.DictReader(fh)) == []


def test_tree_rebuilt_from_poll_csv_when_discovered_missing(driver_tmp):
    """Deploy may push points.csv without points_discovered.csv — tree must still populate."""
    store, discovered, points = driver_tmp
    assert not discovered.is_file()
    points.write_text(
        "point_id,device_instance,device_address,object_type,object_instance,object_name,enabled,poll_interval_s,series_id\n"
        "5007-analog-input-1,5007,192.168.1.10,analog-input,1,Zone Temp,1,60,5007-analog-input-1\n"
        "5007-analog-input-2,5007,192.168.1.10,analog-input,2,SAT,1,300,5007-analog-input-2\n",
        encoding="utf-8",
    )
    tree = store.driver_tree()
    assert tree["inventory_source"] in ("discovered", "poll_csv")
    assert len(tree["devices"]) == 1
    assert tree["devices"][0]["point_count"] == 2
    assert tree["devices"][0]["poll_count"] == 2
    assert discovered.is_file()
    with discovered.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2


def test_clear_registry_syncs_model(driver_tmp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store, discovered, points = driver_tmp
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "model.json").write_text(
        '{"sites":[{"id":"test-site","name":"Test"}],"equipment":[],"points":[]}',
        encoding="utf-8",
    )
    store.sync_discovery(
        device_instance=5007,
        device_address="192.168.1.10",
        objects=[
            {"object_identifier": "analog-input,1", "name": "SAT"},
            {"object_identifier": "analog-input,2", "name": "RAT"},
        ],
    )
    pid = store.driver_tree()["devices"][0]["points"][0]["point_id"]
    store.set_point_poll(point_id=pid, enabled=True, poll_interval_s=60)
    from openfdd_bridge.bacnet_poll_model_sync import sync_enabled_polling_to_model  # noqa: E402

    sync_enabled_polling_to_model(sync_ttl=False)
    res = store.clear_registry(sync_model=True, sync_ttl=False)
    assert res["ok"] is True
    assert store.driver_tree()["devices"] == []
    with discovered.open(newline="", encoding="utf-8") as fh:
        assert list(csv.DictReader(fh)) == []
    with points.open(newline="", encoding="utf-8") as fh:
        assert list(csv.DictReader(fh)) == []
    model = __import__("json").loads((data / "model.json").read_text(encoding="utf-8"))
    assert model["equipment"] == []
    assert model["points"] == []
    assert len(model["sites"]) == 1
