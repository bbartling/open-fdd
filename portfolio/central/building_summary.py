"""Live building summary from Edge BRICK model (registry name ≠ BRICK site id)."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.central.mechanical_narrative import build_mechanical_narrative
from portfolio.collector.edge_client import EdgeClient


def _primary_brick_site(tree: dict[str, Any], registry_site_id: str) -> tuple[str, str]:
    sites = tree.get("sites") if isinstance(tree.get("sites"), list) else []
    for row in sites:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("site_id") or row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if sid == registry_site_id:
            return sid, name or sid
    if sites and isinstance(sites[0], dict):
        row = sites[0]
        return str(row.get("site_id") or row.get("id") or "").strip(), str(row.get("name") or "").strip()
    return "", ""


def build_building_summary(registry_site_id: str) -> dict[str, Any]:
    """Summarise Edge BRICK model for RCx Central dashboard."""
    site = resolve_site_config(registry_site_id)
    client = EdgeClient(site.base_url)
    token = resolve_token(site)

    brick_site_id = ""
    brick_site_name = ""
    equipment_count = 0
    point_count = 0
    model_score: int | None = None
    feed_chains: list[str] = []

    try:
        tree = client.get_model_tree(token=token)
        brick_site_id, brick_site_name = _primary_brick_site(tree, registry_site_id)
        equipment_count = len(tree.get("equipment") or [])
        point_count = len(tree.get("points") or [])
    except RuntimeError:
        tree = {}

    try:
        health = client.get_model_health(token=token)
        counts = health.get("counts") if isinstance(health.get("counts"), dict) else {}
        equipment_count = int(counts.get("equipment") or equipment_count or 0)
        point_count = int(counts.get("points") or point_count or 0)
        model_score = int(health["score"]) if health.get("score") is not None else None
    except RuntimeError:
        pass

    try:
        brief = client.api_get("/openfdd-agent/operational-brief", token=token)
        bm = brief.get("brick_model") if isinstance(brief.get("brick_model"), dict) else {}
        feed_chains = [str(c) for c in (bm.get("feeds_chains") or []) if c][:12]
        if not brick_site_id:
            brick_site_id = str(bm.get("site_id") or "")
    except RuntimeError:
        pass

    mech = build_mechanical_narrative(registry_site_id)
    counts = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}

    title = site.name or registry_site_id
    if brick_site_name:
        title_line = f"{title} — BRICK site «{brick_site_name}»"
        if brick_site_id and brick_site_id != registry_site_id:
            title_line += f" (model id: {brick_site_id}; registry id: {registry_site_id})"
    else:
        title_line = f"{title} (registry id: {registry_site_id})"

    intro = (
        f"{title_line}\n"
        f"Edge: {site.base_url} · Model: {equipment_count} equipment, {point_count} points"
        + (f", health score {model_score}" if model_score is not None else "")
        + "."
    )

    narrative = "\n\n".join(
        part
        for part in (
            intro,
            mech.get("narrative", "").split("\n\n", 1)[-1] if mech.get("narrative") else "",
        )
        if part
    )

    return {
        "registry_site_id": registry_site_id,
        "registry_name": site.name,
        "brick_site_id": brick_site_id,
        "brick_site_name": brick_site_name,
        "narrative": narrative,
        "feeds_chains": feed_chains,
        "model_equipment": equipment_count,
        "model_points": point_count,
        "model_score": model_score,
        "counts": counts,
    }
