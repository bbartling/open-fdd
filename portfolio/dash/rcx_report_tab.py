"""RCx Report Builder tab — wizard for Edge-backed DOCX reports."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib import error, request

from dash import Input, Output, State, dcc, html, no_update

from portfolio.dash.theme import BTN_PRIMARY, BTN_SECONDARY, SECTION_STYLE

CENTRAL_API = os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")

HOUR_OPTS = [
    {"label": "Last 2 hours", "value": 2},
    {"label": "Last 24 hours", "value": 24},
    {"label": "Last 7 days", "value": 168},
]


def _api_get(path: str, *, timeout: int = 90) -> dict:
    req = request.Request(f"{CENTRAL_API}{path}", method="GET")
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_post(path: str, body: dict, *, timeout: int = 180) -> dict:
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


def report_layout(theme: dict) -> html.Div:
    start_d, end_d = _default_dates()
    return html.Div(
        style={"paddingTop": "8px"},
        children=[
            html.P(
                "Build RCx Word reports from live Edge data — pick a building, time window, charts, "
                "and optional BACnet points. Data is fetched on demand (not loaded with the dashboard).",
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
                            html.Label("Quick window", style={"fontWeight": 600, "display": "block", "marginBottom": "6px"}),
                            dcc.RadioItems(
                                id="report-hours",
                                options=HOUR_OPTS,
                                value=24,
                                inline=True,
                                style={"fontSize": "13px"},
                            ),
                            html.Div(
                                "Or custom UTC date range (overrides quick window when both dates set):",
                                style={"color": theme["muted"], "fontSize": "12px", "marginTop": "10px"},
                            ),
                            dcc.DatePickerRange(
                                id="report-date-range",
                                start_date=start_d,
                                end_date=end_d,
                                display_format="YYYY-MM-DD",
                                style={"marginTop": "6px"},
                            ),
                        ]
                    ),
                ],
            ),
            html.Div(
                style={**SECTION_STYLE, "marginBottom": "18px"},
                children=[
                    html.H3("Step 1 — Load catalog", style={"margin": "0 0 10px", "fontSize": "16px"}),
                    html.Div(
                        style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "alignItems": "center"},
                        children=[
                            html.Button("Load charts & sections", id="report-load-catalog-btn", n_clicks=0, style=BTN_PRIMARY),
                            dcc.Checklist(
                                id="report-overlays",
                                options=[{"label": "Overlay FDD faults on trend charts", "value": "on"}],
                                value=["on"],
                                style={"fontSize": "13px"},
                            ),
                        ],
                    ),
                    html.Div(id="report-catalog-status", style={"color": theme["muted"], "fontSize": "13px", "marginTop": "8px"}),
                    html.Div(
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "16px", "marginTop": "12px"},
                        children=[
                            html.Div(id="report-chart-checkboxes"),
                            html.Div(id="report-section-checkboxes"),
                        ],
                    ),
                ],
            ),
            html.Div(
                style={**SECTION_STYLE, "marginBottom": "18px"},
                children=[
                    html.H3("Step 2 — Optional custom points", style={"margin": "0 0 10px", "fontSize": "16px"}),
                    html.P(
                        "Add ad-hoc BACnet historian columns (damper cmd, pump VFD, zone temp, etc.). "
                        "Fetched from Edge only when you preview or generate.",
                        style={"color": theme["muted"], "fontSize": "13px", "margin": "0 0 8px"},
                    ),
                    html.Button("Load point list", id="report-load-points-btn", n_clicks=0, style=BTN_SECONDARY),
                    dcc.Dropdown(
                        id="report-custom-points",
                        multi=True,
                        placeholder="Select points after loading list",
                        style={"marginTop": "10px"},
                    ),
                ],
            ),
            html.Div(
                style={**SECTION_STYLE, "marginBottom": "18px"},
                children=[
                    html.H3("Step 3 — Preview & export", style={"margin": "0 0 10px", "fontSize": "16px"}),
                    html.Div(
                        style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
                        children=[
                            html.Button("Preview charts", id="report-preview-btn", n_clicks=0, style=BTN_PRIMARY),
                            html.Button("Generate DOCX", id="report-docx-btn", n_clicks=0, style=BTN_PRIMARY),
                        ],
                    ),
                    html.Div(id="report-preview-status", style={"color": theme["muted"], "fontSize": "13px", "marginTop": "8px"}),
                    dcc.Loading(
                        id="report-preview-loading",
                        type="circle",
                        color=theme["accent"],
                        children=html.Div(id="report-chart-previews", style={"marginTop": "14px"}),
                    ),
                    dcc.Download(id="report-download"),
                ],
            ),
        ],
    )


def _preview_cards(previews: list[dict], theme: dict) -> list:
    cards = []
    for p in previews:
        b64 = p.get("image_base64")
        if not b64:
            continue
        bullets = p.get("stats_bullets") or []
        narrative = str(p.get("narrative") or "")
        cards.append(
            html.Div(
                style={
                    "background": theme["card_bg"],
                    "border": f"1px solid {theme['grid']}",
                    "borderRadius": "10px",
                    "padding": "14px",
                    "marginBottom": "16px",
                },
                children=[
                    html.Strong(str(p.get("title") or p.get("chart_id") or "Chart")),
                    html.Img(
                        src=f"data:image/png;base64,{b64}",
                        style={"maxWidth": "100%", "marginTop": "10px", "display": "block"},
                    ),
                    html.Ul(
                        [html.Li(b, style={"fontSize": "12px", "color": theme["muted"]}) for b in bullets[:6]],
                        style={"margin": "10px 0 0", "paddingLeft": "18px"},
                    )
                    if bullets
                    else None,
                    html.P(narrative, style={"fontSize": "13px", "lineHeight": 1.5, "marginTop": "8px"})
                    if narrative
                    else None,
                ],
            )
        )
    return cards or [html.P("No chart previews — check data readiness or select different charts.", style={"color": theme["muted"]})]


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
            opts = [{"label": f"{e.get('name') or e.get('site_id')} ({e.get('site_id')})", "value": e.get("site_id")} for e in edges]
            val = opts[0]["value"] if opts else None
            return opts, val
        except Exception:
            return [], None

    @app.callback(
        Output("report-catalog-status", "children"),
        Output("report-chart-checkboxes", "children"),
        Output("report-section-checkboxes", "children"),
        Input("report-load-catalog-btn", "n_clicks"),
        State("report-site", "value"),
        State("report-hours", "value"),
        State("report-date-range", "start_date"),
        State("report-date-range", "end_date"),
        State("report-overlays", "value"),
        prevent_initial_call=True,
    )
    def load_catalog(_n, site_id, hours, start_d, end_d, overlays):
        if not site_id:
            return "Select a building.", no_update, no_update
        body: dict = {
            "site_id": site_id,
            "hours": hours or 24,
            "show_fault_overlays": "on" in (overlays or []),
        }
        if start_d and end_d:
            body["start"] = f"{start_d}T00:00:00+00:00"
            body["end"] = f"{end_d}T23:59:59+00:00"
        try:
            out = _api_post("/api/central/rcx/preview", body)
            fs = out.get("fault_summary") or {}
            disabled = out.get("disabled_charts") or []
            status = (
                f"Active faults: {fs.get('active_faults', 0)} · "
                f"Fault hours: {fs.get('total_fault_hours', '—')} · "
                f"Disabled charts: {len(disabled)}"
            )
            charts = dcc.Checklist(
                id="report-charts-selected",
                options=[{"label": c.get("title"), "value": c.get("chart_id")} for c in (out.get("available_charts") or [])],
                value=[c.get("chart_id") for c in (out.get("available_charts") or [])],
            )
            sections = dcc.Checklist(
                id="report-sections-selected",
                options=[{"label": s.get("label"), "value": s.get("id")} for s in (out.get("sections") or [])],
                value=[s.get("id") for s in (out.get("sections") or []) if s.get("id") != "appendix_faults"],
            )
            if disabled:
                status = html.Div(
                    [
                        html.P(status),
                        html.Ul([html.Li(f"{c.get('title')}: {c.get('reason')}") for c in disabled[:8]]),
                    ]
                )
            return status, charts, sections
        except Exception as exc:
            return str(exc)[:300], no_update, no_update

    @app.callback(
        Output("report-custom-points", "options"),
        Input("report-load-points-btn", "n_clicks"),
        State("report-site", "value"),
        prevent_initial_call=True,
    )
    def load_points(_n, site_id):
        if not site_id:
            return []
        try:
            out = _api_get(f"/api/central/rcx/points/{site_id}?limit=250")
            return [
                {
                    "label": f"{p.get('equipment_name')} · {p.get('label')} ({p.get('column')})",
                    "value": p.get("column"),
                }
                for p in (out.get("points") or [])
                if p.get("column")
            ]
        except Exception:
            return []

    def _report_body(site_id, hours, start_d, end_d, charts, sections, custom_pts, overlays):
        body: dict = {
            "site_id": site_id,
            "hours": hours or 24,
            "chart_ids": charts or [],
            "charts": charts or [],
            "sections": sections or [],
            "custom_columns": custom_pts or [],
            "show_fault_overlays": "on" in (overlays or []),
        }
        if start_d and end_d:
            body["start"] = f"{start_d}T00:00:00+00:00"
            body["end"] = f"{end_d}T23:59:59+00:00"
        return body

    @app.callback(
        Output("report-chart-previews", "children"),
        Output("report-preview-status", "children"),
        Input("report-preview-btn", "n_clicks"),
        State("report-site", "value"),
        State("report-hours", "value"),
        State("report-date-range", "start_date"),
        State("report-date-range", "end_date"),
        State("report-charts-selected", "value"),
        State("report-custom-points", "value"),
        State("report-overlays", "value"),
        prevent_initial_call=True,
    )
    def preview_charts(_n, site_id, hours, start_d, end_d, charts, custom_pts, overlays):
        if not site_id:
            return no_update, "Select a building."
        try:
            out = _api_post(
                "/api/central/rcx/preview",
                _report_body(site_id, hours, start_d, end_d, charts, [], custom_pts, overlays),
                timeout=240,
            )
            n = len(out.get("chart_previews") or [])
            return _preview_cards(out.get("chart_previews") or [], theme), f"Loaded {n} chart preview(s) from Edge."
        except Exception as exc:
            return str(exc)[:400], "Preview failed."

    @app.callback(
        Output("report-download", "data"),
        Output("report-preview-status", "children", allow_duplicate=True),
        Input("report-docx-btn", "n_clicks"),
        State("report-site", "value"),
        State("report-hours", "value"),
        State("report-date-range", "start_date"),
        State("report-date-range", "end_date"),
        State("report-charts-selected", "value"),
        State("report-sections-selected", "value"),
        State("report-custom-points", "value"),
        State("report-overlays", "value"),
        prevent_initial_call=True,
    )
    def download_docx(_n, site_id, hours, start_d, end_d, charts, sections, custom_pts, overlays):
        if not site_id:
            return no_update, "Select a building."
        try:
            url = f"{CENTRAL_API}/api/central/rcx/report"
            body = json.dumps(_report_body(site_id, hours, start_d, end_d, charts, sections, custom_pts, overlays)).encode()
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=300) as resp:
                blob = resp.read()
            fname = f"openfdd-rcx-{site_id}.docx"
            return dcc.send_bytes(blob, fname), "DOCX download started."
        except error.HTTPError as exc:
            return no_update, exc.read().decode("utf-8", errors="replace")[:300]
        except Exception as exc:
            return no_update, str(exc)[:300]
