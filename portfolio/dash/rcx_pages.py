"""OpenFDD RCx Central — Edge Connections tab."""

from __future__ import annotations

from dash import dcc, html

from portfolio.dash.theme import BTN_PRIMARY, EDGE_INPUT_STYLE


def edge_connections_layout(theme: dict) -> html.Div:
    return html.Div(
        style={"paddingTop": "8px"},
        children=[
            html.P(
                "Paste your OpenFDD Edge URL and display name — credentials are saved locally and appear on the Dashboard.",
                style={"color": theme["muted"], "fontSize": "14px"},
            ),
            html.H3("Connected sites", style={"fontSize": "16px", "marginTop": "12px"}),
            html.Div(id="edge-list"),
            html.H3("Add or update Edge", style={"fontSize": "16px", "marginTop": "24px"}),
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1fr", "gap": "10px", "maxWidth": "640px"},
                children=[
                    dcc.Input(
                        id="edge-name",
                        placeholder="Display name (e.g. Main campus lab)",
                        style=EDGE_INPUT_STYLE,
                    ),
                    dcc.Input(
                        id="edge-url",
                        placeholder="Edge URL (e.g. http://192.168.1.50)",
                        style=EDGE_INPUT_STYLE,
                    ),
                    html.Div(
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"},
                        children=[
                            dcc.Input(id="edge-user", placeholder="username", style=EDGE_INPUT_STYLE),
                            dcc.Input(id="edge-password", type="password", placeholder="password", style=EDGE_INPUT_STYLE),
                        ],
                    ),
                ],
            ),
            html.Div(
                style={"display": "flex", "gap": "10px", "marginTop": "12px", "flexWrap": "wrap"},
                children=[
                    html.Button("Test connection", id="edge-test-btn", n_clicks=0, style=BTN_PRIMARY),
                    html.Button("Save connection", id="edge-save-btn", n_clicks=0, style=BTN_PRIMARY),
                ],
            ),
            html.Pre(id="edge-test-result", style={"color": theme["muted"], "whiteSpace": "pre-wrap", "fontSize": "12px"}),
        ],
    )
