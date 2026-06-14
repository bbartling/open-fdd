"""TTL cache for RCx workspace catalog + point tree."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _rcx_ttl() -> int:
    raw = os.environ.get("OPENFDD_RCX_CACHE_SECS", "120")
    try:
        return max(0, int(raw))
    except ValueError:
        return 120


def _cache_key(prefix: str, **parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def get_workspace(
    *,
    site_id: str,
    hours: int,
    start: str | None,
    end: str | None,
    show_fault_overlays: bool,
) -> dict[str, Any]:
    key = _cache_key("rcx_ws", site_id=site_id, hours=hours, start=start, end=end, overlays=show_fault_overlays)
    ttl = _rcx_ttl()
    import time

    now = time.time()
    if ttl > 0 and key in _CACHE:
        expires, payload = _CACHE[key]
        if now < expires:
            return {**payload, "cached": True}

    from .chart_preview import build_rcx_preview
    from .rcx_points import list_report_point_tree

    catalog = build_rcx_preview(
        site_id=site_id,
        hours=hours,
        start=start,
        end=end,
        show_fault_overlays=show_fault_overlays,
        catalog_only=True,
        include_previews=False,
    )
    tree = list_report_point_tree(site_id, limit=500)
    payload = {"catalog": catalog, "point_tree": tree}
    if ttl > 0:
        _CACHE[key] = (now + ttl, payload)
    return {**payload, "cached": False}
