"""On-demand full BRICK model/tree fetch (slow on large remote Edge sites)."""

from __future__ import annotations

import json
from typing import Any

from portfolio.central.edge_fetch import edge_client_for_site


def build_model_tree_summary(site_id: str, *, include_tree: bool = False) -> dict[str, Any]:
    """Fetch /api/model/tree; return compact summary by default."""
    site, token, client = edge_client_for_site(site_id)
    tree = client.get_model_tree(token=token)
    equipment = tree.get("equipment") if isinstance(tree.get("equipment"), list) else []
    points = tree.get("points") if isinstance(tree.get("points"), list) else []
    sites = tree.get("sites") if isinstance(tree.get("sites"), list) else []

    equipment_sample: list[str] = []
    for row in equipment[:20]:
        if not isinstance(row, dict):
            continue
        label = str(row.get("name") or row.get("id") or row.get("equipment_id") or "").strip()
        if label:
            equipment_sample.append(label)

    payload_bytes = len(json.dumps(tree, separators=(",", ":")).encode("utf-8"))

    out: dict[str, Any] = {
        "site_id": site_id,
        "edge_url": site.base_url,
        "equipment_count": len(equipment),
        "point_count": len(points),
        "site_count": len(sites),
        "sites": [
            {
                "site_id": row.get("site_id") or row.get("id"),
                "name": row.get("name"),
            }
            for row in sites[:12]
            if isinstance(row, dict)
        ],
        "equipment_sample": equipment_sample,
        "approx_payload_kb": round(payload_bytes / 1024, 1),
        "note": (
            "Full BRICK model graph loaded on demand. Remote sites often take 20–40s "
            "and return ~100+ KB — not included in automatic dashboard refresh."
        ),
    }
    if include_tree:
        out["tree"] = tree
    return out
