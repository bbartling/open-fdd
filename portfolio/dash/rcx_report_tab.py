"""RCx Report Builder — gallery previews with per-chart DOCX selection."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib import error, request

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from portfolio.dash.theme import BTN_PRIMARY, BTN_SECONDARY, SECTION_STYLE

CENTRAL_API = os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")

HOUR_OPTS = [
    {"label": "Last 2 hours", "value": 2},
    {"label": "Last 24 hours", "value": 24},
    {"label": "Last 7 days", "value": 168},
]

POINT_TREE_STYLE = {
    "maxHeight": "440px",
    "overflowY": "auto",
    "borderRadius": "8px",
    "padding": "8px 4px",
    "marginTop": "10px",
}

GALLERY_STYLE = {
    "display": "grid",
    "gridTemplateColumns": "repeat(auto-fill, minmax(340px, 1fr))",
    "gap": "16px",
    "marginTop": "14px",
}


def _api_get(path: str, *, timeout: int = 90) -> dict:
    req = request.Request(f"{CENTRAL_API}{path}", method="GET")
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_post(path: str, body: dict, *, timeout: int = 300) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        f"{CENTRAL_API}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _default_dates() -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=1)
    return start.date().isoformat(), end.date().isoformat()


def _report_body(
    site_id: str,
    hours: int,
    start_d: str | None,
    end_d: str | None,
    *,
    chart_ids: list[str] | None = None,
    sections: list[str] | None = None,
    custom_pts: list[str] | None = None,
    bundle_ids: list[str] | None = None,
    overlays: list | None = None,
    catalog_only: bool = False,
    include_previews: bool = True,
    gallery_mode: bool = False,
) -> dict:
    body: dict = {
        "site_id": site_id,
        "hours": hours or 24,
        "chart_ids": chart_ids or [],
        "charts": chart_ids or [],
        "sections": sections or [],
        "custom_columns": custom_pts or [],
        "show_fault_overlays": "on" in (overlays or []),
        "catalog_only": catalog_only,
        "include_previews": include_previews,
        "gallery_mode": gallery_mode,
    }
    if bundle_ids:
        body["bundle_ids"] = bundle_ids
    if start_d and end_d:
        body["start"] = f"{start_d}T00:00:00+00:00"
        body["end"] = f"{end_d}T23:59:59+00:00"
    return body


def _point_tree_ui(tree: dict, theme: dict) -> html.Div:
    equipment = tree.get("equipment") or []
    if not equipment:
        return html.P("No points returned from Edge model tree.", style={"color": theme["muted"], "fontSize": "13px"})

    blocks: list = []
    for i, eq in enumerate(equipment):
        name = str(eq.get("equipment_name") or "Equipment")
        pts = eq.get("points") or []
        eq_id = str(eq.get("equipment_id") or name).replace(" ", "_")[:40]
        options = [
            {
                "label": f"{p.get('label')} ({p.get('column')})",
                "value": p.get("column"),
            }
            for p in pts
            if p.get("column")
        ]
        if not options:
            continue
        blocks.append(
            html.Details(
                open=i < 4,
                style={
                    "borderBottom": f"1px solid {theme['grid']}",
                    "padding": "8px 10px",
                    "background": theme["card_bg"],
                },
                children=[
                    html.Summary(
                        f"{name} — {len(options)} point(s)",
                        style={"fontWeight": 600, "fontSize": "13px", "cursor": "pointer"},
                    ),
                    dcc.Checklist(
                        id={"type": "report-eq-points", "index": eq_id},
                        options=options,
                        value=[],
                        style={"fontSize": "12px", "marginTop": "8px", "lineHeight": 1.6},
                        inputStyle={"marginRight": "8px"},
                    ),
                ],
            )
        )
    return html.Div(
        style={
            **POINT_TREE_STYLE,
            "border": f"1px solid {theme['grid']}",
            "background": theme["page_bg"],
        },
        children=blocks,
    )


def _gallery_cards(previews: list[dict], theme: dict, *, default_include: bool = True) -> list:
    cards = []
    for p in previews:
        chart_id = str(p.get("chart_id") or p.get("title") or "chart")
        fig = p.get("plotly_figure")
        b64 = p.get("image_base64")
        if not fig and not b64:
            continue
        bullets = p.get("stats_bullets") or []
        narrative = str(p.get("narrative") or "")
        warns = [str(w) for w in (p.get("warnings") or []) if w]
        row_count = int(p.get("row_count") or 0)
        chart_vis: list = []
        if b64:
            chart_vis.append(
                html.Img(
                    src=f"data:image/png;base64,{b64}",
                    style={"width": "100%", "marginTop": "8px", "borderRadius": "6px"},
                )
            )
        elif fig:
            chart_vis.append(
                dcc.Graph(
                    figure=fig,
                    config={"displayModeBar": True, "responsive": True},
                    style={"height": "360px", "marginTop": "8px"},
                )
            )
        cards.append(
            html.Div(
                style={
                    "background": theme["card_bg"],
                    "border": f"1px solid {theme['grid']}",
                    "borderRadius": "10px",
                    "padding": "12px",
                    "display": "flex",
                    "flexDirection": "column",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start", "gap": "8px"},
                        children=[
                            html.Div(
                                children=[
                                    html.Strong(str(p.get("title") or chart_id), style={"fontSize": "14px"}),
                                    html.Div(
                                        f"{row_count} sample(s)" if row_count else "No samples in window",
                                        style={"fontSize": "11px", "color": theme["muted"], "marginTop": "2px"},
                                    ),
                                ]
                            ),
                            dcc.Checklist(
                                id={"type": "report-include", "index": chart_id},
                                options=[{"label": "Add to report", "value": "on"}],
                                value=["on"] if default_include else [],
                                style={"fontSize": "12px", "whiteSpace": "nowrap"},
                                inputStyle={"marginRight": "4px"},
                            ),
                        ],
                    ),
                    *chart_vis,
                    html.Ul(
                        [html.Li(w, style={"fontSize": "11px", "color": theme["warn"]}) for w in warns],
                        style={"margin": "6px 0 0", "paddingLeft": "16px"},
                    )
                    if warns
                    else None,
                    html.Ul(
                        [html.Li(b, style={"fontSize": "11px", "color": theme["muted"]}) for b in bullets[:5]],
                        style={"margin": "8px 0 0", "paddingLeft": "16px"},
                    )
                    if bullets
                    else None,
                    html.P(
                        narrative,
                        style={"fontSize": "12px", "lineHeight": 1.45, "marginTop": "6px", "color": theme["muted"]},
                    )
                    if narrative
                    else None,
                ],
            )
        )
    return cards


def _workspace_url(
    site_id: str,
    hours: int,
    start_d: str | None,
    end_d: str | None,
    overlays: list | None,
) -> str:
    import urllib.parse

    params: dict[str, str] = {
        "hours": str(hours or 24),
        "show_fault_overlays": "true" if "on" in (overlays or []) else "false",
    }
    if start_d and end_d:
        params["start"] = f"{start_d}T00:00:00+00:00"
        params["end"] = f"{end_d}T23:59:59+00:00"
    qs = urllib.parse.urlencode(params)
    return f"/api/central/rcx/workspace/{urllib.parse.quote(site_id)}?{qs}"


def _bundle_picker_ui(report_bundles: dict, theme: dict) -> tuple[html.Div, list[str]]:
    """Grouped report-package checklists from data model (building / AHU / HWS / VAV)."""
    bundles = report_bundles.get("bundles") or []
    default_ids = list(report_bundles.get("default_bundle_ids") or [])
    if not bundles:
        return html.P("No report bundles from Edge data model.", style={"color": theme["muted"]}), []

    family_order = [
        ("building", "Building"),
        ("ahu", "AHU reports"),
        ("hws", "HWS / plant reports"),
        ("vav", "VAV reports"),
    ]
    blocks: list = []
    for fam_key, fam_title in family_order:
        fam_bundles = [b for b in bundles if b.get("family") == fam_key]
        if not fam_bundles:
            continue
        options = [
            {
                "label": f"{b.get('label')} ({b.get('chart_count', 0)} chart(s))",
                "value": b.get("bundle_id"),
            }
            for b in fam_bundles
        ]
        default_vals = [b["bundle_id"] for b in fam_bundles if b.get("bundle_id") in default_ids]
        body = dcc.Checklist(
            id={"type": "report-bundle", "family": fam_key},
            options=options,
            value=default_vals,
            style={"fontSize": "13px", "lineHeight": 1.7},
            inputStyle={"marginRight": "8px"},
        )
        if fam_key == "vav":
            blocks.append(
                html.Details(
                    open=False,
                    children=[
                        html.Summary(
                            f"{fam_title} ({len(fam_bundles)}) — expand to select individual VAV reports",
                            style={"fontWeight": 600, "cursor": "pointer", "marginBottom": "6px"},
                        ),
                        html.Div(
                            style={"maxHeight": "220px", "overflowY": "auto", "paddingLeft": "4px"},
                            children=[body],
                        ),
                    ],
                )
            )
        else:
            blocks.append(html.H4(fam_title, style={"margin": "12px 0 6px", "fontSize": "14px"}))
            blocks.append(body)

    return html.Div(blocks), default_ids


def _workspace_status_html(catalog: dict, tree: dict, theme: dict) -> html.Div:
    fs = catalog.get("fault_summary") or {}
    suggested = catalog.get("suggested_chart_ids") or []
    disabled = catalog.get("disabled_charts") or []
    avail = catalog.get("available_charts") or []
    cached = catalog.get("_cached")
    mech = catalog.get("mechanical_summary") or {}
    inv = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}

    rb = catalog.get("report_bundles") or {}
    families = rb.get("families") or {}
    ahu_n = families.get("ahu", {}).get("count", "—")
    vav_n = families.get("vav", {}).get("count", "—")
    hws_n = families.get("hws", {}).get("count", "—")

    children: list = [
        html.P(
            f"Active faults: {fs.get('active_faults', 0)} · "
            f"Fault hours: {fs.get('total_fault_hours', '—')} · "
            f"Inventory: {inv.get('ahus', '—')} AHU / {inv.get('vavs', '—')} VAV · "
            f"Report packages: {ahu_n} AHU, {hws_n} HWS, {vav_n} VAV"
            + (" · cached" if cached else "")
        ),
        html.P(
            "Select report packages below — defaults render Building + AHU only (not all 30 VAVs).",
            style={"color": theme["accent"], "fontWeight": 500},
        ),
    ]
    if tree:
        children.append(
            html.P(
                f"Data model: {tree.get('point_count', 0)} points across {tree.get('equipment_count', 0)} equipment.",
                style={"fontSize": "12px", "color": theme["muted"]},
            )
        )
    if disabled:
        children.append(html.P("Unavailable charts:", style={"marginTop": "8px", "fontWeight": 600}))
        children.append(html.Ul([html.Li(f"{c.get('title')}: {c.get('reason')}") for c in disabled[:8]]))
    diag = catalog.get("diagnostics") or {}
    for hint in (diag.get("hints") or [])[:3]:
        children.append(html.P(hint, style={"fontSize": "12px", "color": theme["muted"], "margin": "4px 0 0"}))
    return html.Div(children)


def report_layout(theme: dict) -> html.Div:
    start_d, end_d = _default_dates()
    return html.Div(
        style={"paddingTop": "8px", "maxWidth": "1400px"},
        children=[
            dcc.Store(id="report-catalog-store"),
            dcc.Store(id="report-rendered-ids"),
            html.P(
                "Charts are driven from the Edge BRICK data model (equipment_to_points). "
                "Pick report packages by equipment family, render, then check “Add to report” for DOCX.",
                style={"color": theme["muted"], "margin": "0 0 18px", "fontSize": "14px"},
            ),
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(auto-fit, minmax(280px, 1fr))",
                    "gap": "18px",
                    "marginBottom": "20px",
                },
                children=[
                    html.Div(
                        children=[
                            html.Label("Building", style={"fontWeight": 600, "display": "block", "marginBottom": "6px"}),
                            dcc.Dropdown(id="report-site", placeholder="Connect an Edge first", clearable=False),
                        ]
                    ),
                    html.Div(
                        children=[
                            html.Label("Time window", style={"fontWeight": 600, "display": "block", "marginBottom": "6px"}),
                            dcc.RadioItems(
                                id="report-hours",
                                options=HOUR_OPTS,
                                value=24,
                                inline=True,
                                style={"fontSize": "13px"},
                            ),
                            dcc.DatePickerRange(
                                id="report-date-range",
                                start_date=start_d,
                                end_date=end_d,
                                display_format="YYYY-MM-DD",
                                style={"marginTop": "8px"},
                            ),
                            html.Div(
                                "Optional UTC date range overrides quick window.",
                                style={"color": theme["muted"], "fontSize": "11px", "marginTop": "4px"},
                            ),
                        ]
                    ),
                    html.Div(
                        children=[
                            html.Label("Options", style={"fontWeight": 600, "display": "block", "marginBottom": "6px"}),
                            dcc.Checklist(
                                id="report-overlays",
                                options=[{"label": "Overlay FDD faults on trend charts", "value": "on"}],
                                value=["on"],
                                style={"fontSize": "13px"},
                            ),
                        ]
                    ),
                ],
            ),
            html.Div(
                style={**SECTION_STYLE, "marginBottom": "18px"},
                children=[
                    html.Div(
                        style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "alignItems": "center"},
                        children=[
                            html.Button("Load workspace", id="report-load-workspace-btn", n_clicks=0, style=BTN_PRIMARY),
                            html.Button("Render selected reports", id="report-render-gallery-btn", n_clicks=0, style=BTN_PRIMARY),
                            html.Button("Download DOCX", id="report-docx-btn", n_clicks=0, style=BTN_PRIMARY),
                        ],
                    ),
                    dcc.Loading(
                        id="report-workspace-loading",
                        type="circle",
                        color=theme["accent"],
                        children=html.Div(id="report-workspace-status", style={"color": theme["muted"], "fontSize": "13px", "marginTop": "10px"}),
                    ),
                    html.Div(
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "16px", "marginTop": "12px"},
                        children=[
                            html.Div(
                                children=[
                                    html.H4("DOCX sections", style={"margin": "0 0 8px", "fontSize": "14px"}),
                                    html.Div(id="report-section-checkboxes"),
                                ]
                            ),
                            html.Div(
                                children=[
                                    html.H4("Report packages (data model)", style={"margin": "0 0 8px", "fontSize": "14px"}),
                                    html.Div(id="report-bundle-picker"),
                                ]
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                style={**SECTION_STYLE, "marginBottom": "18px"},
                children=[
                    html.H3("Chart gallery", style={"margin": "0 0 6px", "fontSize": "16px"}),
                    html.P(
                        "Gallery shows charts for selected packages only. Each preview has an “Add to report” checkbox.",
                        style={"color": theme["muted"], "fontSize": "12px", "margin": "0 0 4px"},
                    ),
                    dcc.Loading(
                        id="report-gallery-loading",
                        type="circle",
                        color=theme["accent"],
                        children=html.Div(id="report-chart-gallery", style=GALLERY_STYLE),
                    ),
                ],
            ),
            html.Div(id="report-action-status", style={"color": theme["muted"], "fontSize": "13px", "marginTop": "8px"}),
            dcc.Loading(
                id="report-docx-loading",
                type="circle",
                color=theme["accent"],
                children=html.Div(id="report-docx-status", style={"minHeight": "4px"}),
            ),
            dcc.Download(id="report-download"),
        ],
    )


def register_report_callbacks(app, theme: dict) -> None:
    @app.callback(
        Output("report-site", "options"),
        Output("report-site", "value"),
        Input("main-tabs", "value"),
        Input("edge-registry-revision", "data"),
    )
    def sync_report_sites(tab, _revision):
        if tab != "report":
            return no_update, no_update
        try:
            data = _api_get("/api/central/edges")
            edges = data.get("edges") or []
            opts = [
                {"label": f"{e.get('name') or e.get('site_id')} ({e.get('site_id')})", "value": e.get("site_id")}
                for e in edges
            ]
            val = opts[0]["value"] if opts else None
            return opts, val
        except Exception:
            return [], None

    @app.callback(
        Output("report-catalog-store", "data"),
        Output("report-workspace-status", "children"),
        Output("report-section-checkboxes", "children"),
        Output("report-bundle-picker", "children"),
        Output("report-rendered-ids", "data"),
        Input("report-load-workspace-btn", "n_clicks"),
        Input("main-tabs", "value"),
        Input("report-site", "value"),
        State("report-hours", "value"),
        State("report-date-range", "start_date"),
        State("report-date-range", "end_date"),
        State("report-overlays", "value"),
        State("report-catalog-store", "data"),
        prevent_initial_call=True,
    )
    def load_workspace(_n, tab, site_id, hours, start_d, end_d, overlays, existing_catalog):
        triggered = ctx.triggered_id
        if tab != "report":
            return no_update, no_update, no_update, no_update, no_update, no_update
        if triggered == "main-tabs":
            if existing_catalog or not site_id:
                if not site_id and not existing_catalog:
                    return (
                        no_update,
                        html.P(
                            "Select a building (or wait for Edge list) — workspace auto-loads when site is ready.",
                            style={"color": theme["muted"]},
                        ),
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                    )
                return no_update, no_update, no_update, no_update, no_update, no_update
        elif triggered == "report-site":
            if not site_id:
                return no_update, "Select a building.", no_update, no_update, no_update, no_update
            prev_site = (existing_catalog or {}).get("site_id")
            if existing_catalog and prev_site == site_id:
                return no_update, no_update, no_update, no_update, no_update, no_update
        elif not site_id:
            return no_update, "Select a building.", no_update, no_update, no_update, no_update
        try:
            ws = _api_get(_workspace_url(site_id, hours, start_d, end_d, overlays), timeout=90)
            catalog = ws.get("catalog") or {}
            mech = catalog.get("mechanical_summary") or {}
            if (mech.get("counts") or {}).get("ahus", 0) == 0:
                try:
                    _api_post(f"/api/central/model/remediate-hvac/{site_id}", {})
                    ws = _api_get(_workspace_url(site_id, hours, start_d, end_d, overlays), timeout=90)
                    catalog = ws.get("catalog") or {}
                except Exception:
                    pass
            catalog["_cached"] = ws.get("cached")
            catalog["_point_tree"] = ws.get("point_tree")

            sections = dcc.Checklist(
                id="report-sections-selected",
                options=[{"label": s.get("label"), "value": s.get("id")} for s in (catalog.get("sections") or [])],
                value=[s.get("id") for s in (catalog.get("sections") or []) if s.get("id") != "appendix_faults"],
                style={"fontSize": "13px", "lineHeight": 1.7},
            )
            bundle_ui, _defaults = _bundle_picker_ui(catalog.get("report_bundles") or {}, theme)
            return (
                catalog,
                _workspace_status_html(catalog, ws.get("point_tree") or {}, theme),
                sections,
                bundle_ui,
                [],
            )
        except Exception as exc:
            return no_update, html.P(f"Workspace load failed: {exc}"[:400], style={"color": theme["warn"]}), no_update, no_update, no_update

    @app.callback(
        Output("report-chart-gallery", "children"),
        Output("report-rendered-ids", "data", allow_duplicate=True),
        Output("report-action-status", "children"),
        Input("report-catalog-store", "data"),
        Input("report-render-gallery-btn", "n_clicks"),
        State("report-site", "value"),
        State("report-hours", "value"),
        State("report-date-range", "start_date"),
        State("report-date-range", "end_date"),
        State("report-overlays", "value"),
        State("report-rendered-ids", "data"),
        State({"type": "report-bundle", "family": ALL}, "value"),
        prevent_initial_call=True,
    )
    def render_gallery(catalog, gallery_clicks, site_id, hours, start_d, end_d, overlays, rendered_ids, bundle_vals):
        if not site_id or not catalog:
            return no_update, no_update, "Load workspace first (or wait for auto-load on tab open)."

        triggered = ctx.triggered_id
        rb = catalog.get("report_bundles") or {}
        if triggered == "report-catalog-store":
            if rendered_ids:
                return no_update, no_update, no_update
            bundle_ids = list(rb.get("default_bundle_ids") or [])
        elif triggered == "report-render-gallery-btn":
            bundle_ids = []
            for sel in bundle_vals or []:
                if isinstance(sel, list):
                    bundle_ids.extend(sel)
            bundle_ids = list(dict.fromkeys(bundle_ids))
            if not bundle_ids:
                return no_update, no_update, "Select at least one report package (Building, AHU, HWS, or VAV)."
        else:
            return no_update, no_update, no_update

        if not bundle_ids:
            return html.P("No default report packages.", style={"color": theme["muted"]}), [], "No bundles."

        try:
            out = _api_post(
                "/api/central/rcx/preview",
                _report_body(
                    site_id,
                    hours,
                    start_d,
                    end_d,
                    bundle_ids=bundle_ids,
                    overlays=overlays,
                    include_previews=True,
                    gallery_mode=True,
                ),
                timeout=240,
            )
            previews = out.get("chart_previews") or []
            new_ids = [str(p.get("chart_id")) for p in previews if p.get("chart_id")]
            cards = _gallery_cards(previews, theme)
            shown = len(cards)
            fams = ", ".join(bundle_ids[:4]) + ("…" if len(bundle_ids) > 4 else "")
            msg = f"Rendered {shown} chart(s) for {len(bundle_ids)} report package(s): {fams}."
            if not shown:
                diag = out.get("diagnostics") or catalog.get("diagnostics") or {}
                hints = diag.get("hints") or []
                roles = diag.get("roles_resolved") or {}
                detail = html.Div(
                    [
                        html.P("No chart images returned.", style={"fontWeight": 600}),
                        html.P(
                            "Try a longer time window (24h or 7d) or confirm Edge historian has data for resolved columns.",
                            style={"color": theme["muted"]},
                        ),
                        html.Ul([html.Li(h) for h in hints], style={"fontSize": "12px"}),
                        html.Pre(
                            json.dumps(roles, indent=2)[:800],
                            style={"fontSize": "11px", "background": theme["page_bg"], "padding": "8px", "overflow": "auto"},
                        )
                        if roles
                        else None,
                    ]
                )
                return detail, [], msg
            return cards, new_ids, msg
        except Exception as exc:
            return no_update, no_update, str(exc)[:400]

    @app.callback(
        Output("report-download", "data"),
        Output("report-action-status", "children", allow_duplicate=True),
        Output("report-docx-status", "children"),
        Input("report-docx-btn", "n_clicks"),
        State("report-site", "value"),
        State("report-hours", "value"),
        State("report-date-range", "start_date"),
        State("report-date-range", "end_date"),
        State("report-sections-selected", "value"),
        State("report-overlays", "value"),
        State("report-catalog-store", "data"),
        State({"type": "report-include", "index": ALL}, "value"),
        State({"type": "report-include", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def download_docx(_n, site_id, hours, start_d, end_d, sections, overlays, catalog, include_vals, include_ids):
        if not site_id:
            return no_update, "Select a building.", ""
        if not catalog:
            return no_update, "Load workspace first.", "Required: Load workspace → Render gallery → check Add to report."

        chart_ids: list[str] = []
        custom_cols: list[str] = []
        for val, comp_id in zip(include_vals or [], include_ids or []):
            if not isinstance(comp_id, dict) or "on" not in (val or []):
                continue
            cid = str(comp_id.get("index") or "")
            if not cid:
                continue
            chart_ids.append(cid)
            if cid.startswith("custom_"):
                custom_cols.append(cid[7:])

        if not chart_ids:
            return (
                no_update,
                "Nothing selected for DOCX.",
                "Check “Add to report” on at least one chart in the gallery (render gallery first).",
            )

        try:
            body = _report_body(
                site_id,
                hours,
                start_d,
                end_d,
                chart_ids=chart_ids,
                sections=sections,
                custom_pts=custom_cols,
                overlays=overlays,
            )
            url = f"{CENTRAL_API}/api/central/rcx/report"
            req = request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=300) as resp:
                blob = resp.read()
            fname = f"openfdd-rcx-{site_id}.docx"
            return (
                dcc.send_bytes(blob, fname),
                f"DOCX download started ({len(chart_ids)} chart(s) included).",
                f"Generated {fname} ({len(blob) // 1024} KB).",
            )
        except error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")[:300]
            return no_update, err, "DOCX failed — see message above."
        except Exception as exc:
            return no_update, str(exc)[:300], "DOCX failed."
