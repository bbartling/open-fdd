"""Human / agent handoff payload: where to click next and a copy-paste narrative stub."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any


def ui_public_base_url() -> str:
    explicit = (os.environ.get("OFDD_UI_PUBLIC_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    port = (os.environ.get("OFDD_UI_PORT") or "8080").strip() or "8080"
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

    def _plots_fdd_url(site_id: str, *, run_source: str = "csv") -> str:
        q = urllib.parse.urlencode(
            {"site_id": site_id, "fdd": "1", "skipMissing": "1", "runSource": run_source},
        )
        return f"{ui}/plots?{q}"

    deep_links = {
        "plots": f"{ui}/plots",
        "plots_fdd_hint": "On Plots, use **Load + FDD overlay** after choosing source/join in the backfill panel.",
        "plots_fdd_csv": f"{ui}/plots?fdd=1&skipMissing=1&runSource=csv",
        "csv_import": f"{ui}/csv-import",
        "data_model": f"{ui}/data-model",
        "site_management": f"{ui}/site-management",
        "fdd_rule_setup": f"{ui}/rule-setup",
        "openfdd_claw_chat": f"{ui}/ai-agent",
    }

    plots_quicklinks: list[dict[str, str]] = []
    for s in sites_out:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        name = str(s.get("name") or sid)
        plots_quicklinks.append(
            {
                "site_id": sid,
                "label": name,
                "href": _plots_fdd_url(sid, run_source="csv"),
            },
        )

    suggested_actions = [
        "Open **Plots** → pick a site → **Load + FDD overlay** to see sensors + fault columns together.",
        "Grafana-style CSVs may keep units in cells (e.g. `69.5 °F`); use **POST /timeseries/clean-metrics** with `commit:false` to preview coercion, then `commit:true` before bounds/flatline rules.",
        "Agents and the UI share the same rule pack on disk: **GET /rules/export-json** for a JSON snapshot (YAML + parsed fields), **PUT /rules/{filename}** to save edits; humans use **FDD Rule Setup** (`/rule-setup`) to edit and save.",
        "Tune YAML thresholds under **FDD Rule Setup**, then re-run overlay or **Run FDD backfill**.",
        "When weather/onboard/BACnet are configured, ingest those drivers so **All sources (joined)** reflects multi-stream data.",
        "Persist a reopenable view for Open-FDD Claw: **POST /plots/share** (same JSON as **/plots/fdd-frame**), then open the returned **plots_open_url** or **GET /plots/share/{id}**.",
        "Prefer **POST /plots/fdd-frame** (or **POST /rules/run** for tabular-only) for automation; tune thresholds via **PUT /rules/{file}** or the Rule Setup UI rather than ad-hoc file edits on disk.",
        "Preview plot health without rules: **GET /plots/frame?...&include_readiness=true** or **POST /timeseries/plot-readiness** (returns a Pydantic-style JSON report: ok, per-column plot_line_ready, recommend_clean_metrics).",
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
        lines.append("")
        lines.append("**Plots with FDD overlay (pre-wired query string)**")
        for q in plots_quicklinks:
            lines.append(f"- [{q['label']}]({q['href']})")
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
        "plots_quicklinks": plots_quicklinks,
        "suggested_actions": suggested_actions,
        "message_markdown": message_md,
        "conversation": {
            "prompt_for_human": message_md,
            "suggested_follow_up_yes_no": "Want me to tune fault thresholds or add another ingest source next? (yes/no)",
        },
    }
