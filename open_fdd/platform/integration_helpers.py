"""
Helpers for HA/Node-RED integration: topic filtering, type coercion, entity id validation.
Mirrors patterns from node-red-contrib-home-assistant-websocket for robustness.
"""

import fnmatch
import re
from typing import Any


def topic_matches(subscription: str, topic: str) -> bool:
    """True if topic matches subscription pattern (subscription may contain *)."""
    if not subscription or not topic:
        return False
    return fnmatch.fnmatch(topic, subscription)


def should_include(
    target: str,
    include_pattern: str | None,
    exclude_pattern: str | None,
) -> bool:
    """
    Include if target matches include_pattern (or include is None) and does not match exclude_pattern.
    Patterns are fnmatch style (e.g. fault.*, crud.point.*).
    """
    if not target and not include_pattern:
        return True
    if exclude_pattern and fnmatch.fnmatch(target, exclude_pattern):
        return False
    if include_pattern is None:
        return True
    return fnmatch.fnmatch(target, include_pattern)


def parse_value_to_boolean(value: Any) -> bool:
    """
    Parse common values to bool (HA/Node-RED style).
    True: True, 1, "true", "1", "yes", "on". False: False, 0, "false", "0", "no", "", None.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "on", "y", "open", "home"):
            return True
        if s in ("false", "0", "no", "off", "n", ""):
            return False
        try:
            return int(s) != 0
        except ValueError:
            return False
    return bool(value)


# HA entity_id format: domain.entity_name (e.g. binary_sensor.openfdd_ahu1_occupied)
_ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_]*$")


def valid_entity_id(entity_id: str) -> bool:
    """True if string looks like a valid HA entity_id (domain.entity_name)."""
    if not entity_id or not isinstance(entity_id, str):
        return False
    return bool(_ENTITY_ID_RE.match(entity_id))


def valid_suggested_ha_id(suggested_id: str) -> bool:
    """True if string is a valid suggested Open-FDD HA id (e.g. openfdd_ahu1_occupied)."""
    if not suggested_id or len(suggested_id) > 64:
        return False
    return bool(re.match(r"^[a-z][a-z0-9_]*$", suggested_id))
