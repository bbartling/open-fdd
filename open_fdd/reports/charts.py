"""In-memory matplotlib charts for RCx DOCX reports."""

from __future__ import annotations

import io
from typing import Sequence


def bar_chart_png(
    title: str,
    labels: Sequence[str],
    values: Sequence[float],
    *,
    xlabel: str = "",
    ylabel: str = "Hours",
    color: str = "#2563eb",
) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    labs = list(labels)[:16]
    vals = [float(v) for v in values[:16]]
    if not labs:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.set_axis_off()
    else:
        ax.bar(labs, vals, color=color)
        ax.set_title(title, fontsize=11)
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()


def line_chart_png(
    title: str,
    x: Sequence[str],
    series: dict[str, Sequence[float | None]],
    *,
    ylabel: str = "",
) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    if not x or not series:
        ax.text(0.5, 0.5, "No trend data", ha="center", va="center")
        ax.set_axis_off()
    else:
        for name, ys in series.items():
            ax.plot(list(x), list(ys), label=name, linewidth=1.5)
        ax.set_title(title, fontsize=11)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=9)
        ax.tick_params(axis="x", rotation=30, labelsize=6)
        ax.legend(fontsize=7, loc="best")
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()
