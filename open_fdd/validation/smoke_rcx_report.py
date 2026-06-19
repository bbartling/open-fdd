"""Build RCx DOCX that embeds half-hour bench 5007 smoke validation results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_smoke_validation_context(
    *,
    smoke_json: dict[str, Any],
    health_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Payload for RCx DOCX smoke_validation section."""
    bench = smoke_json.get("bench") if isinstance(smoke_json.get("bench"), dict) else {}
    parity_pairs = [
        ("smoke-paired-zn-t-bacnet-arrow", "smoke-paired-zn-t-bacnet-sql"),
        ("smoke-paired-zn-t-niagara-arrow", "smoke-paired-zn-t-niagara-sql"),
    ]
    snapshots = bench.get("snapshots") if isinstance(bench.get("snapshots"), list) else []
    last_snap = snapshots[-1] if snapshots else {}
    flagged = {}
    if isinstance(last_snap, dict):
        batch = last_snap.get("bench_batch") or {}
        if isinstance(batch, dict):
            flagged = batch.get("flagged") or {}

    override_probe = {}
    for snap in reversed(health_history or []):
        for probe in snap.get("probes") or []:
            if isinstance(probe, dict) and probe.get("name") == "bacnet_override_scan":
                override_probe = probe
                break
        if override_probe:
            break

    return {
        "mode": smoke_json.get("mode"),
        "pass": bool(smoke_json.get("pass")),
        "issues": smoke_json.get("issues") or [],
        "parity_rule_pairs": parity_pairs,
        "last_flagged": flagged,
        "health_probes_final": (health_history or [])[-1] if health_history else {},
        "health_probe_count": len(health_history or []),
        "override_scan": override_probe.get("data") if override_probe else {},
        "override_scan_ok": bool(override_probe.get("ok")) if override_probe else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_smoke_rcx_docx(
    *,
    reports_dir: Path,
    site_id: str = "demo",
    site_name: str = "Bench Demo Site",
    hours: int = 24,
) -> tuple[bytes, Path]:
    """Merge live RCx preview with smoke artifacts into one DOCX."""
    smoke_path = reports_dir / "paired_fdd_smoke_validation.json"
    health_path = reports_dir / "bench_5007_half_hour_health.json"
    smoke_json = _load_json(smoke_path)
    health_doc = _load_json(health_path)
    health_history = health_doc.get("history") if isinstance(health_doc.get("history"), list) else []

    smoke_ctx = build_smoke_validation_context(smoke_json=smoke_json, health_history=health_history)

    import sys

    repo = reports_dir.parent
    api_root = repo / "workspace" / "api"
    for p in (str(repo), str(api_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

    from openfdd_bridge.rcx.chart_preview import build_rcx_preview
    from open_fdd.reports.rcx_docx import build_rcx_docx
    from openfdd_bridge.rcx.rcx_report_context import build_rcx_report_context
    from openfdd_bridge.rcx.rcx_ai_insights import generate_rcx_ai_insights

    preview = build_rcx_preview(site_id=site_id, hours=hours, include_previews=False, include_chart_stats=True)
    fault_rows = preview.get("fault_rows") or []
    mech = preview.get("mechanical_summary") or {}
    overview = {
        "active_faults": preview["fault_summary"]["active_faults"],
        "total_fault_hours": preview["fault_summary"]["total_fault_hours"],
        "missing_roles": preview.get("missing_roles"),
        "mechanical_summary": mech,
        "model_health": mech.get("model_health") if isinstance(mech.get("model_health"), dict) else {},
    }
    report_ctx = build_rcx_report_context(site_id=site_id, hours=hours)
    report_ctx["smoke_validation"] = smoke_ctx

    ai_insights = generate_rcx_ai_insights(
        site_id=site_id,
        site_name=site_name,
        window=preview.get("window") or {},
        fault_rows=fault_rows,
        overview=overview,
        chart_previews=preview.get("chart_previews") or [],
        report_context=report_ctx,
        mechanical_summary=mech,
        report_profile=preview.get("report_profile"),
    )

    sections = [
        "executive_summary",
        "analyst_insights",
        "model_health",
        "smoke_validation",
        "appendix_faults",
    ]
    blob = build_rcx_docx(
        site_id=site_id,
        site_name=site_name,
        window=preview.get("window") or {},
        fault_rows=fault_rows,
        overview=overview,
        sections=sections,
        charts=preview.get("suggested_charts") or [],
        warnings=preview.get("warnings"),
        chart_previews=preview.get("chart_previews") or [],
        report_context=report_ctx,
        equipment_charts=(preview.get("report_bundles") or {}).get("equipment_charts") or [],
        available_charts=preview.get("available_charts") or [],
        disabled_charts=preview.get("disabled_charts") or [],
        ai_insights=ai_insights,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"bench_5007_half_hour_smoke_rcx_{ts}.docx"
    from openfdd_bridge.rcx.report_store import save_report

    out = save_report(fname, blob)
    return blob, out
