"""Open-FDD hosted BACnet server point helpers."""

from __future__ import annotations

from bacnet_toolshed.server_points import (
    OPENFDD_SERVER_POINT_SPECS,
    server_points_snapshot,
    update_openfdd_server_points,
)


class _FakePoint:
    def __init__(self, oid: tuple[str, int], present: object):
        self.objectIdentifier = oid
        self.presentValue = present


def test_openfdd_server_point_specs():
    names = {spec["name"] for spec in OPENFDD_SERVER_POINT_SPECS}
    assert "openfdd-edge-online" in names
    assert "openfdd-poll-sample-count" in names
    assert "openfdd-active-fault-count" in names
    assert len(OPENFDD_SERVER_POINT_SPECS) >= 5


def test_binary_server_point_uses_bacpypes3_enums():
    from bacpypes3.basetypes import BinaryPV
    from bacpypes3.local.binary import BinaryValueObject

    obj = BinaryValueObject(
        objectIdentifier=("binaryValue", 9001),
        objectName="openfdd-edge-online",
        presentValue=BinaryPV.active,
        description="Open-FDD edge bridge online",
    )
    assert obj.objectName == "openfdd-edge-online"


def test_update_and_snapshot_server_points():
    from bacnet_toolshed import server_points

    server_points.point_map.clear()
    server_points._installed = False
    poll = _FakePoint(("analogValue", 9001), 0.0)
    online = _FakePoint(("binaryValue", 9001), "inactive")
    server_points.point_map["openfdd-poll-sample-count"] = poll
    server_points.point_map["openfdd-edge-online"] = online

    update_openfdd_server_points(poll_rows=128, bridge_ok=True)
    snap = server_points_snapshot()
    assert len(snap) == 2
    poll_row = next(r for r in snap if r["name"] == "openfdd-poll-sample-count")
    assert "9001" in poll_row["object_identifier"]
    online_row = next(r for r in snap if r["name"] == "openfdd-edge-online")
    assert online_row["present_value"] == "active"

    server_points.point_map.clear()
    server_points._installed = False
