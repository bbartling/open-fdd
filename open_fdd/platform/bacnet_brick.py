"""
BACnet → BRICK mapping for data model (object_type / object_identifier → brick_type).

Used when importing BACnet discovery into the data model so points get a sensible default
BRICK class. Can be extended later with bacpypes/Brick RDF or scanner_to_brick-style logic.
"""

from __future__ import annotations

# BACnet object type (or first part of object_identifier like "analog-input,3") → BRICK class
_OBJECT_TYPE_TO_BRICK: dict[str, str] = {
    "analog-input": "Sensor",
    "analog-output": "Sensor",
    "analog-value": "Sensor",
    "binary-input": "State",
    "binary-output": "State",
    "binary-value": "State",
    "multi-state-input": "State",
    "multi-state-output": "State",
    "multi-state-value": "State",
    "temperature-sensor": "Sensor",
    "co2-sensor": "Sensor",
    "humidity-sensor": "Sensor",
    "pressure-sensor": "Sensor",
    "flow-sensor": "Sensor",
    "occupancy-sensor": "Sensor",
    "light-level-sensor": "Sensor",
}


def object_type_to_brick(object_type: str | None) -> str | None:
    """
    Map BACnet object type to a default BRICK class.
    object_type can be e.g. "analog-input" or "analog-input,3" (object_identifier style).
    Returns None if unknown (caller can use "Point" or leave unset).
    """
    if not object_type or not isinstance(object_type, str):
        return None
    key = (object_type.split(",")[0] or "").strip().lower()
    return _OBJECT_TYPE_TO_BRICK.get(key)


def object_identifier_to_brick(object_identifier: str | None) -> str | None:
    """
    Extract object type from object_identifier (e.g. "analog-input,3") and map to BRICK.
    """
    return object_type_to_brick(object_identifier)
