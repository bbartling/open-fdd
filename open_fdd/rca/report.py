"""JSON and Markdown formatters for advisory graph-based HVAC RCA reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from open_fdd.rca.rank import RCAReport

REPORT_VERSION = 1


def next_checks(report: RCAReport) -> list[str]:
    """Generate an ordered advisory action checklist for operators and AI agents."""
    checks: list[str] = []
    for cc in report.common_causes[:3]:
        affected = ", ".join(cc.downstream_equipment)
        qual_parts = [p for p in (f"site={cc.root_site}" if cc.root_site else "", cc.root_iri) if p]
        qual_str = ", ".join(qual_parts)
        qual = f" [{qual_str}]" if qual_parts else ""
        inf_tag = f" [{cc.topology_source}]" if cc.inferred else ""
        checks.append(
            f"Inspect {cc.root_equipment}{qual} ({cc.root_rule}, confidence={cc.confidence:.2f}){inf_tag}: "
            f"common upstream cause for {cc.downstream_symptom_count} symptoms ({affected})."
        )
    for tr in report.traces:
        if tr.candidates and tr.candidates[0].hop_distance == 0:
            lead = tr.candidates[0]
            checks.append(
                f"Inspect {tr.symptom_equipment} locally ({lead.rule_id}, confidence={lead.confidence:.2f}); "
                f"no stronger upstream cause found."
            )
        elif tr.candidates and tr.candidates[0].inferred:
            lead = tr.candidates[0]
            checks.append(
                f"Verify inferred upstream {lead.equipment_id} -> {tr.symptom_equipment} "
                f"({lead.rule_id}, confidence={lead.confidence:.2f}; {lead.topology_source})."
            )
        if tr.unknown_upstream and tr.upstream_status != "traced_inferred":
            at = ", ".join(tr.unknown_upstream_at) or tr.symptom_equipment
            checks.append(
                f"Verify topology/feeder tags above {at}: graph traversal hit unknown upstream."
            )
    if not checks:
        checks.append("No active downstream fault symptoms required upstream root-cause tracing.")
    return checks[:10]


def report_to_dict(report: RCAReport, *, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert an ``RCAReport`` into a compact JSON-serializable dictionary (SI units)."""
    return {
        "report_version": REPORT_VERSION,
        "advisory": report.advisory,
        "units": "SI",
        "source": source or {},
        "totals": dict(report.totals),
        "common_causes": [asdict(cc) for cc in report.common_causes],
        "traces": [
            {
                "symptom_equipment": t.symptom_equipment,
                "symptom_rule": t.symptom_rule,
                "symptom_site": t.symptom_site,
                "symptom_start": t.symptom_start,
                "symptom_end": t.symptom_end,
                "upstream_status": t.upstream_status,
                "unknown_upstream": t.unknown_upstream,
                "unknown_upstream_at": list(t.unknown_upstream_at),
                "topology_source": t.topology_source,
                "inferred_edges_used": t.inferred_edges_used,
                "symptom_data_quality": list(t.symptom_data_quality),
                "notes": list(t.notes),
                "candidates": [
                    {
                        **asdict(c),
                        "cause_chain": list(c.cause_chain),
                        "relations": list(c.relations),
                        "data_quality_caveats": list(c.data_quality_caveats),
                        "reasons": list(c.reasons),
                    }
                    for c in t.candidates
                ],
            }
            for t in report.traces
        ],
        "next_checks": next_checks(report),
    }


def report_to_json(report: RCAReport, *, source: dict[str, Any] | None = None, indent: int = 2) -> str:
    """Serialize an ``RCAReport`` as formatted JSON."""
    return json.dumps(report_to_dict(report, source=source), indent=indent)


def report_to_markdown(report: RCAReport) -> str:
    """Format an ``RCAReport`` as concise operator/agent Markdown."""
    t = report.totals
    lines = [
        "# HVAC Root-Cause Analysis (Advisory)",
        "",
        f"> {report.advisory}",
        "",
        (
            f"Analyzed **{t.get('symptoms_analyzed', 0)}** symptom(s): "
            f"**{t.get('common_cause_groups', 0)}** common-cause group(s), "
            f"**{t.get('unknown_upstream_traces', 0)}** trace(s) with unknown upstream, "
            f"**{t.get('inferred_topology_traces', 0)}** trace(s) using inferred topology (not modeled), "
            f"**{t.get('false_positives_downweighted', 0)}** likely false positive(s) down-weighted."
        ),
        "",
        "## Check next",
        "",
        *[f"{i}. {c}" for i, c in enumerate(next_checks(report), 1)],
    ]

    if report.common_causes:
        lines.extend(
            [
                "",
                "## Common-cause rollups",
                "",
                "| Root equipment | Root rule | Topology | Confidence | Downstream symptoms | Affected equipment |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for cc in report.common_causes:
            affected = ", ".join(cc.downstream_equipment)
            lines.append(
                f"| {cc.root_equipment} | {cc.root_rule} | {cc.topology_source} | {cc.confidence:.3f} | "
                f"{cc.downstream_symptom_count} | {affected} |"
            )

    if report.traces:
        lines.extend(["", "## Symptom traces"])
        for tr in report.traces:
            lines.extend(
                [
                    "",
                    f"### {tr.symptom_equipment} — {tr.symptom_rule} (`{tr.upstream_status}`)",
                ]
            )
            for note in tr.notes:
                lines.append(f"- **Note:** {note}")
            if tr.symptom_data_quality:
                lines.append(f"- **Symptom data quality:** {', '.join(tr.symptom_data_quality)}")
            if tr.candidates:
                lines.extend(
                    [
                        "",
                        "| Rank | Equipment | Rule | Topology | Confidence | Share | Cause chain | Why |",
                        "|---:|---|---|---|---:|---:|---|---|",
                    ]
                )
                for idx, c in enumerate(tr.candidates, 1):
                    chain = " -> ".join(c.cause_chain)
                    why = "; ".join(c.reasons).replace("|", "/")
                    lines.append(
                        f"| {idx} | {c.equipment_id} | {c.rule_id} | {c.topology_source} | {c.confidence:.3f} | "
                        f"{c.share:.0%} | `{chain}` | {why} |"
                    )
            elif not tr.unknown_upstream:
                lines.append("- No upstream fault or SI deviation candidates found.")

    return "\n".join(lines) + "\n"