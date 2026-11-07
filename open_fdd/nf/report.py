"""Reports from NF / CSV frames: a plain CSV + markdown summary, and (optionally) the full
Engineering Findings pipeline of ``open_fdd.reporting`` (needs the ``reporting`` extra)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from open_fdd.nf.rules import results_table, rule_results


def build_overview_context(frames: Mapping[tuple[str, str], Any]) -> dict:
    """``overview_context`` for the reporting pipeline from role-named frames (all SI)."""
    from open_fdd.analytics.core import dataset_time_span
    from open_fdd.reporting.overview_export import build_overview_context as _build

    by_equip = {equip: df for (_, equip), df in frames.items()}
    span = dataset_time_span(by_equip) if by_equip else {}
    return _build(frames=by_equip, role_map={}, weather=None, dataset_start=span.get("start"),
                  dataset_end=span.get("end"), span_hours=span.get("span_hours"))


def summary_markdown(table, building: str, frames: Mapping[tuple[str, str], Any]) -> str:
    lines = [f"# Open-FDD rules summary: {building or 'NF site'}", ""]
    if frames:
        start = min(df.index.min() for df in frames.values())
        end = max(df.index.max() for df in frames.values())
        lines.append(f"Period (UTC): {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}; "
                     f"{len(frames)} equipment with data. All values SI.")
        lines.append("")
    counts = table["status"].value_counts().to_dict()
    lines.append("Status counts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) if counts else "No rules ran.")
    faults = table[table["status"] == "fault"].sort_values("fault_hours", ascending=False)
    lines += ["", "## Faults", ""]
    if faults.empty:
        lines.append("No confirmed faults.")
    else:
        lines += ["| site | equip | rule | fault hours | fault % | coverage |", "|---|---|---|---:|---:|---:|"]
        lines += [f"| {r.site} | {r.equip} | {r.rule} | {r.fault_hours} | {r.fault_pct} | {r.coverage} |"
                  for r in faults.itertuples()]
    lines += ["", "Rules that could not be assessed (missing roles, equipment off) are listed as "
              "`not-assessed` in `rules.csv`; they are not healthy.", ""]
    return "\n".join(lines)


def write_report(
    frames: Mapping[tuple[str, str], Any],
    out_dir: str | Path,
    building: str = "",
    findings: bool = False,
    docx: bool = False,
) -> dict[str, str]:
    """Write ``rules.csv`` and ``summary.md`` (always) and, with ``findings=True``, the Engineering
    Findings report from ``open_fdd.reporting`` (JSON, optional DOCX). Returns ``{name: path}``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = rule_results(frames)
    table = results_table(results)
    written: dict[str, str] = {}
    (out / "rules.csv").write_text(table.to_csv(index=False), encoding="utf-8")
    (out / "summary.md").write_text(summary_markdown(table, building, frames), encoding="utf-8")
    written["rules_csv"], written["summary_md"] = str(out / "rules.csv"), str(out / "summary.md")
    if findings:
        from open_fdd.reporting.pipeline import build_engineering_findings, render_engineering_report

        art = build_engineering_findings(
            building=building, rule_results=[r for _, _, r in results],
            overview_context=build_overview_context(frames) if frames else None)
        paths = render_engineering_report(art, out, docx=docx, json_out=True, charts=False,
                                          overview_context=None, rule_results=[r for _, _, r in results])
        written.update({k: str(v) for k, v in paths.items()})
        (out / "quality_gate.json").write_text(json.dumps(art.quality_gate, indent=2, default=str), encoding="utf-8")
        written["quality_gate"] = str(out / "quality_gate.json")
    return written
