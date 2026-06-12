"""Callbacks for RCx Central tabs (Edge, Mechanical, Report Builder)."""

from __future__ import annotations

import json
import os
from urllib import error, request

from dash import Input, Output, State, dcc, html, no_update

CENTRAL_API = os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{CENTRAL_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def register_rcx_callbacks(app) -> None:
    @app.callback(
        Output("edge-list", "children"),
        Output("mech-site", "options"),
        Output("rcx-site", "options"),
        Output("fdd-site", "options"),
        Output("val-site", "options"),
        Input("main-tabs", "value"),
        Input("edge-save-btn", "n_clicks"),
    )
    def refresh_edge_lists(tab, _save):
        try:
            data = _api("GET", "/api/central/edges")
            edges = data.get("edges") or []
            opts = [{"label": f"{e.get('name')} ({e.get('site_id')})", "value": e.get("site_id")} for e in edges]
            rows = [html.Li(f"{e.get('name')} — {e.get('base_url')} [{e.get('auth_type')}]") for e in edges]
            return html.Ul(rows), opts, opts, opts, opts
        except Exception as exc:
            return html.P(str(exc)), [], [], [], []

    @app.callback(
        Output("edge-test-result", "children"),
        Input("edge-test-btn", "n_clicks"),
        State("edge-url", "value"),
        State("edge-user", "value"),
        State("edge-password", "value"),
        prevent_initial_call=True,
    )
    def test_edge(_n, url, user, password):
        if not url:
            return "Enter Edge base URL."
        try:
            out = _api(
                "POST",
                "/api/central/edges/test",
                {"base_url": url, "username": user or "agent", "password": password or "", "auth_type": "password"},
            )
            return json.dumps(out, indent=2)
        except Exception as exc:
            return str(exc)

    @app.callback(
        Output("edge-test-result", "children", allow_duplicate=True),
        Input("edge-save-btn", "n_clicks"),
        State("edge-site-id", "value"),
        State("edge-name", "value"),
        State("edge-url", "value"),
        State("edge-user", "value"),
        State("edge-password", "value"),
        prevent_initial_call=True,
    )
    def save_edge(_n, site_id, name, url, user, password):
        if not site_id or not url:
            return "site_id and base_url required."
        try:
            _api(
                "POST",
                "/api/central/edges",
                {
                    "site_id": site_id,
                    "name": name or site_id,
                    "base_url": url,
                    "username": user or "agent",
                    "password": password or "",
                    "auth_type": "password",
                },
            )
            return f"Saved Edge {site_id}."
        except Exception as exc:
            return str(exc)

    @app.callback(
        Output("mech-summary", "children"),
        Input("mech-refresh-btn", "n_clicks"),
        State("mech-site", "value"),
        State("mech-hours", "value"),
        prevent_initial_call=True,
    )
    def refresh_mech(_n, site_id, hours):
        if not site_id:
            return "Select a site."
        try:
            out = _api("GET", f"/api/central/mechanical-summary/{site_id}?hours={hours or 24}")
            return json.dumps(out, indent=2)
        except Exception as exc:
            return str(exc)

    @app.callback(
        Output("rcx-readiness", "children"),
        Output("rcx-chart-checkboxes", "children"),
        Output("rcx-section-checkboxes", "children"),
        Input("rcx-preview-btn", "n_clicks"),
        State("rcx-site", "value"),
        State("rcx-hours", "value"),
        State("rcx-overlays", "value"),
        prevent_initial_call=True,
    )
    def rcx_preview(_n, site_id, hours, overlays):
        if not site_id:
            return "Select a site.", no_update, no_update
        try:
            out = _api(
                "POST",
                "/api/central/rcx/preview",
                {
                    "site_id": site_id,
                    "hours": hours or 24,
                    "show_fault_overlays": "on" in (overlays or []),
                },
            )
            fs = out.get("fault_summary") or {}
            text = (
                f"Active faults: {fs.get('active_faults')} · "
                f"Fault hours: {fs.get('total_fault_hours')} · "
                f"Disabled charts: {len(out.get('disabled_charts') or [])}"
            )
            charts = dcc.Checklist(
                id="rcx-charts-selected",
                options=[
                    {"label": c.get("title"), "value": c.get("chart_id")}
                    for c in (out.get("available_charts") or [])
                ],
                value=[c.get("chart_id") for c in (out.get("available_charts") or [])],
            )
            disabled = html.Ul(
                [html.Li(f"{c.get('title')}: {c.get('reason')}") for c in (out.get("disabled_charts") or [])]
            )
            sections = dcc.Checklist(
                id="rcx-sections-selected",
                options=[{"label": s.get("label"), "value": s.get("id")} for s in (out.get("sections") or [])],
                value=[s.get("id") for s in (out.get("sections") or [])],
            )
            return html.Div([html.P(text), disabled]), charts, sections
        except Exception as exc:
            return str(exc), no_update, no_update

    @app.callback(
        Output("rcx-chart-previews", "children"),
        Input("rcx-charts-btn", "n_clicks"),
        State("rcx-site", "value"),
        State("rcx-hours", "value"),
        State("rcx-charts-selected", "value"),
        State("rcx-overlays", "value"),
        prevent_initial_call=True,
    )
    def rcx_chart_previews(_n, site_id, hours, chart_ids, overlays):
        if not site_id:
            return "Select a site."
        try:
            out = _api(
                "POST",
                "/api/central/rcx/charts/preview",
                {
                    "site_id": site_id,
                    "hours": hours or 24,
                    "chart_ids": chart_ids or [],
                    "show_fault_overlays": "on" in (overlays or []),
                },
            )
            imgs = []
            for p in out.get("chart_previews") or []:
                b64 = p.get("image_base64")
                if b64:
                    imgs.append(
                        html.Div(
                            [
                                html.H4(p.get("title")),
                                html.Img(src=f"data:image/png;base64,{b64}", style={"maxWidth": "100%"}),
                            ]
                        )
                    )
            return imgs or "No chart previews (missing data or python-docx/matplotlib)."
        except Exception as exc:
            return str(exc)

    @app.callback(
        Output("fdd-rules-table", "children"),
        Input("fdd-refresh-btn", "n_clicks"),
        State("fdd-site", "value"),
        State("fdd-hours", "value"),
        prevent_initial_call=True,
    )
    def refresh_fdd(_n, site_id, hours):
        if not site_id:
            return "Select a site."
        try:
            out = _api("GET", f"/api/central/fdd-analytics/{site_id}?hours={hours or 24}")
            return json.dumps(out, indent=2)
        except Exception as exc:
            return str(exc)

    @app.callback(
        Output("val-result", "children"),
        Output("val-jobs", "children"),
        Input("val-run-btn", "n_clicks"),
        State("val-site", "value"),
        prevent_initial_call=True,
    )
    def run_validation(_n, site_id):
        if not site_id:
            return "Select a site.", no_update
        try:
            out = _api(
                "POST",
                "/api/central/validation/run",
                {"site_id": site_id, "interval_hours": 2, "duration_hours": 0, "sleep_seconds": 0},
            )
            jobs = _api("GET", "/api/central/validation/jobs")
            return json.dumps(out, indent=2), json.dumps(jobs, indent=2)
        except Exception as exc:
            return str(exc), no_update

    @app.callback(
        Output("rcx-download", "data"),
        Output("rcx-status", "children"),
        Input("rcx-docx-btn", "n_clicks"),
        State("rcx-site", "value"),
        State("rcx-hours", "value"),
        State("rcx-charts-selected", "value"),
        State("rcx-sections-selected", "value"),
        prevent_initial_call=True,
    )
    def rcx_download(_n, site_id, hours, charts, sections):
        if not site_id:
            return no_update, "Select a site."
        try:
            url = f"{CENTRAL_API}/api/central/rcx/report"
            body = json.dumps(
                {
                    "site_id": site_id,
                    "hours": hours or 24,
                    "charts": charts or [],
                    "sections": sections or [],
                }
            ).encode("utf-8")
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=180) as resp:
                blob = resp.read()
            fname = f"openfdd-rcx-{site_id}.docx"
            return dcc.send_bytes(blob, fname), "Report generated — download started."
        except Exception as exc:
            return no_update, str(exc)
