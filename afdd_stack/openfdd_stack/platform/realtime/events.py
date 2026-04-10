"""Event topic constants and broadcast helper."""

from datetime import datetime, timezone
from typing import Any, Optional

# Topic name prefixes (use * for wildcard in subscribe)
TOPIC_CRUD_SITE = "crud.site"
TOPIC_CRUD_EQUIPMENT = "crud.equipment"
TOPIC_CRUD_POINT = "crud.point"
TOPIC_CRUD_ENERGY_CALC = "crud.energy_calc"
TOPIC_CONFIG_UPDATED = "config.updated"
TOPIC_GRAPH_UPDATED = "graph.updated"
TOPIC_BACNET_DISCOVERY = "bacnet.discovery"
TOPIC_BACNET_WRITE = "bacnet.write"
TOPIC_FDD_RUN = "fdd.run"
TOPIC_FAULT_RAISED = "fault.raised"
TOPIC_FAULT_CLEARED = "fault.cleared"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(
    topic: str, data: dict[str, Any], correlation_id: Optional[str] = None
) -> None:
    """Broadcast event to WebSocket clients subscribed to topic (or wildcard)."""
    from openfdd_stack.platform.realtime.hub import get_hub

    payload = {
        "type": "event",
        "topic": topic,
        "ts": _ts(),
        "correlation_id": correlation_id,
        "data": data,
    }
    get_hub().broadcast(payload)
