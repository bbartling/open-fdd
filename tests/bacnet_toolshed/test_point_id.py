"""BACnet point_id slugging — regression for BACpypes3 ObjectType enums."""

from __future__ import annotations

from bacpypes3.primitivedata import ObjectIdentifier

from bacnet_toolshed.point_id import make_point_id


def test_make_point_id_from_object_type_enum() -> None:
    oid = ObjectIdentifier("analog-input:1168")
    assert make_point_id(5007, oid[0], oid[1]) == "5007-analog-input-1168"
    assert make_point_id(5007, str(oid[0]), oid[1]) == "5007-analog-input-1168"


def test_make_point_id_analog_output_enum() -> None:
    oid = ObjectIdentifier("analog-output:2466")
    assert make_point_id(5007, oid[0], oid[1]) == "5007-analog-output-2466"
