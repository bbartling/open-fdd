"""Finding-specific charts → optional PNG (Plotly + Kaleido when available)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from open_fdd.reporting.models import EngineeringFinding, ReportArtifacts


def _detection_label(c: dict[str, Any], *, max_label: int = 42) -> str:
    """Compact axis label: equipment · rule_id (short title if room)."""
    equip = str(c.get("equipment_id") or "?").strip()
    rid = str(c.get("rule_id") or "").strip()
    title = str(c.get("rule_label") or "").strip()
    base = f"{equip} · {rid}" if rid else equip
    if title and title.upper() != rid.upper() and len(base) + len(title) < max_label:
        return f"{base} ({title})"[:max_label]
    return base[:max_label]


def _is_vav_candidate(c: dict[str, Any]) -> bool:
    """Data-model / id / rule driven — not a hardcoded building list."""
    et = str(c.get("equipment_type") or "").upper()
    eid = str(c.get("equipment_id") or "").upper()
    rid = str(c.get("rule_id") or "").upper()
    return (
        "VAV" in et
        or eid.startswith("VAV")
        or rid.startswith("VAV")
        or "ZONE" in et
    )


def _horizontal_fault_hours_fig(
    rows: list[dict[str, Any]],
    *,
    title: str,
    go,
    marker_color: str = "#2b6cb0",
):
    """Readable horizontal bar chart; layout height/margins sized for Kaleido export."""
    labels = [_detection_label(c) for c in rows][::-1]
    hours = [float(c.get("fault_hours") or 0) for c in rows][::-1]
    longest = max((len(lbl) for lbl in labels), default=10)
    left_margin = min(320, max(140, int(longest * 7.2)))
    height = max(380, 32 * len(rows) + 100)
    fig = go.Figure(
        data=[go.Bar(y=labels, x=hours, orientation="h", marker_color=marker_color)]
    )
    fig.update_layout(
        title=title,
        xaxis_title="Fault hours",
        yaxis_title=None,
        height=height,
        width=960,
        margin=dict(l=left_margin, r=28, t=56, b=48),
        font=dict(size=11),
        yaxis=dict(automargin=True, tickfont=dict(size=10)),
        xaxis=dict(automargin=True),
    )
    return fig


def build_report_charts(
    artifacts: ReportArtifacts,
    *,
    out_dir: Path | None = None,
    comfort_rows: list[dict[str, Any]] | None = None,
    overview_context: dict[str, Any] | None = None,
    rule_results: list | None = None,
) -> list[dict[str, Any]]:
    """Attach chart metadata (and PNG paths when Kaleido / matplotlib works)."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return []

    out_dir = Path(out_dir) if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    charts: list[dict[str, Any]] = []

    # 0) Overview analytics (Plotly → Kaleido) when frames present
    if out_dir is not None and overview_context:
        try:
            from open_fdd.reporting.overview_export import (
                build_overview_charts,
                overview_settings_from_context,
            )

            if not artifacts.overview_settings:
                artifacts.overview_settings = overview_settings_from_context(
                    overview_context
                )
            overview_meta = build_overview_charts(
                artifacts, overview_context, out_dir=out_dir / "overview"
            )
            charts.extend(overview_meta)
        except Exception as exc:
            charts.append(
                {"name": "overview_export", "path": None, "export_error": str(exc)}
            )

    # 1) Confidence summary
    from collections import Counter

    counts = Counter(f.effective_classification.value for f in artifacts.findings)
    for s in artifacts.suppressed:
        counts[s.get("classification") or "SUPPRESSED"] += 0  # don't inflate
    fig = go.Figure(
        data=[
            go.Bar(
                x=list(counts.keys()),
                y=list(counts.values()),
                marker_color="#2c5282",
            )
        ]
    )
    fig.update_layout(
        title="Findings by confidence category",
        xaxis_title="Category",
        yaxis_title="Count",
        height=360,
        width=900,
        margin=dict(l=40, r=20, t=50, b=100),
        font=dict(size=12),
        xaxis=dict(tickangle=-35, automargin=True),
    )
    charts.append(_export(fig, "confidence_summary", out_dir))

    # 1b) Top detections by fault hours (all equipment types from candidates)
    ranked = sorted(
        [c for c in (artifacts.candidates or []) if c.get("fault_hours") is not None],
        key=lambda c: -float(c.get("fault_hours") or 0),
    )
    top = ranked[:12]
    if top:
        fig_top = _horizontal_fault_hours_fig(
            top,
            title="Top detections by fault hours",
            go=go,
            marker_color="#2b6cb0",
        )
        charts.append(_export(fig_top, "top_detections", out_dir))

    # 1c) VAV / zone box detections — same candidate model, filtered by type/id/rule
    vav_top = [c for c in ranked if _is_vav_candidate(c)][:12]
    if vav_top:
        fig_vav = _horizontal_fault_hours_fig(
            vav_top,
            title="Top VAV / zone box detections by fault hours",
            go=go,
            marker_color="#805ad5",
        )
        charts.append(_export(fig_vav, "top_vav_detections", out_dir))

    # 2) Comfort ranking (valid sensors only)
    rows = comfort_rows or (artifacts.comfort_summary.get("rows") or [])
    valid = [
        r
        for r in rows
        if not r.get("flag_dead_sensor")
        and not r.get("outlier")
        and (r.get("mean_zone_t") or 99) >= 40
    ]
    valid = sorted(valid, key=lambda r: float(r.get("in_band_pct") or r.get("in_band_%") or 0))[:15]
    if valid:
        y_labels = [str(r.get("equipment_id") or "?") for r in valid][::-1]
        left = min(280, max(100, int(max(len(x) for x in y_labels) * 7.2)))
        fig2 = go.Figure(
            data=[
                go.Bar(
                    y=y_labels,
                    x=[float(r.get("in_band_pct") or r.get("in_band_%") or 0) for r in valid][::-1],
                    orientation="h",
                    marker_color="#c05621",
                )
            ]
        )
        fig2.update_layout(
            title="Zone comfort ranking (dead/implausible sensors excluded)",
            xaxis_title="In-band % (occupied)",
            height=max(380, 30 * len(valid) + 100),
            width=900,
            margin=dict(l=left, r=20, t=50, b=40),
            yaxis=dict(automargin=True),
        )
        charts.append(_export(fig2, "comfort_ranking", out_dir))

    # 3) Per priority finding chart (scalar fallback)
    for f in artifacts.findings:
        if not f.include_in_report or not f.chart_spec:
            continue
        fig_f = _figure_for_finding(f, go)
        if fig_f is None:
            continue
        meta = _export(fig_f, f"finding_{f.finding_id}", out_dir)
        f.chart_path = meta.get("path")
        charts.append({**meta, "finding_id": f.finding_id})

    # 4) Day-zoom matplotlib PNGs from RuleResult series
    if out_dir is not None and rule_results:
        try:
            from open_fdd.reporting.day_zoom import attach_day_zoom_to_findings

            day_meta = attach_day_zoom_to_findings(
                artifacts.findings,
                rule_results,
                out_dir=out_dir / "day_zoom",
            )
            charts.extend(day_meta)
        except Exception as exc:
            charts.append(
                {"name": "day_zoom", "path": None, "export_error": str(exc)}
            )

    artifacts.charts = charts
    return charts


def _figure_for_finding(f: EngineeringFinding, go):
    spec = f.chart_spec or {}
    kind = spec.get("kind")
    if kind == "fan_off_static":
        fig = go.Figure(
            data=[
                go.Bar(
                    x=["Fan OFF", "Fan ON"],
                    y=[float(spec.get("fan_off_p50") or 0), float(spec.get("fan_on_p50") or 0)],
                    marker_color=["#c53030", "#2b6cb0"],
                )
            ]
        )
        fig.update_layout(
            title=f"{spec.get('equipment_id')} duct static — fan OFF vs ON ({spec.get('units')})",
            yaxis_title=str(spec.get("units") or "in. w.c."),
            height=360,
            width=900,
        )
        return fig
    if kind == "vav5_damper_flow":
        fig = go.Figure(
            data=[
                go.Bar(
                    x=["Damper %", "Airflow"],
                    y=[float(spec.get("damper") or 0), float(spec.get("airflow") or 0)],
                    marker_color=["#805ad5", "#dd6b20"],
                )
            ]
        )
        fig.update_layout(
            title=f"{spec.get('equipment_id')} closed-damper / airflow spot check",
            height=360,
            width=900,
            annotations=[
                dict(
                    text="Units: damper %, airflow CFM (spot medians)",
                    xref="paper",
                    yref="paper",
                    x=0,
                    y=-0.15,
                    showarrow=False,
                )
            ],
        )
        return fig
    if kind == "fault_hours_bar" and spec.get("fault_hours") is not None:
        fig = go.Figure(
            data=[
                go.Bar(
                    x=[f"{spec.get('equipment_id')} / {spec.get('rule_id')}"],
                    y=[float(spec.get("fault_hours"))],
                )
            ]
        )
        fig.update_layout(
            title="Fault hours",
            yaxis_title="Hours",
            height=320,
            width=900,
            xaxis=dict(tickangle=-25, automargin=True),
            margin=dict(l=40, r=20, t=50, b=90),
        )
        return fig
    # comfort_rank: fleet chart is the comfort_ranking PNG — no per-finding scalar
    return None


def _export(fig, name: str, out_dir: Path | None) -> dict[str, Any]:
    meta: dict[str, Any] = {"name": name, "path": None}
    if out_dir is None:
        return meta
    png = out_dir / f"{name}.png"
    try:
        from open_fdd.reporting.overview_export import _fig_for_kaleido

        export_fig = _fig_for_kaleido(fig)
        # Honor layout size so horizontal bar labels are not clipped at 420px.
        layout = getattr(export_fig, "layout", None)
        width = int(getattr(layout, "width", None) or 900)
        height = int(getattr(layout, "height", None) or 420)
        export_fig.write_image(str(png), scale=2, width=width, height=height)
        meta["path"] = str(png)
    except Exception as exc:  # kaleido optional / may fail headless
        meta["export_error"] = str(exc)
        # still save interactive html for debugging
        html = out_dir / f"{name}.html"
        try:
            fig.write_html(str(html), include_plotlyjs="cdn")
            meta["html"] = str(html)
        except Exception:
            pass
    return meta
