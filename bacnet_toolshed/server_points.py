"""Hard-coded Open-FDD BACnet server points (edge head-end identity)."""

from __future__ import annotations

import logging
from typing import Any

from bacpypes3.app import Application
from bacpypes3.basetypes import EngineeringUnits
from bacpypes3.local.analog import AnalogValueObject
from bacpypes3.local.binary import BinaryValueObject
from bacpypes3.primitivedata import Real

logger = logging.getLogger(__name__)

# Open-FDD edge device exposes these local objects on the same BACpypes3 Application
# used for commissioning (instance/name from commission.env — default OpenFddEdge/599999).
OPENFDD_SERVER_POINT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "openfdd-edge-online",
        "kind": "binaryValue",
        "instance": 9001,
        "present_value": "active",
        "description": "Open-FDD edge bridge online",
    },
    {
        "name": "openfdd-commission-agent",
        "kind": "binaryValue",
        "instance": 9002,
        "present_value": "active",
        "description": "BACnet commission agent reachable",
    },
    {
        "name": "openfdd-poll-sample-count",
        "kind": "analogValue",
        "instance": 9001,
        "present_value": 0.0,
        "units": EngineeringUnits.noUnits,
        "description": "Rows in latest BACnet poll CSV",
    },
    {
        "name": "openfdd-devices-discovered",
        "kind": "analogValue",
        "instance": 9002,
        "present_value": 0.0,
        "units": EngineeringUnits.noUnits,
        "description": "Unique devices in points_discovered.csv",
    },
)

point_map: dict[str, Any] = {}
_installed = False


def _binary_present(value: str | bool) -> str:
    if isinstance(value, bool):
        return "active" if value else "inactive"
    text = str(value).strip().lower()
    return "active" if text in {"active", "true", "1", "on", "yes"} else "inactive"


def install_openfdd_server_points(app: Application) -> dict[str, str]:
    """Register Open-FDD local BACnet objects once per Application."""
    global _installed
    if _installed and point_map:
        return {name: str(obj.objectIdentifier) for name, obj in point_map.items()}

    point_map.clear()
    for spec in OPENFDD_SERVER_POINT_SPECS:
        name = spec["name"]
        kind = spec["kind"]
        instance = int(spec["instance"])
        if kind == "binaryValue":
            obj = BinaryValueObject(
                objectIdentifier=("binaryValue", instance),
                objectName=name,
                presentValue=_binary_present(spec.get("present_value", "inactive")),
                statusFlags=[0, 0, 0, 0],
                eventState="normal",
                outOfService=False,
                polarity="normal",
                description=str(spec.get("description", "")),
            )
        elif kind == "analogValue":
            obj = AnalogValueObject(
                objectIdentifier=("analogValue", instance),
                objectName=name,
                presentValue=Real(float(spec.get("present_value", 0.0))),
                statusFlags=[0, 0, 0, 0],
                eventState="normal",
                outOfService=False,
                units=spec.get("units", EngineeringUnits.noUnits),
                description=str(spec.get("description", "")),
            )
        else:
            logger.warning("Unsupported Open-FDD server point kind: %s", kind)
            continue
        app.add_object(obj)
        point_map[name] = obj
        logger.info("Open-FDD server point %s @ %s", name, obj.objectIdentifier)

    _installed = True
    return {name: str(obj.objectIdentifier) for name, obj in point_map.items()}


def update_openfdd_server_points(
    *,
    poll_rows: int | None = None,
    devices_discovered: int | None = None,
    commission_ok: bool | None = None,
    bridge_ok: bool | None = None,
) -> None:
    """Refresh present values for hosted Open-FDD status points."""
    if "openfdd-poll-sample-count" in point_map and poll_rows is not None:
        point_map["openfdd-poll-sample-count"].presentValue = Real(float(poll_rows))
    if "openfdd-devices-discovered" in point_map and devices_discovered is not None:
        point_map["openfdd-devices-discovered"].presentValue = Real(float(devices_discovered))
    if "openfdd-commission-agent" in point_map and commission_ok is not None:
        point_map["openfdd-commission-agent"].presentValue = _binary_present(commission_ok)
    if "openfdd-edge-online" in point_map and bridge_ok is not None:
        point_map["openfdd-edge-online"].presentValue = _binary_present(bridge_ok)


def server_points_snapshot() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, obj in point_map.items():
        pv = getattr(obj, "presentValue", None)
        out.append(
            {
                "name": name,
                "object_identifier": str(obj.objectIdentifier),
                "present_value": str(pv) if pv is not None else None,
                "commandable": False,
            }
        )
    return out
