"""Headless CLI: Engineering Findings from checklist JSON and/or WattLab dump package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _overview_context_from_dataset(ds) -> dict:
    """Build overview_context from an AgentDataset (frames + session knobs)."""
    from open_fdd.analytics.core import dataset_time_span
    from open_fdd.analytics.occupancy import OccupancySchedule, occupied_hours_per_week
    from open_fdd.reporting.overview_export import build_overview_context

    frames = getattr(ds, "frames", None) or {}
    span = dataset_time_span(frames) if frames else {}
    session = getattr(ds, "session_config", None) or {}
    params = getattr(ds, "params", None) or session.get("params") or {}
    oat_err = 5.0
    try:
        oat_err = float((params.get("OAT-METEO") or {}).get("oat_err", 5.0))
    except (TypeError, ValueError):
        oat_err = 5.0
    sched = OccupancySchedule.from_dict(session.get("occupancy_schedule"))
    return build_overview_context(
        frames=frames,
        role_map=getattr(ds, "role_map", None) or {},
        weather=getattr(ds, "weather", None),
        prefer_web_oat=bool(getattr(ds, "prefer_web_oat", session.get("prefer_web_oat", True))),
        oat_err=oat_err,
        chw_leave_max_f=float(
            getattr(ds, "chw_leave_max_f", None) or session.get("chw_leave_max_f", 48.0)
        ),
        use_status_proof=bool(
            getattr(
                ds,
                "use_mech_cooling_status_proof",
                session.get("use_mech_cooling_status_proof", True),
            )
        ),
        zone_lo_f=float(session.get("zone_lo_f", 70.0)),
        zone_hi_f=float(session.get("zone_hi_f", 75.0)),
        bare_min_occ_hours=float(occupied_hours_per_week(sched)),
        occupancy_schedule=sched.to_dict(),
        dataset_start=span.get("start"),
        dataset_end=span.get("end"),
        span_hours=span.get("span_hours"),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Generate an FDD Engineering Findings Report (evidence-reviewed). "
            "Detection ≠ finding; likely false positives stay in Appendix C. "
            "Agent knobs: --systems / --equipment-prefix / --rule-ids / "
            "--allow-priority / --pin-finding / --drop-finding / --write-inventory."
        )
    )
    p.add_argument("--checklist-json", type=Path, help="controls_service_checklist JSON")
    p.add_argument("--dump", type=Path, help="WattLab dump / vibe19 package zip or folder")
    p.add_argument("--package", type=Path, help="Alias for --dump (agent-friendly)")
    p.add_argument("--building", default="", help="Override building name")
    p.add_argument("--out-dir", type=Path, help="Output directory")
    p.add_argument("--out", type=Path, help="Alias for --out-dir")
    p.add_argument("--docx", action="store_true")
    p.add_argument("--xlsx", action="store_true", help="Punchlist-first Excel notebook (BUG notebook)")
    p.add_argument("--json", action="store_true", dest="json_out")
    p.add_argument("--no-charts", action="store_true")
    p.add_argument("--max-findings", type=int, default=7, help="Priority pack size (default 7)")
    p.add_argument(
        "--allow-priority",
        type=int,
        default=None,
        metavar="N",
        help="Explicit raise: authorize up to N priority findings (quality gate). "
        "Required when --max-findings > 7.",
    )
    p.add_argument(
        "--raise-max-findings",
        action="store_true",
        help="Shorthand: set --allow-priority to the same value as --max-findings",
    )
    p.add_argument("--systems", default="", help="Scope systems CSV e.g. VAV or VAV,AHU (BUG-019)")
    p.add_argument(
        "--equipment-prefix",
        default="",
        help="Scope equipment id prefixes CSV e.g. VAV (BUG-019)",
    )
    p.add_argument(
        "--rule-ids",
        default="",
        help="Scope exact cookbook rule ids CSV e.g. VAV-4,VAV-5,SV-FLATLINE (BUG-019)",
    )
    p.add_argument(
        "--boost-terminal",
        action="store_true",
        help="Prefer VAV/terminal FAULTs over plant when ranking (BUG-019)",
    )
    p.add_argument(
        "--pin-finding",
        action="append",
        default=[],
        metavar="REF",
        help="Force-include finding (equipment:rule or equipment|rule). Repeatable (BUG-021)",
    )
    p.add_argument(
        "--drop-finding",
        action="append",
        default=[],
        metavar="REF",
        help="Exclude finding from priority even if ranked high. Repeatable (BUG-021)",
    )
    p.add_argument(
        "--note",
        action="append",
        default=[],
        metavar="REF=TEXT",
        help="Attach field note (BUG-021). Repeatable.",
    )
    p.add_argument("--notes-file", type=Path, help="JSON object of ref → note (BUG-021)")
    p.add_argument(
        "--write-inventory",
        action="store_true",
        default=True,
        help="Write FAULT inventory JSON alongside report (default on) (BUG-023)",
    )
    p.add_argument("--no-inventory", action="store_true", help="Skip FAULT inventory export")
    p.add_argument("--run-rules", action="store_true", help="With --dump, also run cookbook FAULTs")
    args = p.parse_args(argv)

    dump = args.dump or args.package
    out_dir = args.out_dir or args.out
    if out_dir is None:
        p.error("Provide --out-dir / --out")
    if not args.checklist_json and not dump:
        p.error("Provide --checklist-json and/or --dump/--package")

    allow_priority = args.allow_priority
    if args.raise_max_findings:
        allow_priority = args.max_findings

    from open_fdd.reporting.hitl import load_notes_file, parse_note_arg
    from open_fdd.reporting.pipeline import build_engineering_findings, render_engineering_report
    from open_fdd.reporting.scope import FindingScope

    notes: dict[str, str] = {}
    if args.notes_file:
        notes.update(load_notes_file(args.notes_file))
    for raw in args.note or []:
        ref, text = parse_note_arg(raw)
        notes[ref] = text

    scope = FindingScope.from_cli(
        systems=args.systems or None,
        equipment_prefix=args.equipment_prefix or None,
        rule_ids=args.rule_ids or None,
        boost_terminal=bool(args.boost_terminal),
    )

    rule_results = None
    overview_context = None
    building = args.building
    if dump:
        try:
            from open_fdd.analytics.agent_bridge import load_package_path, run_rules
        except ImportError as exc:  # pragma: no cover - host app provides bridge
            raise SystemExit(
                "Dump/run-rules requires a host bridge (vibe19 agent_api). "
                f"Import failed: {exc}"
            ) from exc

        ds = load_package_path(dump)
        building = building or getattr(ds, "building_id", "") or ""
        try:
            overview_context = _overview_context_from_dataset(ds)
        except Exception as exc:  # soft-fail Overview export path
            print(f"overview_context unavailable: {exc}", file=sys.stderr)
            overview_context = None
        if args.run_rules:
            run = run_rules(ds)
            rule_results = run.results

    write_inv = bool(args.write_inventory) and not args.no_inventory
    artifacts = build_engineering_findings(
        building=building,
        checklist=args.checklist_json,
        rule_results=rule_results,
        overview_context=overview_context,
        max_findings=args.max_findings,
        allow_priority=allow_priority,
        scope=scope,
        pin_findings=list(args.pin_finding or []),
        drop_findings=list(args.drop_finding or []),
        notes=notes,
        write_inventory=write_inv,
    )
    written = render_engineering_report(
        artifacts,
        out_dir,
        docx=args.docx,
        json_out=args.json_out or not args.docx,
        charts=not args.no_charts,
        xlsx=bool(args.xlsx),
        overview_context=overview_context,
        rule_results=rule_results,
        write_inventory=write_inv,
    )
    print(json.dumps({k: str(v) for k, v in written.items()}, indent=2))
    print("metrics", json.dumps(artifacts.metrics))
    print("quality_gate", json.dumps(artifacts.quality_gate))
    if not artifacts.quality_gate.get("ok"):
        print("QUALITY_GATE_ERRORS", artifacts.quality_gate.get("errors"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
