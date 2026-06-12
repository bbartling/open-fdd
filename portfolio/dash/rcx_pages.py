"""OpenFDD RCx Central — additional Dash tab layouts."""

from __future__ import annotations

import os

from dash import dcc, html

CENTRAL_API = os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")

HOUR_OPTS = [
    {"label": "Last 2 hours", "value": 2},
    {"label": "Last 24 hours", "value": 24},
    {"label": "Last 7 days", "value": 168},
]


def edge_connections_layout(theme: dict) -> html.Div:
    return html.Div(
        className="rcx-panel",
        children=[
            html.H2("Edge Connections", style={"color": theme["text"]}),
            html.P(
                "Add OpenFDD Edge instances (Tailscale/VPN URL). Credentials stay in local config volume only.",
                style={"color": theme["muted"]},
            ),
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
                children=[
                    dcc.Input(id="edge-site-id", placeholder="site_id (e.g. acme)", style={"padding": "8px"}),
                    dcc.Input(id="edge-name", placeholder="Site name", style={"padding": "8px"}),
                    dcc.Input(id="edge-url", placeholder="https://edge.example:8765", style={"padding": "8px", "gridColumn": "1 / -1"}),
                    dcc.Input(id="edge-user", placeholder="username", value="agent", style={"padding": "8px"}),
                    dcc.Input(id="edge-password", type="password", placeholder="password", style={"padding": "8px"}),
                ],
            ),
            html.Div(
                style={"marginTop": "12px", "display": "flex", "gap": "8px"},
                children=[
                    html.Button("Test Connection", id="edge-test-btn", n_clicks=0),
                    html.Button("Save Edge", id="edge-save-btn", n_clicks=0),
                ],
            ),
            html.Pre(id="edge-test-result", style={"color": theme["muted"], "whiteSpace": "pre-wrap"}),
            html.Div(id="edge-list"),
        ],
    )


def mechanical_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.H2("Mechanical Summary", style={"color": theme["text"]}),
            dcc.Dropdown(id="mech-site", placeholder="Select Edge site"),
            dcc.RadioItems(id="mech-hours", options=HOUR_OPTS, value=24, inline=True),
            html.Button("Refresh Mechanical Summary", id="mech-refresh-btn", n_clicks=0, style={"marginTop": "8px"}),
            html.Pre(id="mech-summary", style={"color": theme["text"], "whiteSpace": "pre-wrap"}),
        ]
    )


def rcx_builder_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.H2("RCx Report Builder", style={"color": theme["text"]}),
            dcc.Dropdown(id="rcx-site", placeholder="Select Edge site"),
            dcc.RadioItems(id="rcx-hours", options=HOUR_OPTS, value=24, inline=True),
            dcc.Checklist(id="rcx-overlays", options=[{"label": "Show fault overlays", "value": "on"}], value=["on"]),
            html.Div(
                style={"display": "flex", "gap": "8px", "marginTop": "8px", "flexWrap": "wrap"},
                children=[
                    html.Button("Collect Data / Preview", id="rcx-preview-btn", n_clicks=0),
                    html.Button("Preview Charts", id="rcx-charts-btn", n_clicks=0),
                    html.Button("Generate DOCX", id="rcx-docx-btn", n_clicks=0),
                ],
            ),
            html.Div(id="rcx-readiness", style={"color": theme["muted"]}),
            html.Div(id="rcx-chart-checkboxes"),
            html.Div(id="rcx-section-checkboxes"),
            html.Div(id="rcx-chart-previews"),
            dcc.Download(id="rcx-download"),
            html.Pre(id="rcx-status", style={"color": theme["muted"]}),
        ]
    )


def fdd_analytics_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.H2("FDD Rules & Analytics", style={"color": theme["text"]}),
            dcc.Dropdown(id="fdd-site", placeholder="Select Edge site"),
            dcc.RadioItems(id="fdd-hours", options=HOUR_OPTS, value=24, inline=True),
            html.Button("Refresh FDD rules", id="fdd-refresh-btn", n_clicks=0, style={"marginTop": "8px"}),
            html.Pre(id="fdd-rules-table", style={"color": theme["text"], "whiteSpace": "pre-wrap"}),
        ]
    )


def trend_explorer_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.H2("Trend Explorer", style={"color": theme["text"]}),
            html.P("Plotly view of collected portfolio rollups (interactive).", style={"color": theme["muted"]}),
            dcc.Dropdown(id="trend-site", placeholder="Site (overview tab charts)"),
            html.P("Use Overview charts for interactive Plotly trends from local collect CSVs.", style={"color": theme["muted"]}),
        ]
    )


def validation_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.H2("Validation Runs", style={"color": theme["text"]}),
            dcc.Dropdown(id="val-site", placeholder="Select Edge site"),
            html.Button("Run one-off validation", id="val-run-btn", n_clicks=0, style={"marginTop": "8px"}),
            html.Pre(id="val-result", style={"color": theme["text"], "whiteSpace": "pre-wrap"}),
            html.H3("Stored jobs", style={"color": theme["text"]}),
            html.Pre(id="val-jobs", style={"color": theme["muted"], "whiteSpace": "pre-wrap"}),
        ]
    )


def settings_layout(theme: dict) -> html.Div:
    return html.Div(
        children=[
            html.H2("Settings", style={"color": theme["text"]}),
            html.P(f"Central API: {CENTRAL_API}", style={"color": theme["muted"]}),
            html.P(
                "Data and credentials persist under portfolio/data and portfolio/config (Docker volumes in compose).",
                style={"color": theme["muted"]},
            ),
            html.P("Read-only toward OpenFDD Edge — no BACnet writes.", style={"color": theme.get("warn", theme["muted"])}),
        ]
    )


def overview_intro(theme: dict) -> html.P:
    return html.P(
        "Multi-edge fault & run-hour rollups from collected Edge snapshots. Use Edge Connections to register sites.",
        style={"color": theme["muted"], "margin": "4px 0 12px"},
    )
