"""VOLTTRON ↔ Open-F-DD bridge (topic parsing, scrape flattening, Brick point catalog).

This package is the **first concrete slice** of the VOLTTRON-first retrofit: agents or ETL
jobs can map **platform driver** style publishes into **Open-F-DD** ``external_id`` keys
without going through the HTTP CRUD path. The monorepo **FastAPI** stack remains until
feature parity exists here and in deployment agents.
"""

from openfdd_stack.volttron_bridge.catalog import list_points_for_volttron_device
from openfdd_stack.volttron_bridge.flatten import flatten_device_publish
from openfdd_stack.volttron_bridge.materialize import (
    merge_flatten_into_row,
    scrape_dict_to_external_id_row,
)
from openfdd_stack.volttron_bridge.topics import VolttronDeviceTopic, parse_device_subscription_topic

__all__ = [
    "VolttronDeviceTopic",
    "parse_device_subscription_topic",
    "flatten_device_publish",
    "list_points_for_volttron_device",
    "scrape_dict_to_external_id_row",
    "merge_flatten_into_row",
]
