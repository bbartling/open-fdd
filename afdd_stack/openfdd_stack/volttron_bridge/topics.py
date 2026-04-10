"""Parse VOLTTRON pub/sub device topics (``devices/<name>/…``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VolttronDeviceTopic:
    """Components of a typical device scrape topic."""

    device_name: str
    """Platform driver device name (e.g. ``BensFakeAHU``)."""

    suffix: str
    """Remainder after ``devices/<device_name>/`` (often ``all``)."""


def parse_device_subscription_topic(topic: str) -> Optional[VolttronDeviceTopic]:
    """
    Parse topics such as ``devices/BensFakeAHU/all`` produced by the VOLTTRON platform driver.

    Returns ``None`` if the string is not at least ``devices/<name>/<suffix>``.
    """
    t = topic.strip().strip("/")
    if not t:
        return None
    parts = t.split("/")
    if len(parts) < 3:
        return None
    if parts[0] != "devices":
        return None
    device_name = parts[1]
    if not device_name:
        return None
    suffix = "/".join(parts[2:])
    if not suffix:
        return None
    return VolttronDeviceTopic(device_name=device_name, suffix=suffix)
