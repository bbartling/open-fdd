"""Discovered inventory dedupe and model duplicate BACnet equipment checks."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_acme_backup_no_duplicate_bacnet_equipment_instances():
    model_path = REPO / "workspace/data/acme_gl36_model.json"
    if not model_path.is_file():
        pytest.skip("acme_gl36_model.json missing")
    from openfdd_bridge.bacnet_poll_model_sync import duplicate_bacnet_equipment_report

    model = json.loads(model_path.read_text(encoding="utf-8"))
    report = duplicate_bacnet_equipment_report(model)
    assert report["duplicate_device_instances"] == 0


def test_dedupe_discovered_rows_prefers_canonical_point_id():
    from openfdd_bridge import bacnet_driver_store as store

    rows = [
        {
            "device_instance": "39",
            "object_type": "analog-input",
            "object_instance": "1019",
            "point_id": "39-unknown-1019",
        },
        {
            "device_instance": "39",
            "object_type": "analog-input",
            "object_instance": "1019",
            "point_id": "39-analog-input-1019",
        },
    ]
    out = store._dedupe_discovered_rows(rows)
    assert len(out) == 1
    assert out[0]["point_id"] == "39-analog-input-1019"


def test_driver_tree_device_count_matches_poll_csv():
    acme = REPO / "edge_backup/local/acme/vm-bbartling"
    if not (acme / "points.csv").is_file():
        pytest.skip("acme backup missing")
    tmp = Path(tempfile.mkdtemp())
    ws = tmp / "workspace"
    comm = ws / "bacnet" / "commissioning"
    comm.mkdir(parents=True)
    for name in ("points.csv", "points_discovered.csv", "commission.env"):
        src = acme / name
        if src.is_file():
            (comm / name).write_bytes(src.read_bytes())
    if not (comm / "commission.env").is_file():
        (comm / "commission.env").write_text('site_id="acme"\nbuilding_id="vm-bbartling"\n', encoding="utf-8")

    os.environ["OPENFDD_REPO_ROOT"] = str(REPO)
    os.environ["OPENFDD_WORKSPACE_DIR"] = str(ws)
    os.environ["OFDD_DESKTOP_DATA_DIR"] = str(tmp / "data")
    (tmp / "data").mkdir()

    for name in list(sys.modules):
        if name.startswith("openfdd_bridge"):
            del sys.modules[name]

    poll_rows = list(csv.DictReader((acme / "points.csv").open()))
    poll_devs = {str(r.get("device_instance")) for r in poll_rows if r.get("device_instance")}

    from openfdd_bridge.bacnet_driver_store import driver_tree

    tree = driver_tree()
    assert len(tree["devices"]) == len(poll_devs)


def test_model_health_flags_duplicate_bacnet_equipment():
    from openfdd_bridge.bacnet_poll_model_sync import duplicate_bacnet_equipment_report
    from openfdd_bridge.model_health import model_health_summary

    model = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [
            {"id": "acme-vav-39", "site_id": "acme", "bacnet_device_instance": 39},
            {"id": "bacnet-39", "site_id": "acme", "bacnet_device_id": 39, "equipment_type": "BACnet_Device"},
        ],
        "points": [],
    }
    assert duplicate_bacnet_equipment_report(model)["duplicate_device_instances"] == 1
    health = model_health_summary(model)
    assert health["counts"]["duplicate_bacnet_device_instances"] == 1
    assert any("multiple equipment rows" in i["title"] for i in health["issues"])
