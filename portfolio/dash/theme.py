"""RCx Central Dash — light theme only."""

from __future__ import annotations

THEME: dict[str, str] = {
    "page_bg": "#f1f5f9",
    "card_bg": "#ffffff",
    "text": "#0f172a",
    "muted": "#475569",
    "accent": "#1d4ed8",
    "plot_template": "plotly_white",
    "paper": "#ffffff",
    "plot": "#ffffff",
    "grid": "#e2e8f0",
    "up": "#15803d",
    "down": "#b91c1c",
    "warn": "#b45309",
}

ROOT_STYLE = {
    "fontFamily": "'Segoe UI', system-ui, sans-serif",
    "background": THEME["page_bg"],
    "color": THEME["text"],
    "minHeight": "100vh",
    "padding": "24px 28px",
    "maxWidth": "1200px",
    "margin": "0 auto",
}

SECTION_STYLE = {
    "borderTop": f"1px solid {THEME['grid']}",
    "paddingTop": "8px",
}

EDGE_INPUT_STYLE: dict[str, str] = {
    "padding": "10px 12px",
    "lineHeight": "1.5",
    "minHeight": "44px",
    "boxSizing": "border-box",
    "fontSize": "14px",
    "width": "100%",
    "border": f"1px solid {THEME['grid']}",
    "borderRadius": "8px",
}

BTN_PRIMARY = {
    "background": THEME["accent"],
    "color": "#ffffff",
    "border": "none",
    "padding": "10px 18px",
    "borderRadius": "8px",
    "fontSize": "14px",
    "fontWeight": "600",
    "cursor": "pointer",
}
