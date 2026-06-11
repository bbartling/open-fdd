"""Fake fault event sink — replace with SNS, webhook, historian, etc."""

from __future__ import annotations

from typing import Any


def write_fault_events(events: list[dict[str, Any]]) -> None:
    for ev in events:
        print("FAULT_EVENT", ev)
