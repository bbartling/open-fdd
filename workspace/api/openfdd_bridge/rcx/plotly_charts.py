"""Plotly trend charts aligned with OpenFDD Edge Plot tab (light theme)."""

from __future__ import annotations

import base64
import io
from typing import Any

TEMP_PALETTE = ["#3b6de0", "#2d9a52", "#c9870a", "#a371f7", "#c53d3d", "#58a6ff"]
FAULT_COLORS = ["#f85149", "#d29922", "#58a6ff", "#3fb950", "#a371f7", "#ffa657"]


def _light_layout(title: str = "") -> dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 13, "color": "#1a2332"}},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "font": {"color": "#1a2332", "size": 11},
        "hovermode": "x unified",
        "margin": {"t": 48, "r": 48, "b": 48, "l": 56},
        "legend": {"orientation": "h", "y": 1.12, "font": {"size": 10}},
        "xaxis": {
            "title": "Time (UTC)",
            "gridcolor": "#d8e0ec",
            "linecolor": "#b8c4d4",
            "tickfont": {"color": "#1a2332"},
        },
        "yaxis": {
            "gridcolor": "#d8e0ec",
            "linecolor": "#b8c4d4",
            "tickfont": {"color": "#1a2332"},
            "automargin": True,
        },
    }


def build_trend_figure(
    readings: dict[str, Any],
    *,
    title: str = "",
    show_faults: bool = True,
    plotly: bool = True,
) -> dict[str, Any]:
    """Plotly figure for Dash (optional); PNG for gallery/DOCX."""
    row_count = int(readings.get("row_count") or len(readings.get("timestamps") or []))
    if not plotly:
        return {
            "figure": None,
            "image_base64": _matplotlib_trend_png(readings, title=title, show_faults=show_faults),
            "row_count": row_count,
        }
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    timestamps = readings.get("timestamps") or []
    series = readings.get("series") if isinstance(readings.get("series"), dict) else {}
    labels = readings.get("labels") if isinstance(readings.get("labels"), dict) else {}
    fault_plots = readings.get("fault_plots") if isinstance(readings.get("fault_plots"), dict) else {}
    panels = {
        str(p.get("key")): p
        for p in (readings.get("fault_panels") or [])
        if isinstance(p, dict)
    }

    fault_keys = list(fault_plots.keys()) if show_faults else []
    rows = 2 if fault_keys else 1
    row_heights = [0.72, 0.28] if fault_keys else [1.0]
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=row_heights,
    )

    for i, (col, vals) in enumerate(series.items()):
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=vals,
                name=str(labels.get(col) or col),
                mode="lines",
                line={"color": TEMP_PALETTE[i % len(TEMP_PALETTE)], "width": 2},
                connectgaps=True,
            ),
            row=1,
            col=1,
        )

    if fault_keys:
        for j, key in enumerate(fault_keys[:6]):
            flags = fault_plots.get(key) or []
            panel = panels.get(key) or {}
            total = sum(int(f or 0) for f in flags)
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=[int(f or 0) for f in flags],
                    name=f"{panel.get('title') or key} ({total})",
                    mode="lines",
                    line={"color": FAULT_COLORS[j % len(FAULT_COLORS)], "width": 2, "shape": "hv"},
                ),
                row=2,
                col=1,
            )
        fig.update_yaxes(title_text="Faults (0/1)", range=[-0.08, 1.08], row=2, col=1)

    layout = _light_layout(title)
    if not series:
        layout["annotations"] = [
            {
                "text": "No trend samples in selected window",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"color": "#475569", "size": 13},
            }
        ]
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="Value", row=1, col=1)

    figure = fig.to_dict()
    image_b64 = _figure_to_png(fig)
    if not image_b64:
        image_b64 = _matplotlib_trend_png(readings, title=title, show_faults=show_faults)
    return {"figure": figure, "image_base64": image_b64, "row_count": int(readings.get("row_count") or len(timestamps))}


def build_bar_figure(
    *,
    title: str,
    labels: list[str],
    values: list[float],
    y_title: str = "Hours (est.)",
    plotly: bool = True,
) -> dict[str, Any]:
    if not plotly:
        return {
            "figure": None,
            "image_base64": _matplotlib_bar_png(title, labels, values, y_title),
        }
    import plotly.graph_objects as go

    fig = go.Figure(go.Bar(x=labels, y=values, marker_color="#3b6de0"))
    layout = _light_layout(title)
    layout["yaxis"]["title"] = y_title
    fig.update_layout(**layout)
    if not labels:
        layout["annotations"] = [
            {
                "text": "No data in selected window",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"color": "#475569"},
            }
        ]
        fig.update_layout(**layout)
    image_b64 = _figure_to_png(fig)
    if not image_b64:
        image_b64 = _matplotlib_bar_png(title, labels, values, y_title)
    return {"figure": fig.to_dict(), "image_base64": image_b64}


def build_building_inventory_figure(
    *,
    counts: dict[str, Any],
    fault_summary: dict[str, Any],
    model_health: dict[str, Any],
    plotly: bool = True,
) -> dict[str, Any]:
    labels = ["AHUs", "VAVs", "Zones", "Active faults", "Health score"]
    values = [
        float(counts.get("ahus") or 0),
        float(counts.get("vavs") or 0),
        float(counts.get("zones") or 0),
        float(fault_summary.get("active_faults") or 0),
        float(model_health.get("score") or 100),
    ]
    return build_bar_figure(
        title="Building inventory & active faults",
        labels=labels,
        values=values,
        y_title="Count / score",
        plotly=plotly,
    )


def build_model_health_figure(health: dict[str, Any], *, plotly: bool = True) -> dict[str, Any]:
    counts = health.get("counts") if isinstance(health.get("counts"), dict) else {}
    labels = ["Devices", "Points", "Equipment", "Stale", "Issues"]
    values = [
        float(counts.get("devices") or counts.get("device_count") or 0),
        float(counts.get("points") or counts.get("point_count") or 0),
        float(counts.get("equipment") or counts.get("equipment_count") or 0),
        float(health.get("stale_point_count") or 0),
        float(len(health.get("issues") or [])),
    ]
    return build_bar_figure(title="BACnet / model health", labels=labels, values=values, y_title="Count", plotly=plotly)


def _matplotlib_trend_png(readings: dict[str, Any], *, title: str, show_faults: bool) -> str:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from .trend_charts import overlays_from_readings, render_trend_ax

        fig, ax = plt.subplots(figsize=(9, 3.6))
        overlays = overlays_from_readings(readings, show=show_faults)
        render_trend_ax(ax, readings, overlays=overlays)
        ax.set_title(title, fontsize=11)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _matplotlib_bar_png(title: str, labels: list[str], values: list[float], y_title: str) -> str:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.bar(labels, values, color="#3b6de0")
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(y_title)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _figure_to_png(fig) -> str:
    try:
        png = fig.to_image(format="png", width=900, height=420, scale=1)
        return base64.b64encode(png).decode("ascii")
    except Exception:
        return ""
