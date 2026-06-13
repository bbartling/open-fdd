#!/usr/bin/env python3
"""OpenFDD RCx Central — analyst dashboard (Dash)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import dash
from dash import Input, Output, dcc, html

from portfolio.dash.theme import BTN_PRIMARY, ROOT_STYLE, THEME

ROOT = Path(__file__).resolve().parents[1]

app = dash.Dash(__name__, title="OpenFDD RCx Central", suppress_callback_exceptions=True)


def _overview_shell() -> html.Div:
    from portfolio.dash.overview_tab import overview_layout

    return html.Div(id="overview-root", children=[overview_layout(THEME)])


def _edges_shell() -> html.Div:
    from portfolio.dash.rcx_pages import edge_connections_layout

    return edge_connections_layout(THEME)


def _report_shell() -> html.Div:
    from portfolio.dash.rcx_report_tab import report_layout

    return html.Div(id="report-root", children=[report_layout(THEME)])


app.layout = html.Div(
    id="app-root",
    style=ROOT_STYLE,
    children=[
        dcc.Store(id="edge-registry-revision", data=0),
        dcc.Interval(id="refresh-interval", interval=300_000, n_intervals=0),
        html.Header(
            style={"marginBottom": "20px", "borderBottom": f"1px solid {THEME['grid']}", "paddingBottom": "16px"},
            children=[
                html.H1("OpenFDD RCx Central", style={"margin": "0 0 6px", "fontSize": "26px"}),
                html.P("Read-only RCx analyst dashboard", style={"margin": 0, "color": THEME["muted"], "fontSize": "14px"}),
            ],
        ),
        dcc.Tabs(
            id="main-tabs",
            value="dashboard",
            children=[
                dcc.Tab(label="Dashboard", value="dashboard", children=[_overview_shell()]),
                dcc.Tab(label="Report Builder", value="report", children=[_report_shell()]),
                dcc.Tab(label="Edge Connections", value="edges", children=[_edges_shell()]),
            ],
        ),
    ],
)


@app.callback(
    Output("refresh-status", "children"),
    Input("refresh-data-btn", "n_clicks"),
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
            return f"Refresh failed: {proc.stderr[:200] or proc.stdout[:200]}"
        return "Data refreshed."
    except Exception as exc:
        return f"Refresh error: {exc}"


def main() -> None:
    from portfolio.dash.overview_tab import register_overview_callbacks
    from portfolio.dash.rcx_callbacks import register_edge_callbacks
    from portfolio.dash.rcx_report_tab import register_report_callbacks

    register_overview_callbacks(app, THEME)
    register_report_callbacks(app, THEME)
    register_edge_callbacks(app)
    host = os.environ.get("OPENFDD_RCX_DASH_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENFDD_RCX_DASH_PORT", "8050"))
    print(f"OpenFDD RCx Central Dash → http://{host}:{port}/", flush=True)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
