"""Stable point and series identifiers for BACnet CSV / local storage."""

from __future__ import annotations

import re


def _slug(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def make_point_id(device_instance: int | str, object_type: str, object_instance: int | str) -> str:
    # BACpypes3 ObjectType must be str()'d before slug (analog-input enum slugs to "unknown" otherwise).
    ot = _slug(str(object_type))
    return f"{device_instance}-{ot}-{object_instance}"


def make_series_id(
    site_id: str,
    building_id: str,
    system_id: str,
    point_id: str,
) -> str:
    return "#".join(
        [
            _slug(site_id),
            _slug(building_id),
            _slug(system_id),
            point_id,
        ]
    )
