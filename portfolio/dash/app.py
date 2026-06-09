#!/usr/bin/env python3
"""Open-FDD central portfolio dashboard — run-hour & fault rollups across sites."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import dash
from dash import Input, Output, dcc, html
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _read_csv(name: str) -> pd.DataFrame:
    path = DATA / name
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


def _traffic_color(traffic: str) -> str:
    return {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}.get(
        str(traffic or "").lower(), "#64748b"
    )


def _delta_badge(current: float, prior: float) -> tuple[str, str]:
    if prior == 0 and current == 0:
        return "0.0", "#64748b"
    delta = current - prior
    sign = "+" if delta >= 0 else ""
    color = "#22c55e" if delta <= 0 else "#ef4444"
    return f"{sign}{delta:.1f}", color


def _latest_checkins(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    return df.sort_values("collected_at").groupby("site_id", as_index=False).tail(1)


def _run_hour_series(df: pd.DataFrame, site_id: str, metric: str) -> pd.DataFrame:
    if df.empty:
        return df
    sub = df[df["site_id"] == site_id].copy()
    if sub.empty:
        return sub
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    sub = sub.sort_values(["equipment_id", "collected_at"])
    return sub


def build_layout() -> html.Div:
    checkins = _read_csv("checkins.csv")
    sites = sorted(checkins["site_id"].dropna().unique()) if not checkins.empty else []
    latest = _latest_checkins(checkins)

    cards = []
    for _, row in latest.iterrows():
        sid = row.get("site_id")
        fan_df = _read_csv("run_hours_daily.csv")
        site_runs = fan_df[fan_df["site_id"] == sid] if not fan_df.empty else fan_df
        fan_total = float(site_runs["fan_run_hours"].fillna(0).sum()) if not site_runs.empty else 0.0
        prior = (
            site_runs.sort_values("collected_at").groupby("equipment_id").tail(2)
            if not site_runs.empty
            else pd.DataFrame()
        )
        prior_fan = 0.0
        if not prior.empty:
            last_two = prior.groupby("equipment_id").apply(
                lambda g: g.sort_values("collected_at").iloc[-1]["fan_run_hours"]
                - g.sort_values("collected_at").iloc[0]["fan_run_hours"]
                if len(g) >= 2
                else 0.0
            )
            prior_fan = float(last_two.sum())
        delta_txt, delta_color = _delta_badge(fan_total, fan_total - prior_fan)
        cards.append(
            html.Div(
                className="site-card",
                style={
                    "borderLeft": f"6px solid {_traffic_color(row.get('traffic'))}",
                    "padding": "12px 16px",
                    "marginBottom": "8px",
                    "background": "#0f172a",
                    "borderRadius": "8px",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between"},
                        children=[
                            html.Strong(f"{row.get('site_name') or sid} ({sid})"),
                            html.Span(
                                str(row.get("traffic") or "—").upper(),
                                style={"color": _traffic_color(row.get("traffic"))},
                            ),
                        ],
                    ),
                    html.Div(
                        style={"fontSize": "13px", "color": "#94a3b8", "marginTop": "4px"},
                        children=[
                            f"Alerts {int(row.get('alert_count') or 0)} · "
                            f"FDD {int(row.get('fdd_alert_count') or 0)} · "
                            f"P8 overrides {int(row.get('operator_overrides') or 0)}"
                        ],
                    ),
                    html.Div(
                        style={"marginTop": "6px"},
                        children=[
                            html.Span("Fan hours ", style={"color": "#94a3b8"}),
                            html.Span(f"{fan_total:.1f}h ", style={"fontWeight": 600}),
                            html.Span(delta_txt, style={"color": delta_color, "fontWeight": 600}),
                        ],
                    ),
                ],
            )
        )

    return html.Div(
        style={
            "fontFamily": "system-ui, sans-serif",
            "background": "#020617",
            "color": "#e2e8f0",
            "minHeight": "100vh",
            "padding": "20px",
        },
        children=[
            html.H1("Open-FDD Portfolio", style={"marginBottom": "4px"}),
            html.P(
                "Central analytics for mechanical run hours, fault codes, and BACnet P8 operator overrides.",
                style={"color": "#94a3b8", "marginTop": 0},
            ),
            html.Div(
                style={"display": "flex", "gap": "12px", "margin": "16px 0", "flexWrap": "wrap"},
                children=[
                    html.Button(
                        "Collect now",
                        id="collect-btn",
                        n_clicks=0,
                        style={
                            "background": "#2563eb",
                            "color": "white",
                            "border": "none",
                            "padding": "8px 16px",
                            "borderRadius": "6px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Span(id="collect-status", style={"color": "#94a3b8", "alignSelf": "center"}),
                ],
            ),
            html.Div(id="site-cards", children=cards or [html.P("No data yet — run portfolio collector.")]),
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "280px 1fr", "gap": "16px", "marginTop": "20px"},
                children=[
                    html.Div(
                        children=[
                            html.Label("Site"),
                            dcc.Dropdown(
                                id="site-select",
                                options=[{"label": s, "value": s} for s in sites],
                                value=sites[0] if sites else None,
                                clearable=False,
                            ),
                            html.Label("Metric", style={"marginTop": "12px"}),
                            dcc.RadioItems(
                                id="metric-select",
                                options=[
                                    {"label": "Fan run hours", "value": "fan_run_hours"},
                                    {"label": "System run hours", "value": "system_run_hours"},
                                    {"label": "Unoccupied fan hours", "value": "unoccupied_fan_hours"},
                                ],
                                value="fan_run_hours",
                                style={"color": "#e2e8f0"},
                            ),
                        ]
                    ),
                    dcc.Graph(id="run-hours-chart", style={"background": "#0f172a", "borderRadius": "8px"}),
                ],
            ),
            dcc.Graph(id="fault-trend-chart", style={"marginTop": "16px", "background": "#0f172a"}),
            dcc.Graph(id="override-chart", style={"marginTop": "16px", "background": "#0f172a"}),
            dcc.Interval(id="refresh-interval", interval=120_000, n_intervals=0),
        ],
    )


def _stock_style_figure(df: pd.DataFrame, metric: str, title: str) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.add_annotation(text="No run-hour data", showarrow=False, font={"color": "#94a3b8"})
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0f172a", plot_bgcolor="#0f172a", title=title)
        return fig

    for equipment_id, grp in df.groupby("equipment_id"):
        grp = grp.sort_values("collected_at")
        y = pd.to_numeric(grp[metric], errors="coerce").fillna(0)
        fig.add_trace(
            go.Scatter(
                x=grp["collected_at"],
                y=y,
                mode="lines+markers",
                name=str(grp["equipment_name"].iloc[-1] if "equipment_name" in grp else equipment_id),
                line={"width": 2},
            ),
            secondary_y=False,
        )
        if len(y) >= 2:
            delta = y.diff().fillna(0)
            colors = ["#22c55e" if d <= 0 else "#ef4444" for d in delta]
            fig.add_trace(
                go.Bar(
                    x=grp["collected_at"],
                    y=delta,
                    name=f"Δ {equipment_id}",
                    marker_color=colors,
                    opacity=0.35,
                    showlegend=False,
                ),
                secondary_y=True,
            )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        title=title,
        legend={"orientation": "h"},
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
    )
    fig.update_yaxes(title_text="Hours", secondary_y=False)
    fig.update_yaxes(title_text="Δ hours", secondary_y=True)
    return fig


def _fault_figure(site_id: str) -> go.Figure:
    df = _read_csv("faults_daily.csv")
    fig = go.Figure()
    if df.empty or not site_id:
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0f172a", title="Fault codes — no data")
        return fig
    sub = df[df["site_id"] == site_id].copy()
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    for code, grp in sub.groupby("fault_code"):
        grp = grp.sort_values("collected_at")
        fig.add_trace(
            go.Scatter(
                x=grp["collected_at"],
                y=grp["active_count"],
                mode="lines+markers",
                name=str(code),
            )
        )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        title=f"Active fault codes — {site_id}",
        xaxis_title="Collection time",
        yaxis_title="Active alerts",
        legend={"orientation": "h"},
    )
    return fig


def _override_figure(site_id: str) -> go.Figure:
    checkins = _read_csv("checkins.csv")
    fig = go.Figure()
    if checkins.empty or not site_id:
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0f172a", title="P8 overrides — no data")
        return fig
    sub = checkins[checkins["site_id"] == site_id].copy()
    sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    sub = sub.sort_values("collected_at")
    fig.add_trace(
        go.Scatter(
            x=sub["collected_at"],
            y=pd.to_numeric(sub["operator_overrides"], errors="coerce").fillna(0),
            mode="lines+markers",
            name="P8 operator overrides",
            line={"color": "#f59e0b", "width": 2},
            fill="tozeroy",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        title=f"BACnet priority-8 operator overrides — {site_id}",
        xaxis_title="Collection time",
        yaxis_title="Override points",
    )
    return fig


app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.layout = build_layout


@app.callback(
    Output("collect-status", "children"),
    Input("collect-btn", "n_clicks"),
    prevent_initial_call=True,
)
def run_collect(n_clicks: int):
    if not n_clicks:
        return ""
    script = ROOT.parent / "scripts" / "portfolio_collect.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--json"],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if proc.returncode != 0:
            return f"Collect failed: {proc.stderr[:200] or proc.stdout[:200]}"
        return "Collect finished — refresh or wait for auto-refresh."
    except Exception as exc:
        return f"Collect error: {exc}"


@app.callback(
    Output("run-hours-chart", "figure"),
    Output("fault-trend-chart", "figure"),
    Output("override-chart", "figure"),
    Input("site-select", "value"),
    Input("metric-select", "value"),
    Input("refresh-interval", "n_intervals"),
    Input("collect-btn", "n_clicks"),
)
def update_charts(site_id: str | None, metric: str, _n: int, _btn: int):
    runs = _read_csv("run_hours_daily.csv")
    if site_id and not runs.empty:
        sub = _run_hour_series(runs, site_id, metric)
        sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
    else:
        sub = pd.DataFrame()
    run_fig = _stock_style_figure(sub, metric or "fan_run_hours", f"Equipment run hours — {site_id or '—'}")
    return run_fig, _fault_figure(site_id or ""), _override_figure(site_id or "")


def main() -> None:
    app.run(host="0.0.0.0", port=8050, debug=False)


if __name__ == "__main__":
    main()
