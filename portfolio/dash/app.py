#!/usr/bin/env python3
"""OpenFDD RCx Central — multi-edge analytics and RCx report builder (Dash)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import dash
from dash import Input, Output, State, dcc, html
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "page_bg": "#020617",
        "card_bg": "#0f172a",
        "text": "#e2e8f0",
        "muted": "#94a3b8",
        "accent": "#2563eb",
        "plot_template": "plotly_dark",
        "paper": "#0f172a",
        "plot": "#0f172a",
        "grid": "#1e293b",
        "up": "#22c55e",
        "down": "#ef4444",
        "warn": "#f59e0b",
    },
    "light": {
        "page_bg": "#f8fafc",
        "card_bg": "#ffffff",
        "text": "#0f172a",
        "muted": "#64748b",
        "accent": "#2563eb",
        "plot_template": "plotly_white",
        "paper": "#ffffff",
        "plot": "#f1f5f9",
        "grid": "#e2e8f0",
        "up": "#16a34a",
        "down": "#dc2626",
        "warn": "#d97706",
    },
}


def _read_csv(name: str) -> pd.DataFrame:
    path = DATA / name
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


def _traffic_color(traffic: str, theme: dict[str, str]) -> str:
    base = {"green": theme["up"], "yellow": theme["warn"], "red": theme["down"]}
    return base.get(str(traffic or "").lower(), theme["muted"])


def _delta_parts(
    current: float,
    prior: float,
    theme: dict[str, str],
    *,
    up_is_bad: bool = True,
) -> tuple[str, str]:
    delta = current - prior
    sign = "+" if delta >= 0 else ""
    if delta == 0:
        color = theme["muted"]
    elif up_is_bad:
        color = theme["down"] if delta > 0 else theme["up"]
    else:
        color = theme["up"] if delta > 0 else theme["down"]
    return f"{sign}{delta:.1f}", color


def _latest_checkins(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    return df.sort_values("collected_at").groupby("site_id", as_index=False).tail(1)


def _prior_checkins(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    return df.sort_values("collected_at").groupby("site_id", as_index=False).nth(-2)


def _run_hour_series(df: pd.DataFrame, site_id: str) -> pd.DataFrame:
    if df.empty:
        return df
    sub = df[df["site_id"] == site_id].copy()
    if sub.empty:
        return sub
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    return sub.sort_values(["equipment_id", "collected_at"])


def _site_cards(theme: dict[str, str]) -> list:
    checkins = _read_csv("checkins.csv")
    if checkins.empty:
        return [html.P("No data yet — run portfolio collector.", style={"color": theme["muted"]})]

    latest = _latest_checkins(checkins)
    prior = _prior_checkins(checkins)
    fan_df = _read_csv("run_hours_daily.csv")
    cards = []

    for _, row in latest.iterrows():
        sid = row.get("site_id")
        site_runs = fan_df[fan_df["site_id"] == sid] if not fan_df.empty else fan_df
        fan_total = float(site_runs["fan_run_hours"].fillna(0).sum()) if not site_runs.empty else 0.0

        prior_fan = 0.0
        if not site_runs.empty:
            last_two = site_runs.sort_values("collected_at").groupby("equipment_id").tail(2)

            def _equip_delta(g: pd.DataFrame) -> float:
                if len(g) < 2:
                    return 0.0
                g = g.sort_values("collected_at")
                return float(g.iloc[-1]["fan_run_hours"]) - float(g.iloc[0]["fan_run_hours"])

            prior_fan = float(last_two.groupby("equipment_id", group_keys=False).apply(_equip_delta).sum())

        delta_txt, delta_color = _delta_parts(fan_total, fan_total - prior_fan, theme)

        prev_row = prior[prior["site_id"] == sid]
        prev_alerts = int(prev_row["alert_count"].iloc[0]) if not prev_row.empty else 0
        prev_overrides = int(prev_row["operator_overrides"].iloc[0]) if not prev_row.empty else 0
        alert_delta, alert_color = _delta_parts(
            float(row.get("alert_count") or 0), float(prev_alerts), theme
        )
        ovr_delta, ovr_color = _delta_parts(
            float(row.get("operator_overrides") or 0), float(prev_overrides), theme
        )

        cards.append(
            html.Div(
                style={
                    "borderLeft": f"6px solid {_traffic_color(row.get('traffic'), theme)}",
                    "padding": "12px 16px",
                    "marginBottom": "8px",
                    "background": theme["card_bg"],
                    "borderRadius": "8px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.12)",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between"},
                        children=[
                            html.Strong(
                                f"{row.get('site_name') or sid} ({sid})",
                                style={"color": theme["text"]},
                            ),
                            html.Span(
                                str(row.get("traffic") or "—").upper(),
                                style={"color": _traffic_color(row.get("traffic"), theme), "fontWeight": 600},
                            ),
                        ],
                    ),
                    html.Div(
                        style={"fontSize": "13px", "color": theme["muted"], "marginTop": "4px"},
                        children=[
                            "Alerts ",
                            html.Span(f"{int(row.get('alert_count') or 0)}", style={"color": theme["text"]}),
                            html.Span(f" ({alert_delta})", style={"color": alert_color, "marginRight": "8px"}),
                            f"· FDD {int(row.get('fdd_alert_count') or 0)} · P8 ",
                            html.Span(f"{int(row.get('operator_overrides') or 0)}", style={"color": theme["text"]}),
                            html.Span(f" ({ovr_delta})", style={"color": ovr_color}),
                        ],
                    ),
                    html.Div(
                        style={"marginTop": "6px", "fontSize": "15px"},
                        children=[
                            html.Span("Fan hours ", style={"color": theme["muted"]}),
                            html.Span(f"{fan_total:.1f}h ", style={"fontWeight": 700, "color": theme["text"]}),
                            html.Span(
                                delta_txt,
                                style={
                                    "color": delta_color,
                                    "fontWeight": 700,
                                    "fontFamily": "ui-monospace, monospace",
                                },
                            ),
                        ],
                    ),
                ],
            )
        )
    return cards


def _figure_layout(fig: go.Figure, theme: dict[str, str], title: str) -> go.Figure:
    fig.update_layout(
        template=theme["plot_template"],
        paper_bgcolor=theme["paper"],
        plot_bgcolor=theme["plot"],
        title=title,
        font={"color": theme["text"]},
        legend={"orientation": "h", "font": {"color": theme["text"]}},
        margin={"l": 48, "r": 24, "t": 52, "b": 40},
        xaxis={"gridcolor": theme["grid"]},
        yaxis={"gridcolor": theme["grid"]},
    )
    return fig


def _annotate_last_delta(fig: go.Figure, x, y, delta: float, theme: dict[str, str]) -> None:
    if pd.isna(delta) or delta == 0:
        return
    sign = "+" if delta > 0 else ""
    color = theme["down"] if delta > 0 else theme["up"]
    fig.add_annotation(
        x=x,
        y=y,
        text=f"{sign}{delta:.1f}",
        showarrow=True,
        arrowhead=2,
        arrowcolor=color,
        font={"color": color, "size": 11, "family": "ui-monospace, monospace"},
        bgcolor=theme["card_bg"],
        bordercolor=color,
        borderwidth=1,
        ay=-28 if delta > 0 else 28,
    )


def _stock_style_figure(
    df: pd.DataFrame,
    metric: str,
    title: str,
    theme: dict[str, str],
) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.add_annotation(text="No run-hour data", showarrow=False, font={"color": theme["muted"]})
        return _figure_layout(fig, theme, title)

    for equipment_id, grp in df.groupby("equipment_id"):
        grp = grp.sort_values("collected_at")
        y = pd.to_numeric(grp[metric], errors="coerce").fillna(0)
        label = str(grp["equipment_name"].iloc[-1] if "equipment_name" in grp else equipment_id)
        fig.add_trace(
            go.Scatter(
                x=grp["collected_at"],
                y=y,
                mode="lines+markers",
                name=label,
                line={"width": 2.5},
            ),
            secondary_y=False,
        )
        if len(y) >= 2:
            delta = y.diff().fillna(0)
            colors = [theme["down"] if d > 0 else theme["up"] if d < 0 else theme["muted"] for d in delta]
            fig.add_trace(
                go.Bar(
                    x=grp["collected_at"],
                    y=delta,
                    name=f"Δ {equipment_id}",
                    marker_color=colors,
                    opacity=0.45,
                    showlegend=False,
                ),
                secondary_y=True,
            )
            last_delta = float(delta.iloc[-1])
            _annotate_last_delta(
                fig,
                grp["collected_at"].iloc[-1],
                float(y.iloc[-1]),
                last_delta,
                theme,
            )

    fig.update_yaxes(title_text="Hours", secondary_y=False)
    fig.update_yaxes(title_text="Δ hours (+/−)", secondary_y=True)
    return _figure_layout(fig, theme, f"{title}  ·  green ▼ red ▲")


def _site_fault_total_figure(site_id: str, theme: dict[str, str]) -> go.Figure:
    """Total active faults per site over portfolio collects (stock-style line + Δ bars)."""
    checkins = _read_csv("checkins.csv")
    fig = go.Figure()
    if checkins.empty or not site_id:
        return _figure_layout(fig, theme, "Site fault total — no data")

    sub = checkins[checkins["site_id"] == site_id].copy()
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    sub = sub.sort_values("collected_at")
    y = pd.to_numeric(sub["alert_count"], errors="coerce").fillna(0)

    fig.add_trace(
        go.Scatter(
            x=sub["collected_at"],
            y=y,
            mode="lines+markers",
            name="Active faults (total)",
            line={"color": theme["warn"], "width": 2.5},
        )
    )
    if len(y) >= 2:
        delta = y.diff().fillna(0)
        colors = [theme["down"] if d > 0 else theme["up"] if d < 0 else theme["muted"] for d in delta]
        fig.add_trace(
            go.Bar(
                x=sub["collected_at"],
                y=delta,
                marker_color=colors,
                opacity=0.35,
                showlegend=False,
                name="Δ faults",
            )
        )
        _annotate_last_delta(fig, sub["collected_at"].iloc[-1], float(y.iloc[-1]), float(delta.iloc[-1]), theme)

    if "agent_checkin" in sub.columns:
        agent_rows = sub[sub["agent_checkin"].astype(str).str.lower().isin({"true", "1", "yes"})]
        if not agent_rows.empty:
            fig.add_trace(
                go.Scatter(
                    x=agent_rows["collected_at"],
                    y=pd.to_numeric(agent_rows["alert_count"], errors="coerce").fillna(0),
                    mode="markers",
                    name="AI agent check-in",
                    marker={"symbol": "star", "size": 14, "color": theme["accent"], "line": {"width": 1, "color": theme["text"]}},
                )
            )

    fig.update_layout(xaxis_title="Collection time", yaxis_title="Active faults (site total)")
    return _figure_layout(fig, theme, f"Site fault total (+/−) — {site_id}")


def _fault_figure(site_id: str, theme: dict[str, str]) -> go.Figure:
    df = _read_csv("faults_daily.csv")
    fig = go.Figure()
    if df.empty or not site_id:
        return _figure_layout(fig, theme, "Fault codes — no data")

    sub = df[df["site_id"] == site_id].copy()
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    for code, grp in sub.groupby("fault_code"):
        grp = grp.sort_values("collected_at")
        y = pd.to_numeric(grp["active_count"], errors="coerce").fillna(0)
        fig.add_trace(
            go.Scatter(x=grp["collected_at"], y=y, mode="lines+markers", name=str(code), line={"width": 2})
        )
        if len(y) >= 2:
            delta = y.diff().fillna(0)
            colors = [theme["down"] if d > 0 else theme["up"] if d < 0 else theme["muted"] for d in delta]
            fig.add_trace(
                go.Bar(
                    x=grp["collected_at"],
                    y=delta,
                    opacity=0.3,
                    marker_color=colors,
                    showlegend=False,
                    name=f"Δ {code}",
                )
            )

    fig.update_layout(xaxis_title="Collection time", yaxis_title="Active alerts")
    return _figure_layout(fig, theme, f"Fault codes by type (+/−) — {site_id}")


def _override_figure(site_id: str, theme: dict[str, str]) -> go.Figure:
    checkins = _read_csv("checkins.csv")
    fig = go.Figure()
    if checkins.empty or not site_id:
        return _figure_layout(fig, theme, "P8 overrides — no data")

    sub = checkins[checkins["site_id"] == site_id].copy()
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    sub = sub.sort_values("collected_at")
    y = pd.to_numeric(sub["operator_overrides"], errors="coerce").fillna(0)
    fig.add_trace(
        go.Scatter(
            x=sub["collected_at"],
            y=y,
            mode="lines+markers",
            name="P8 operator overrides",
            line={"color": theme["warn"], "width": 2.5},
            fill="tozeroy",
        )
    )
    if len(y) >= 2:
        delta = y.diff().fillna(0)
        colors = [theme["down"] if d > 0 else theme["up"] if d < 0 else theme["muted"] for d in delta]
        fig.add_trace(
            go.Bar(
                x=sub["collected_at"],
                y=delta,
                marker_color=colors,
                opacity=0.4,
                showlegend=False,
                name="Δ overrides",
            )
        )
        _annotate_last_delta(fig, sub["collected_at"].iloc[-1], float(y.iloc[-1]), float(delta.iloc[-1]), theme)

    fig.update_layout(xaxis_title="Collection time", yaxis_title="Override points")
    return _figure_layout(fig, theme, f"P8 operator overrides (+/−) — {site_id}")


def _site_options() -> list[dict[str, str]]:
    checkins = _read_csv("checkins.csv")
    if checkins.empty:
        return []
    return [{"label": s, "value": s} for s in sorted(checkins["site_id"].dropna().unique())]


app = dash.Dash(__name__, title="OpenFDD RCx Central", suppress_callback_exceptions=True)

_sites = _site_options()

def _overview_tab() -> html.Div:
    return html.Div(
        children=[
            html.Div(id="overview-intro"),
            html.Div(id="site-cards"),
            html.Div(
                id="chart-grid",
                style={"display": "grid", "gridTemplateColumns": "280px 1fr", "gap": "16px", "marginTop": "20px"},
                children=[
                    html.Div(
                        id="sidebar",
                        children=[
                            html.Label("Site", id="site-label"),
                            dcc.Dropdown(
                                id="site-select",
                                options=_sites,
                                value=_sites[0]["value"] if _sites else None,
                                clearable=False,
                            ),
                            html.Label("Metric", id="metric-label", style={"marginTop": "12px"}),
                            dcc.RadioItems(
                                id="metric-select",
                                options=[
                                    {"label": "Fan run hours", "value": "fan_run_hours"},
                                    {"label": "System run hours", "value": "system_run_hours"},
                                    {"label": "Unoccupied fan hours", "value": "unoccupied_fan_hours"},
                                ],
                                value="fan_run_hours",
                            ),
                            html.P(
                                id="delta-legend",
                                children="Δ bars: green = hours down (good) · red = hours up",
                                style={"fontSize": "12px", "marginTop": "12px"},
                            ),
                        ],
                    ),
                    dcc.Graph(id="run-hours-chart"),
                ],
            ),
            dcc.Graph(id="site-fault-total-chart", style={"marginTop": "16px"}),
            dcc.Graph(id="fault-trend-chart", style={"marginTop": "16px"}),
            dcc.Graph(id="override-chart", style={"marginTop": "16px"}),
        ]
    )


app.layout = html.Div(
    id="app-root",
    children=[
        dcc.Store(id="theme-store", data="dark"),
        dcc.Interval(id="refresh-interval", interval=120_000, n_intervals=0),
        html.Div(id="header-row"),
        dcc.Tabs(
            id="main-tabs",
            value="overview",
            children=[
                dcc.Tab(label="Overview", value="overview", children=[_overview_tab()]),
                dcc.Tab(label="Edge Connections", value="edges", children=[html.Div(id="edges-tab")]),
                dcc.Tab(label="Mechanical Summary", value="mechanical", children=[html.Div(id="mech-tab")]),
                dcc.Tab(label="FDD Analytics", value="fdd", children=[html.Div(id="fdd-tab")]),
                dcc.Tab(label="Trend Explorer", value="trends", children=[html.Div(id="trends-tab")]),
                dcc.Tab(label="RCx Report Builder", value="rcx", children=[html.Div(id="rcx-tab")]),
                dcc.Tab(label="Validation Runs", value="validation", children=[html.Div(id="val-tab")]),
                dcc.Tab(label="Settings", value="settings", children=[html.Div(id="settings-tab")]),
            ],
        ),
    ],
)


@app.callback(
    Output("header-row", "children"),
    Output("app-root", "style"),
    Input("theme-store", "data"),
)
def render_header(theme_key: str):
    theme = THEMES.get(theme_key or "dark", THEMES["dark"])
    other = "light" if theme_key == "dark" else "dark"
    header = html.Div(
        style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "flex-start",
            "flexWrap": "wrap",
            "gap": "12px",
            "marginBottom": "8px",
        },
        children=[
            html.Div(
                children=[
                    html.H1("OpenFDD RCx Central", style={"margin": 0, "color": theme["text"]}),
                    html.P(
                        "Local analyst tool · multi-edge RCx analytics · read-only toward OpenFDD Edge",
                        style={"color": theme["muted"], "margin": "4px 0 0"},
                    ),
                ]
            ),
            html.Div(
                style={"display": "flex", "gap": "8px", "alignItems": "center"},
                children=[
                    html.Button(
                        f"{'☀️ Light' if theme_key == 'dark' else '🌙 Dark'} mode",
                        id="theme-toggle",
                        n_clicks=0,
                        style={
                            "background": theme["card_bg"],
                            "color": theme["text"],
                            "border": f"1px solid {theme['grid']}",
                            "padding": "8px 14px",
                            "borderRadius": "6px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Button(
                        "Collect now",
                        id="collect-btn",
                        n_clicks=0,
                        style={
                            "background": theme["accent"],
                            "color": "white",
                            "border": "none",
                            "padding": "8px 16px",
                            "borderRadius": "6px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Span(id="collect-status", style={"color": theme["muted"]}),
                ],
            ),
        ],
    )
    root_style = {
        "fontFamily": "system-ui, sans-serif",
        "background": theme["page_bg"],
        "color": theme["text"],
        "minHeight": "100vh",
        "padding": "20px",
    }
    return header, root_style


@app.callback(
    Output("theme-store", "data"),
    Input("theme-toggle", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def toggle_theme(n_clicks: int, current: str):
    return "light" if (current or "dark") == "dark" else "dark"


@app.callback(
    Output("site-cards", "children"),
    Input("theme-store", "data"),
    Input("refresh-interval", "n_intervals"),
    Input("collect-btn", "n_clicks"),
)
def refresh_cards(theme_key: str, _n: int, _btn: int):
    theme = THEMES.get(theme_key or "dark", THEMES["dark"])
    return _site_cards(theme)


@app.callback(
    Output("site-label", "style"),
    Output("metric-label", "style"),
    Output("metric-select", "style"),
    Output("delta-legend", "style"),
    Input("theme-store", "data"),
)
def theme_sidebar(theme_key: str):
    theme = THEMES.get(theme_key or "dark", THEMES["dark"])
    label_style = {"color": theme["text"]}
    metric_label_style = {"marginTop": "12px", "color": theme["text"]}
    radio_style = {"color": theme["text"]}
    legend_style = {"fontSize": "12px", "color": theme["muted"], "marginTop": "12px"}
    return label_style, metric_label_style, radio_style, legend_style


@app.callback(
    Output("collect-status", "children"),
    Input("collect-btn", "n_clicks"),
    prevent_initial_call=True,
)
def run_collect(n_clicks: int):
    if not n_clicks:
        return ""
    script = ROOT.parent / "scripts" / "portfolio_collect.py"
    py = Path(sys.executable)
    venv_py = ROOT.parent / ".venv" / "bin" / "python"
    if venv_py.is_file():
        py = venv_py
    try:
        proc = subprocess.run(
            [str(py), str(script)],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if proc.returncode != 0:
            return f"Collect failed: {proc.stderr[:200] or proc.stdout[:200]}"
        return "Collect finished — charts refresh automatically."
    except Exception as exc:
        return f"Collect error: {exc}"


@app.callback(
    Output("run-hours-chart", "figure"),
    Output("site-fault-total-chart", "figure"),
    Output("fault-trend-chart", "figure"),
    Output("override-chart", "figure"),
    Input("site-select", "value"),
    Input("metric-select", "value"),
    Input("theme-store", "data"),
    Input("refresh-interval", "n_intervals"),
    Input("collect-btn", "n_clicks"),
)
def update_charts(
    site_id: str | None,
    metric: str,
    theme_key: str,
    _n: int,
    _btn: int,
):
    theme = THEMES.get(theme_key or "dark", THEMES["dark"])
    runs = _read_csv("run_hours_daily.csv")
    sub = _run_hour_series(runs, site_id or "") if site_id and not runs.empty else pd.DataFrame()
    run_fig = _stock_style_figure(
        sub,
        metric or "fan_run_hours",
        f"Equipment run hours — {site_id or '—'}",
        theme,
    )
    sid = site_id or ""
    return (
        run_fig,
        _site_fault_total_figure(sid, theme),
        _fault_figure(sid, theme),
        _override_figure(sid, theme),
    )


@app.callback(
    Output("overview-intro", "children"),
    Output("edges-tab", "children"),
    Output("mech-tab", "children"),
    Output("fdd-tab", "children"),
    Output("trends-tab", "children"),
    Output("rcx-tab", "children"),
    Output("val-tab", "children"),
    Output("settings-tab", "children"),
    Input("theme-store", "data"),
)
def render_tab_shells(theme_key: str):
    from portfolio.dash.rcx_pages import (
        edge_connections_layout,
        fdd_analytics_layout,
        mechanical_layout,
        overview_intro,
        rcx_builder_layout,
        settings_layout,
        trend_explorer_layout,
        validation_layout,
    )

    theme = THEMES.get(theme_key or "dark", THEMES["dark"])
    return (
        overview_intro(theme),
        edge_connections_layout(theme),
        mechanical_layout(theme),
        fdd_analytics_layout(theme),
        trend_explorer_layout(theme),
        rcx_builder_layout(theme),
        validation_layout(theme),
        settings_layout(theme),
    )


def main() -> None:
    from portfolio.dash.rcx_callbacks import register_rcx_callbacks

    register_rcx_callbacks(app)
    app.run(host="0.0.0.0", port=8050, debug=False)


if __name__ == "__main__":
    main()
