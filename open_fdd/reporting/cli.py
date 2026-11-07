"""Headless CLI: Engineering Findings from a checklist JSON, a Normal Framework box (--nf) or the
NF app's CSV export (--csv)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _frames_from_source(args, p):
    """Equipment frames (SI role columns) from NF (--nf) or the app's CSV export (--csv)."""
    from open_fdd.nf.client import NFError

    try:
        if args.csv:
            from open_fdd.nf.export import csv_frames

            return csv_frames(args.csv), args.building
        import os
        from open_fdd.nf.client import NFClient, parse_nf_ts
        from open_fdd.nf.model import default_range, equipment_frames, load_model, site_name

        env = dict(os.environ)
        if args.url:
            env.update(NF_URL=args.url, NF_LAN_URL=args.url, NFURL=args.url)
        client = NFClient.from_env(via=args.via, env_file=args.env or None, env=env)
        model = load_model(client)
        start, end = (parse_nf_ts(args.start), parse_nf_ts(args.end)) if args.start and args.end else default_range(args.days)
        frames = equipment_frames(client, model, start, end, site=args.site, equip=args.equip)
        building = args.building or (site_name(model, args.site) if args.site else
                                     ", ".join((s.get("attrs") or {}).get("dis") or s.get("name", "") for s in model.sites))
        return frames, building
    except NFError as exc:
        p.error(str(exc))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Generate an FDD Engineering Findings Report (evidence-reviewed). "
            "Detection is not a finding; likely false positives stay in Appendix C. "
            "Agent knobs: --systems / --equipment-prefix / --rule-ids / "
            "--allow-priority / --pin-finding / --drop-finding / --write-inventory."
        )
    )
    p.add_argument("--checklist-json", type=Path, help="controls_service_checklist JSON")
    src = p.add_argument_group("history source (run the pandas rules on real data)")
    src.add_argument("--nf", action="store_true", help="pull history from a Normal Framework box (see open-fdd-nf)")
    src.add_argument("--csv", type=Path, help="the NF app's CSV export (Export tab); fully offline")
    src.add_argument("--url", help="with --nf: NF base URL (default: NF_URL / NF_LAN_URL / NFURL)")
    src.add_argument("--env", default="", metavar="FILE", help="with --nf: KEY=VALUE env file with NF_* settings")
    src.add_argument("--via", choices=("lan", "portal"), help="with --nf: which URL to prefer")
    src.add_argument("--site", help="with --nf: site id or name")
    src.add_argument("--equip", help="with --nf: one equipment id or name")
    src.add_argument("--days", type=float, default=7.0, help="with --nf: trailing days (default 7)")
    src.add_argument("--start", help="with --nf: ISO UTC start (use with --end)")
    src.add_argument("--end", help="with --nf: ISO UTC end")
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
    p.add_argument("--notes-file", type=Path, help="JSON object of ref to note (BUG-021)")
    p.add_argument(
        "--write-inventory",
        action="store_true",
        default=True,
        help="Write FAULT inventory JSON alongside report (default on) (BUG-023)",
    )
    p.add_argument("--no-inventory", action="store_true", help="Skip FAULT inventory export")
    args = p.parse_args(argv)

    out_dir = args.out_dir or args.out
    if out_dir is None:
        p.error("Provide --out-dir / --out")
    if not args.checklist_json and not (args.nf or args.csv):
        p.error("Provide --checklist-json and/or --nf / --csv")

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
    if args.nf or args.csv:
        frames, building = _frames_from_source(args, p)
        if not frames:
            p.error("no equipment history found for that source/range")
        from open_fdd.nf.report import build_overview_context
        from open_fdd.nf.rules import rule_results

        rule_results_list = rule_results(frames)
        rule_results = [r for _, _, r in rule_results_list]
        try:
            overview_context = build_overview_context(frames)
        except Exception as exc:  # soft-fail the Overview export path
            print(f"overview_context unavailable: {exc}", file=sys.stderr)
            overview_context = None

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
