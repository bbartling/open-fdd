"""Real-time event bus and WebSocket for HA/Node-RED integration."""

from open_fdd.platform.realtime.events import (
    TOPIC_CRUD_SITE,
    TOPIC_CRUD_EQUIPMENT,
    TOPIC_CRUD_POINT,
    TOPIC_CONFIG_UPDATED,
    TOPIC_GRAPH_UPDATED,
    TOPIC_BACNET_DISCOVERY,
    TOPIC_FDD_RUN,
    TOPIC_FAULT_RAISED,
    TOPIC_FAULT_CLEARED,
    TOPIC_BACNET_WRITE,
    emit,
)
from open_fdd.platform.realtime.hub import get_hub

__all__ = [
    "get_hub",
    "emit",
    "TOPIC_CRUD_SITE",
    "TOPIC_CRUD_EQUIPMENT",
    "TOPIC_CRUD_POINT",
    "TOPIC_CONFIG_UPDATED",
    "TOPIC_GRAPH_UPDATED",
    "TOPIC_BACNET_DISCOVERY",
    "TOPIC_FDD_RUN",
    "TOPIC_FAULT_RAISED",
    "TOPIC_FAULT_CLEARED",
    "TOPIC_BACNET_WRITE",
]
