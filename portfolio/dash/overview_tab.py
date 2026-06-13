"""OpenFDD RCx Central — unified dashboard (faults, mechanical, FDD, RCx report)."""

from __future__ import annotations

import json
import os
from urllib import error, request

import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from portfolio.central.display_time import format_ts_local, tz_label
from portfolio.central.fdd_preset_catalog import FDD_PRESET_BUTTONS
from portfolio.central.fault_code_lookup import lookup_fault_description
from portfolio.dash.theme import BTN_PRIMARY, BTN_SECONDARY, SECTION_STYLE

CENTRAL_API = os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")

HOUR_OPTS = [
    {"label": "Last 2 hours", "value": 2},
    {"label": "Last 24 hours", "value": 24},
    {"label": "Last 7 days", "value": 168},
]


def _api_get(path: str) -> dict:
    req = request.Request(f"{CENTRAL_API}{path}", method="GET")
    with request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{CENTRAL_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _load_overview(site_id: str) -> dict:
    try:
        return _api_get(f"/api/central/overview/{site_id}")
    except Exception:
        from portfolio.central.overview_data import build_overview, build_overview_from_csv

        try:
            return build_overview(site_id, include_live=True)
        except KeyError:
            return build_overview_from_csv(site_id)


def _card_style(theme: dict) -> dict:
    return {
        "background": theme["card_bg"],
        "borderRadius": "10px",
        "padding": "16px 20px",
        "boxShadow": "0 1px 3px rgba(15,23,42,0.08)",
        "border": f"1px solid {theme['grid']}",
    }


def _section(title: str, theme: dict, *children) -> html.Div:
    return html.Section(
        style={**SECTION_STYLE, "marginTop": "28px"},
        children=[
            html.H2(title, style={"margin": "0 0 12px", "fontSize": "18px", "color": theme["text"]}),
            *children,
        ],
    )


def overview_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.P(
                "Connect an Edge on the Edge Connections tab, then select a building here.",
                style={"color": theme["muted"], "margin": "0 0 16px", "fontSize": "14px"},
            ),
            html.Div(
                style={"display": "flex", "gap": "16px", "alignItems": "center", "flexWrap": "wrap"},
                children=[
                    html.Label("Building", style={"fontWeight": 600}),
                    dcc.Dropdown(
                        id="overview-site",
                        placeholder="Connect an Edge first",
                        clearable=False,
                        style={"minWidth": "280px", "flex": "1"},
                    ),
                    html.Button("Refresh data", id="refresh-data-btn", n_clicks=0, style=BTN_PRIMARY),
                    html.Span(id="refresh-status", style={"color": theme["muted"], "fontSize": "13px"}),
                    dcc.RadioItems(
                        id="overview-hours",
                        options=HOUR_OPTS,
                        value=24,
                        inline=True,
                        style={"fontSize": "13px"},
                    ),
                ],
            ),
            dcc.Loading(
                id="overview-loading",
                type="circle",
                color=theme["accent"],
                children=[
                    html.Span(
                        id="overview-source",
                        style={"color": theme["muted"], "fontSize": "12px", "display": "block", "marginTop": "8px"},
                    ),
                    html.Div(
                        id="overview-kpi-row",
                        style={
                            "display": "grid",
                            "gridTemplateColumns": "repeat(auto-fit, minmax(200px, 1fr))",
                            "gap": "14px",
                            "marginTop": "18px",
                        },
                    ),
                ],
            ),
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1fr 1.2fr", "gap": "18px", "marginTop": "18px"},
                children=[
                    html.Div(
                        style=_card_style(theme),
                        children=[
                            html.H3("Fault mix", style={"margin": "0 0 8px", "fontSize": "15px"}),
                            dcc.Graph(id="overview-fault-pie", config={"displayModeBar": False}, style={"height": "260px"}),
                            html.Div(id="overview-fault-legend"),
                        ],
                    ),
                    html.Div(
                        style=_card_style(theme),
                        children=[html.Div(id="overview-mech-narrative")],
                    ),
                ],
            ),
            _section(
                "Priority 8 operator overrides",
                theme,
                html.Div(id="overview-p8-section"),
            ),
            _section(
                "FDD rules & analytics",
                theme,
                html.Div(id="overview-fdd-rules"),
                html.P(
                    "FDD / BRICK query presets — same composed coverage queries as the OpenFDD Edge Data Model tab.",
                    style={"color": theme["muted"], "fontSize": "13px", "margin": "12px 0 8px"},
                ),
                html.Div(
                    style={"display": "flex", "flexWrap": "wrap", "gap": "4px"},
                    children=[
                        html.Button(
                            title,
                            id={"type": "fdd-preset-btn", "index": preset_id},
                            n_clicks=0,
                            style=BTN_SECONDARY,
                        )
                        for preset_id, title in FDD_PRESET_BUTTONS
                    ],
                ),
                dcc.Loading(
                    id="overview-fdd-preset-loading",
                    type="dot",
                    color=theme["accent"],
                    children=html.Div(id="overview-fdd-preset-result", style={"marginTop": "12px"}),
                ),
            ),
            _section(
                "RCx report",
                theme,
                dcc.Checklist(
                    id="rcx-overlays",
                    options=[{"label": "Show fault overlays on chart previews", "value": "on"}],
                    value=["on"],
                    style={"marginBottom": "10px"},
                ),
                html.Div(
                    style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "12px"},
                    children=[
                        html.Button("Preview data readiness", id="rcx-preview-btn", n_clicks=0, style=BTN_PRIMARY),
                        html.Button("Preview charts", id="rcx-charts-btn", n_clicks=0, style=BTN_PRIMARY),
                        html.Button("Generate DOCX", id="rcx-docx-btn", n_clicks=0, style=BTN_PRIMARY),
                    ],
                ),
                html.Div(id="rcx-readiness", style={"color": theme["muted"], "fontSize": "13px"}),
                html.Div(id="rcx-chart-checkboxes"),
                html.Div(id="rcx-section-checkboxes"),
                html.Div(id="rcx-chart-previews"),
                dcc.Download(id="rcx-download"),
                html.Div(id="rcx-status", style={"color": theme["muted"], "fontSize": "13px", "marginTop": "8px"}),
            ),
        ]
    )


def _fault_pie_figure(pie_data: list[dict], theme: dict) -> go.Figure:
    labels = [str(p.get("fault_code") or "?") for p in pie_data]
    values = [int(p.get("count") or 0) for p in pie_data]
    hover = [
        f"{p.get('fault_code') or '?'} — {p.get('description') or ''} ({int(p.get('count') or 0)})"
        for p in pie_data
    ]
    if not labels:
        fig = go.Figure()
        fig.add_annotation(text="No fault data", showarrow=False, font={"color": theme["muted"]})
    else:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=values,
                    hole=0.4,
                    textinfo="percent",
                    hovertext=hover,
                    hoverinfo="text",
                )
            ]
        )
    fig.update_layout(
        template=theme["plot_template"],
        paper_bgcolor=theme["paper"],
        plot_bgcolor=theme["plot"],
        font={"color": theme["text"]},
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        showlegend=False,
    )
    return fig


def _fault_legend(pie_data: list[dict], theme: dict) -> html.Component:
    if not pie_data:
        return html.P("No active fault codes.", style={"color": theme["muted"], "fontSize": "12px", "margin": "8px 0 0"})
    items = []
    for p in pie_data:
        code = str(p.get("fault_code") or "?")
        desc = str(p.get("description") or code)
        count = int(p.get("count") or 0)
        items.append(
            html.Li(
                [
                    html.Strong(code, style={"color": theme["text"]}),
                    f" — {desc} ",
                    html.Span(f"({count})", style={"color": theme["muted"]}),
                ],
                style={"marginBottom": "4px", "lineHeight": 1.45},
            )
        )
    return html.Div(
        [
            html.Div("Fault codes", style={"fontSize": "11px", "fontWeight": 600, "color": theme["muted"], "marginTop": "4px"}),
            html.Ul(items, style={"margin": "6px 0 0", "paddingLeft": "18px", "fontSize": "12px", "color": theme["muted"]}),
        ]
    )


def _connection_kpi(data: dict, theme: dict) -> html.Div:
    ok = data.get("connection_ok")
    ts = data.get("last_connection_at_local")
    if data.get("live_error"):
        status = html.Div(
            [
                html.Span("✗ ", style={"color": theme["down"]}),
                html.Span("Edge unreachable", style={"fontSize": "14px", "fontWeight": 600}),
            ]
        )
        detail = html.Div(str(data.get("live_error", ""))[:80], style={"fontSize": "11px", "color": theme["muted"], "marginTop": "4px"})
    elif ok and ts:
        status = html.Div(
            [
                html.Span("● ", style={"color": theme["up"]}),
                html.Span("Connected", style={"fontSize": "14px", "fontWeight": 600}),
            ]
        )
        detail = html.Div(f"{ts} {tz_label()}", style={"fontSize": "12px", "marginTop": "6px"})
    elif data.get("credentials_ok") is False and not data.get("last_collect_at"):
        status = html.Div("No credentials", style={"fontSize": "14px", "color": theme["muted"]})
        detail = html.Div("Save Edge on Edge Connections tab", style={"fontSize": "11px", "color": theme["muted"], "marginTop": "4px"})
    else:
        status = html.Div(
            [
                html.Span("○ ", style={"color": theme["accent"], "marginRight": "2px"}),
                html.Span("Offline snapshot", style={"fontSize": "14px"}),
            ]
        )
        detail = html.Div("Start API + credentials for live Edge", style={"fontSize": "11px", "color": theme["muted"], "marginTop": "4px"})
    return html.Div(
        style=_card_style(theme),
        children=[
            html.Div("Last connection", style={"color": theme["muted"], "fontSize": "12px"}),
            status,
            detail,
        ],
    )


def _kpi_cards(data: dict, theme: dict) -> list:
    active = int(data.get("active_faults") or 0)
    pct = float(data.get("fault_pct_change") or 0)
    delta = int(data.get("fault_delta") or 0)
    sign = "+" if pct > 0 else ""
    pct_color = theme["down"] if pct > 0 else theme["up"] if pct < 0 else theme["muted"]
    cards = [
        html.Div(
            style=_card_style(theme),
            children=[
                html.Div("Active faults", style={"color": theme["muted"], "fontSize": "12px"}),
                html.Div(str(active), style={"fontSize": "36px", "fontWeight": 700}),
                html.Div(f"{sign}{pct:.1f}% vs prior check-in ({delta:+d})", style={"color": pct_color, "fontSize": "13px"}),
            ],
        ),
        _connection_kpi(data, theme),
    ]
    if data.get("last_collect_at"):
        local_ts = data.get("last_collect_at_local") or format_ts_local(data.get("last_collect_at"))
        cards.append(
            html.Div(
                style=_card_style(theme),
                children=[
                    html.Div("Last refresh", style={"color": theme["muted"], "fontSize": "12px"}),
                    html.Div(local_ts, style={"fontSize": "14px", "marginTop": "6px", "fontWeight": 600}),
                    html.Div(tz_label(), style={"fontSize": "11px", "color": theme["muted"], "marginTop": "2px"}),
                ],
            )
        )
    op_ov = int(data.get("operator_overrides") or 0)
    cards.append(
        html.Div(
            style=_card_style(theme),
            children=[
                html.Div("P8 overrides", style={"color": theme["muted"], "fontSize": "12px"}),
                html.Div(str(op_ov), style={"fontSize": "28px", "fontWeight": 700}),
                html.Div(str(data.get("overrides_source") or "—"), style={"fontSize": "11px", "color": theme["muted"]}),
            ],
        )
    )
    traffic = str(data.get("traffic") or (data.get("live_edge") or {}).get("traffic") or "—")
    cards.append(
        html.Div(
            style={**_card_style(theme), "borderLeft": f"4px solid {theme['warn']}"},
            children=[
                html.Div("Edge traffic", style={"color": theme["muted"], "fontSize": "12px"}),
                html.Div(traffic.upper(), style={"fontSize": "20px", "fontWeight": 600}),
            ],
        )
    )
    return cards


def _overrides_chart_figure(points: list[dict], theme: dict) -> go.Figure:
    fig = go.Figure()
    if not points:
        fig.add_annotation(text="No P8 overrides in snapshot or live rollup", showarrow=False, font={"color": theme["muted"]})
    else:
        labels = [str(p.get("label") or p.get("object_name") or "?") for p in points[:20]]
        fig.add_trace(
            go.Bar(
                x=labels,
                y=[1] * len(labels),
                orientation="v",
                marker_color=theme["warn"],
                text=[str(p.get("value") or "") for p in points[:20]],
                textposition="outside",
            )
        )
        fig.update_layout(bargap=0.35)
    fig.update_layout(
        template=theme["plot_template"],
        paper_bgcolor=theme["paper"],
        plot_bgcolor=theme["plot"],
        font={"color": theme["text"], "size": 11},
        margin={"l": 8, "r": 8, "t": 8, "b": 120},
        xaxis={"tickangle": -35},
        yaxis={"visible": False, "showgrid": False},
        showlegend=False,
    )
    return fig


def _source_html(data: dict, theme: dict) -> html.Div:
    if data.get("connection_ok") and data.get("credentials_ok"):
        label = "Live Edge"
        color = theme["up"]
        detail = f"Connected · {data.get('last_connection_at_local') or ''} {tz_label()}".strip()
    elif data.get("live_error"):
        label = "Edge unreachable"
        color = theme["warn"]
        detail = str(data["live_error"])[:120]
    elif data.get("last_collect_at_local"):
        label = "Cached snapshot"
        color = theme["muted"]
        detail = f"Last refresh {data.get('last_collect_at_local')} {tz_label()}"
    else:
        label = "No data"
        color = theme["muted"]
        detail = "Connect an Edge and click Refresh data"
    return html.Div(
        [html.Span(f"{label} — ", style={"fontWeight": 600, "color": color}), html.Span(detail, style={"color": theme["muted"]})],
        style={"fontSize": "12px"},
    )


def _table_styles(theme: dict) -> tuple[dict, dict, dict]:
    table = {
        "width": "100%",
        "fontSize": "13px",
        "borderCollapse": "collapse",
        "tableLayout": "fixed",
    }
    th = {
        "textAlign": "left",
        "padding": "8px 10px",
        "borderBottom": f"2px solid {theme['grid']}",
        "color": theme["muted"],
        "fontSize": "12px",
        "fontWeight": "600",
    }
    td = {
        "padding": "8px 10px",
        "borderBottom": f"1px solid {theme['grid']}",
        "verticalAlign": "top",
        "wordBreak": "break-word",
    }
    return table, th, td


def _data_table(columns: list[str], rows: list[dict], theme: dict, *, max_rows: int = 40) -> html.Table:
    table_style, th_style, td_style = _table_styles(theme)
    header = html.Tr([html.Th(col, style=th_style) for col in columns])
    body = []
    for row in rows[:max_rows]:
        if not isinstance(row, dict):
            continue
        body.append(
            html.Tr([html.Td(str(row.get(col, "") or "—"), style=td_style) for col in columns])
        )
    return html.Table([html.Thead(header), html.Tbody(body)], style=table_style)


def _p8_section(overrides: list[dict], theme: dict) -> html.Component:
    if not overrides:
        return html.Div()
    return html.Div(
        [
            html.P(
                "BACnet priority-array slot 8 (operator override) from Edge live rollup or portfolio/data/overrides_daily.csv.",
                style={"color": theme["muted"], "fontSize": "13px", "marginTop": 0},
            ),
            dcc.Graph(
                figure=_overrides_chart_figure(overrides, theme),
                config={"displayModeBar": False},
                style={"height": "280px"},
            ),
        ]
    )


def _fdd_rules_html(data: dict, theme: dict) -> html.Div:
    rules = data.get("rules") or []
    warnings = data.get("warnings") or []
    if not rules:
        return html.P(
            (warnings[0] if warnings else "No FDD rules — start Central API and connect Edge."),
            style={"color": theme["muted"]},
        )
    columns = ("Rule", "Code", "Description", "Type", "Active", "Fault hrs")
    table_style, th_style, td_style = _table_styles(theme)
    header = html.Tr([html.Th(c, style=th_style) for c in columns])
    body = []
    for r in rules[:25]:
        code = str(r.get("fault_code") or "")
        desc = str(r.get("fault_description") or lookup_fault_description(code) or "—")
        body.append(
            html.Tr(
                [
                    html.Td(str(r.get("fault_name") or r.get("rule_id") or ""), style=td_style),
                    html.Td(code, style=td_style),
                    html.Td(desc, style=td_style),
                    html.Td(str(r.get("equipment_type") or "—"), style=td_style),
                    html.Td(str(r.get("active_fault_count") or 0), style=td_style),
                    html.Td(f"{float(r.get('elapsed_fault_hours') or 0):.1f}", style=td_style),
                ]
            )
        )
    return html.Div(
        [
            html.P(f"{data.get('rules_configured', len(rules))} rules configured", style={"color": theme["muted"], "fontSize": "13px"}),
            html.Table([html.Thead(header), html.Tbody(body)], style=table_style),
        ]
    )


def _fdd_preset_result_html(result: dict, theme: dict) -> html.Div:
    if not result:
        return html.Div()
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    title = str(result.get("title") or result.get("preset_id") or "Preset")
    desc = str(result.get("description") or "")
    if not rows:
        return html.P(f"{title}: no rows.", style={"color": theme["muted"], "fontSize": "13px"})
    if not columns and rows and isinstance(rows[0], dict):
        columns = list(rows[0].keys())
    return html.Div(
        [
            html.H4(title, style={"margin": "0 0 4px", "fontSize": "15px"}),
            html.P(desc, style={"color": theme["muted"], "fontSize": "12px", "margin": "0 0 8px"}) if desc else None,
            html.P(f"{result.get('row_count', len(rows))} row(s)", style={"color": theme["muted"], "fontSize": "12px"}),
            _data_table([str(c) for c in columns], rows, theme),
        ]
    )


def register_overview_callbacks(app, theme: dict) -> None:
    @app.callback(
        Output("overview-kpi-row", "children"),
        Output("overview-fault-pie", "figure"),
        Output("overview-fault-legend", "children"),
        Output("overview-p8-section", "children"),
        Output("overview-mech-narrative", "children"),
        Output("overview-fdd-rules", "children"),
        Output("overview-source", "children"),
        Input("overview-site", "value"),
        Input("overview-hours", "value"),
        Input("main-tabs", "value"),
        Input("refresh-interval", "n_intervals"),
        Input("refresh-data-btn", "n_clicks"),
        Input("edge-save-btn", "n_clicks"),
        Input("edge-registry-revision", "data"),
    )
    def refresh_dashboard(site_id, hours, tab, _n, _refresh, _save, _revision):
        if tab and tab != "dashboard":
            return (no_update,) * 7
        empty_fig = _fault_pie_figure([], theme)
        empty_legend = _fault_legend([], theme)
        empty_p8 = _p8_section([], theme)
        if not site_id:
            empty = html.P("Connect an Edge on the Edge Connections tab.", style={"color": theme["muted"]})
            return [], empty_fig, empty_legend, empty_p8, empty, empty, _source_html({}, theme)

        data = _load_overview(site_id)
        kpis = _kpi_cards(data, theme)
        pie_rows = data.get("fault_pie") or []
        fig = _fault_pie_figure(pie_rows, theme)
        legend = _fault_legend(pie_rows, theme)
        p8_section = _p8_section(data.get("overrides_p8") or [], theme)

        narrative = data.get("mechanical_narrative")
        brick_name = data.get("brick_site_name")
        if narrative:
            header_children = [html.H3("Building summary", style={"margin": "0 0 10px", "fontSize": "15px"})]
            if brick_name:
                header_children.append(
                    html.Div(
                        f"BRICK site: {brick_name}"
                        + (f" ({data.get('brick_site_id')})" if data.get("brick_site_id") else ""),
                        style={"fontSize": "12px", "color": theme["accent"], "marginBottom": "8px", "fontWeight": 600},
                    )
                )
            mech = html.Div(
                header_children
                + [html.P(narrative, style={"lineHeight": 1.55, "whiteSpace": "pre-wrap", "margin": 0})]
            )
        elif data.get("live_error"):
            mech = html.P(f"Building summary unavailable: {data['live_error']}", style={"color": theme["warn"]})
        else:
            mech = html.P("Connect an Edge and save credentials to load the BRICK building summary.", style={"color": theme["muted"]})

        fdd_data: dict = {"rules": [], "warnings": ["Central API not running — FDD rules need API + Edge."]}
        try:
            fdd_data = _api_get(f"/api/central/fdd-analytics/{site_id}?hours={hours or 24}")
        except Exception:
            pass
        fdd_panel = _fdd_rules_html(fdd_data, theme)

        return kpis, fig, legend, p8_section, mech, fdd_panel, _source_html(data, theme)

    @app.callback(
        Output("overview-fdd-preset-result", "children"),
        Input({"type": "fdd-preset-btn", "index": ALL}, "n_clicks"),
        State("overview-site", "value"),
        prevent_initial_call=True,
    )
    def run_fdd_preset(n_clicks_list, site_id):
        if not site_id or not ctx.triggered_id:
            return no_update
        preset_id = ctx.triggered_id.get("index") if isinstance(ctx.triggered_id, dict) else None
        if not preset_id:
            return no_update
        try:
            result = _api_get(f"/api/central/fdd-preset/{site_id}/{preset_id}")
            return _fdd_preset_result_html(result, theme)
        except Exception as exc:
            return html.P(str(exc)[:300], style={"color": theme["warn"], "fontSize": "13px"})

    @app.callback(
        Output("rcx-readiness", "children"),
        Output("rcx-chart-checkboxes", "children"),
        Output("rcx-section-checkboxes", "children"),
        Input("rcx-preview-btn", "n_clicks"),
        State("overview-site", "value"),
        State("overview-hours", "value"),
        State("rcx-overlays", "value"),
        prevent_initial_call=True,
    )
    def rcx_preview(_n, site_id, hours, overlays):
        if not site_id:
            return "Select a site on Edge Connections.", no_update, no_update
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
                f"Active faults: {fs.get('active_faults')} · Fault hours: {fs.get('total_fault_hours')} · "
                f"Disabled charts: {len(out.get('disabled_charts') or [])}"
            )
            charts = dcc.Checklist(
                id="rcx-charts-selected",
                options=[{"label": c.get("title"), "value": c.get("chart_id")} for c in (out.get("available_charts") or [])],
                value=[c.get("chart_id") for c in (out.get("available_charts") or [])],
            )
            disabled = html.Ul([html.Li(f"{c.get('title')}: {c.get('reason')}") for c in (out.get("disabled_charts") or [])])
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
        State("overview-site", "value"),
        State("overview-hours", "value"),
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
                                html.Strong(p.get("title")),
                                html.Img(src=f"data:image/png;base64,{b64}", style={"maxWidth": "100%", "marginTop": "6px"}),
                            ],
                            style={"marginBottom": "16px"},
                        )
                    )
            return imgs or html.P("No chart previews (API/matplotlib/Edge data required).", style={"color": theme["muted"]})
        except Exception as exc:
            return str(exc)

    @app.callback(
        Output("rcx-download", "data"),
        Output("rcx-status", "children"),
        Input("rcx-docx-btn", "n_clicks"),
        State("overview-site", "value"),
        State("overview-hours", "value"),
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
                {"site_id": site_id, "hours": hours or 24, "charts": charts or [], "sections": sections or []}
            ).encode("utf-8")
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=180) as resp:
                blob = resp.read()
            return dcc.send_bytes(blob, f"openfdd-rcx-{site_id}.docx"), "DOCX download started."
        except Exception as exc:
            return no_update, str(exc)
