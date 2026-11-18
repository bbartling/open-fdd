"""open-fdd-scorecard: score FDD rule results from ANY SQL database against fault labels.

    open-fdd-scorecard sql                                   # print the portable SQL (run it in your own DB)
    open-fdd-scorecard export --results r.csv [--history h.csv --point-map points.csv] [--labels l.csv] \\
        --out BUNDLE_DIR --private-dir KEEP_LOCAL [--shift-days 364] [--window-hours 6]   # owner side
    open-fdd-scorecard unalias --verdicts BUNDLE_DIR/verdicts.csv --private-dir KEEP_LOCAL --out verdicts_real.csv
    open-fdd-scorecard check BUNDLE_DIR                      # validate an offline export bundle
    open-fdd-scorecard template BUNDLE_DIR --out verdicts.csv  # blank verdict rows for every unreviewed FAULT
    open-fdd-scorecard run --bundle BUNDLE_DIR [--prior ...] [--md card.md]
    open-fdd-scorecard run --results results.csv --labels labels.csv \\
        [--config columns.json] [--prior lbnl_scorecard.json --prior-weight 20] \\
        [--json card.json] [--md card.md] [--queue review_queue.csv]

results.csv: one row per rule result window (equipment_id, rule_id, window_start, window_end, status).
labels.csv:  equipment_id, start_ts, end_ts, label (fault/normal), [rule_id], [fault_type], [source].
Column names and status / label values are mapped with --config; nothing is site-specific.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from open_fdd.scorecard import bundle
from open_fdd.scorecard.core import SQL_PATH, load_config, read_csv, score, to_markdown


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="open-fdd-scorecard", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sql", help="Print the portable scorecard SQL")
    ex = sub.add_parser("export", help="Owner side: build a privacy-preserving review bundle from local CSV exports")
    ex.add_argument("--results", required=True, type=Path)
    ex.add_argument("--history", type=Path, default=None, help="Long CSV: ts, equipment_id, point, value (SI)")
    ex.add_argument("--point-map", type=Path, default=None, help="CSV: point, role [, equipment_id]")
    ex.add_argument("--labels", type=Path, default=None, help="Owner labels already known (optional)")
    ex.add_argument("--config", type=Path, default=None)
    ex.add_argument("--out", type=Path, required=True, help="Bundle folder (this is what you send)")
    ex.add_argument("--private-dir", type=Path, required=True, help="Re-identification files (never send)")
    ex.add_argument("--window-hours", type=float, default=6.0, help="History kept around each FAULT window")
    ex.add_argument("--shift-days", type=int, default=0, help="Shift all times (use a multiple of 7)")
    ex.add_argument("--no-alias", action="store_true", help="Keep equipment ids as they are")
    ex.add_argument("--source-note", default="", help="Free text for the manifest (no site names)")
    un = sub.add_parser("unalias", help="Owner side: map a filled verdict sheet back to real ids and times")
    un.add_argument("--verdicts", required=True, type=Path)
    un.add_argument("--private-dir", required=True, type=Path)
    un.add_argument("--out", required=True, type=Path)
    chk = sub.add_parser("check", help="Validate an offline export bundle (see open_fdd.scorecard.bundle)")
    chk.add_argument("bundle", type=Path)
    tpl = sub.add_parser("template", help="Write a verdict template for every unreviewed FAULT in a bundle")
    tpl.add_argument("bundle", type=Path)
    tpl.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("run", help="Score results against labels (CSV files or a bundle folder)")
    run.add_argument("--bundle", type=Path, default=None, help="Bundle folder (rule_results.csv, labels.csv, ...)")
    run.add_argument("--results", type=Path, default=None)
    run.add_argument("--labels", type=Path, default=None)
    run.add_argument("--config", type=Path, default=None, help="JSON column / value mapping")
    run.add_argument("--prior", type=Path, default=None, help="A previous scorecard JSON used as a Beta prior")
    run.add_argument("--prior-weight", type=float, default=20.0, help="Pseudo-verdicts the prior is worth")
    run.add_argument("--prevalence", type=float, default=None,
                     help="Expected share of truly faulted windows at the target site (re-weights precision)")
    run.add_argument("--json", type=Path, default=None)
    run.add_argument("--md", type=Path, default=None)
    run.add_argument("--queue", type=Path, default=None, help="CSV of unlabeled FAULT windows to review")
    args = ap.parse_args(argv)
    if args.cmd == "sql":
        sys.stdout.write(SQL_PATH.read_text(encoding="utf-8"))
        return 0
    if args.cmd == "export":
        from open_fdd.scorecard import export
        if args.shift_days % 7:
            print("warning: --shift-days is not a multiple of 7; day-of-week schedules will move", file=sys.stderr)
        stats = export.build(results=args.results, out=args.out, private_dir=args.private_dir,
                             history=args.history, point_map=args.point_map, labels=args.labels,
                             cfg=load_config(args.config), window_hours=args.window_hours,
                             shift_days=args.shift_days, alias=not args.no_alias, source_note=args.source_note)
        print(json.dumps(stats, indent=2))
        return 0
    if args.cmd == "unalias":
        from open_fdd.scorecard import export
        print(f"{export.unalias(args.verdicts, args.private_dir, args.out)} verdicts -> {args.out}")
        return 0
    if args.cmd == "check":
        report = bundle.check(args.bundle)
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return 0 if report["ok"] else 1
    if args.cmd == "template":
        n = bundle.verdict_template(args.bundle, args.out)
        print(f"{n} unreviewed FAULT windows -> {args.out}")
        return 0
    prior = json.loads(args.prior.read_text(encoding="utf-8")) if args.prior else None
    if args.bundle:
        report = bundle.check(args.bundle)
        if not report["ok"]:
            sys.stderr.write("bundle check failed: " + "; ".join(report["errors"]) + "\n")
            return 1
        results, labels, cfg = bundle.load(args.bundle)
        if args.config:
            cfg = load_config(args.config)
    elif args.results and args.labels:
        results, labels, cfg = read_csv(args.results), read_csv(args.labels), load_config(args.config)
    else:
        ap.error("run needs --bundle, or both --results and --labels")
    card = score(results, labels, cfg, prior=prior, prior_weight=args.prior_weight, prevalence=args.prevalence)
    md = to_markdown(card)
    if args.json:
        args.json.write_text(json.dumps(card, indent=2), encoding="utf-8")
    if args.md:
        args.md.write_text(md, encoding="utf-8")
    if args.queue:
        with open(args.queue, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["equipment_id", "rule_id", "window_start", "window_end",
                                               "p_true_fault"])
            w.writeheader()
            w.writerows(card["review_queue"])
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
