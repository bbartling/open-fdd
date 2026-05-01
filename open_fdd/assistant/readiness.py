"""Human / agent handoff payload: where to click next and a copy-paste narrative stub."""

from __future__ import annotations

import os
from typing import Any


def ui_public_base_url() -> str:
    explicit = (os.environ.get("OFDD_UI_PUBLIC_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    port = (os.environ.get("OFDD_UI_PORT") or "5173").strip() or "5173"
    return f"http://127.0.0.1:{port}"


def build_readiness_payload(model: dict[str, Any]) -> dict[str, Any]:
    ui = ui_public_base_url()
    sites_out: list[dict[str, Any]] = []
    for s in model.get("sites") or []:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "")
        if not sid:
            continue
        name = str(s.get("name") or sid)
        pts = [
            p
            for p in (model.get("points") or [])
            if isinstance(p, dict) and str(p.get("site_id")) == sid
        ]
        sites_out.append(
            {
                "id": sid,
                "name": name,
                "point_count": len(pts),
                "brick_mapped_points": sum(1 for p in pts if str(p.get("brick_type") or "") not in ("", "Point")),
            },
        )

    deep_links = {
        "plots": f"{ui}/plots",
        "plots_fdd_hint": "On Plots, use **Load + FDD overlay** after choosing source/join in the backfill panel.",
        "csv_import": f"{ui}/csv-import",
        "data_model": f"{ui}/data-model",
        "site_management": f"{ui}/site-management",
        "openfdd_claw_chat": f"{ui}/openfdd-claw-chat",
    }

    suggested_actions = [
        "Open **Plots** → pick a site → **Load + FDD overlay** to see sensors + fault columns together.",
        "Tune YAML thresholds under **FDD Rule Setup**, then re-run overlay or **Run FDD backfill**.",
        "When weather/onboard/BACnet are configured, ingest those drivers so **All sources (joined)** reflects multi-stream data.",
    ]

    lines = [
        "### Open-FDD - ready for engineering review",
        "",
        f"- **UI (local):** {ui}",
        f"- **Plots:** {deep_links['plots']}",
        "",
        "**Sites in this workspace**",
    ]
    if not sites_out:
        lines.append("- _(none yet - import CSV or run a site profile pack.)_")
    else:
        for s in sites_out:
            lines.append(
                f"- **{s['name']}** (`{s['id']}`) - {s['point_count']} points, "
                f"{s['brick_mapped_points']} with BRICK/fdd mapping",
            )
    lines.extend(
        [
            "",
            "_Mechanical review:_ Data are ingested and mapped for FDD; open **Plots** with overlay to scan for "
            "sensor bounds / flatline / operating-band flags. If something looks off on a specific asset, "
            "call out the site id and we can tighten rules or add points.",
            "",
            "**Next (you or the agent):** Want me to tune a specific fault rule or add another data source next? **(yes / no)**",
        ],
    )
    message_md = "\n".join(lines)

    return {
        "version": 1,
        "ui_public_base_url": ui,
        "sites": sites_out,
        "deep_links": deep_links,
        "suggested_actions": suggested_actions,
        "message_markdown": message_md,
        "conversation": {
            "prompt_for_human": message_md,
            "suggested_follow_up_yes_no": "Want me to tune fault thresholds or add another ingest source next? (yes/no)",
        },
    }
