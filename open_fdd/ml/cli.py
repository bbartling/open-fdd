"""``open-fdd-ml``: ML FDD benchmark on public LBNL data, and ML detectors on a device folder.

Examples::

    open-fdd-ml download                              # LBNL single-duct AHU subset -> ~/.cache/open-fdd/lbnl
    open-fdd-ml benchmark --out bench.md --json bench.json
    open-fdd-ml detect ./AHU_1 --method pca --train-until 2026-06-01 --out ./ahu1_ml
    open-fdd-ml detect ./AHU_1 --method grey_box --train ./AHU_1_known_good --out ./ahu1_ml

``detect`` reads the same device folder as ``open-fdd-anomaly`` (``history_wide.csv`` in SI + ``column_map.json``),
fits on known-good rows (``--train`` folder or rows before ``--train-until``) and writes ``flags.csv`` and
``summary.json`` (PCA adds ``contributions.csv`` and ``contributions.png``). Needs ``pip install "open-fdd[ml]"``;
``--method copod`` also needs ``pyod``. Nothing here writes to a building system.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DETECT_METHODS = ("pca", "grey_box", "ocsvm", "copod", "zscore", "mad")


FOLDER_EPILOG = """device folder format (read by open-fdd-ml detect and open-fdd-anomaly screen/report):
  history_wide.csv   timestamp_utc (ISO 8601, UTC) + one column per point, SI values:
                     degC, Pa, fractions 0-1 (commands may be 0-100 %), status 0/1
  column_map.json    {"equipType": "AHU", "points": {"discharge-air-temp": "SAT", "fan-status": "SF_S"}}
                     roles are Haystack-style names or their short aliases (--list-roles)

examples:
  open-fdd-ml make-folder trend.csv --out AHU_1 --time-col Time --tz America/Chicago \\
      --map discharge-air-temp=SAT --map mixed-air-temp=MAT --map outside-air-temp=OAT --map fan-status=SF_S
  open-fdd-ml make-folder --from-lbnl ~/.cache/open-fdd/lbnl/AHU_annual.csv --from 2018-06-01 --to 2018-06-30 --out AHU_1
  open-fdd-ml make-folder --example --out demo_AHU
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-fdd-ml",
        description="ML FDD benchmark (LBNL data) and ML detectors. "
                    "`open-fdd-ml methods [FOLDER]` lists each method's required roles and which can run on FOLDER. "
                    "`open-fdd-ml make-folder --help` describes the device folder format and builds one.",
    )
    sub = parser.add_subparsers(dest="command")

    dl = sub.add_parser("download", help="Fetch the LBNL single-duct AHU subset into the cache (CC BY 4.0)")
    dl.add_argument("--cache", type=Path, default=None, help="Cache dir (default $OPENFDD_ML_CACHE or ~/.cache/open-fdd/lbnl)")
    dl.add_argument("--files", default=None, help="Comma-separated file names (default: the benchmark subset)")
    dl.add_argument("--force", action="store_true", help="Download again even when cached")

    bench = sub.add_parser("benchmark", help="Score the rule pack and the ML detectors on the cached LBNL subset")
    bench.add_argument("--cache", type=Path, default=None, help="Cache dir with the LBNL CSVs")
    bench.add_argument("--download", action="store_true", help="Download missing files first")
    bench.add_argument("--methods", default="rules,pca,grey_box,ocsvm,copod,zscore,mad",
                       help="Comma-separated: rules,pca,grey_box,ocsvm,copod,zscore,mad")
    bench.add_argument("--seed", type=int, default=0)
    bench.add_argument("--out", type=Path, default=None, help="Write the Markdown table here (default: stdout)")
    bench.add_argument("--json", type=Path, default=None, help="Write every score and detail as JSON")
    meth = sub.add_parser("methods", help="List each detector's required roles; with FOLDER, which can run there and why not")
    meth.add_argument("folder", type=Path, nargs="?", default=None, help="Device folder to check (optional)")
    meth.add_argument("--json", action="store_true", help="Print JSON instead of text")
    mk = sub.add_parser(
        "make-folder",
        help="Build a device folder (history_wide.csv + column_map.json) from a CSV, an LBNL file or an example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=FOLDER_EPILOG,
    )
    mk.add_argument("csv", type=Path, nargs="?", default=None, help="Wide CSV with a time column and one column per point")
    mk.add_argument("--out", type=Path, default=None, help="Folder to write")
    mk.add_argument("--map", action="append", default=[], metavar="ROLE=COLUMN",
                    help="Role for a CSV column, repeatable (e.g. --map discharge-air-temp=SAT --map fan-status=SF_S)")
    mk.add_argument("--time-col", default="timestamp_utc", help="Time column of CSV (default timestamp_utc)")
    mk.add_argument("--tz", default="UTC", help="Zone of naive time stamps in CSV (default UTC), e.g. America/Chicago")
    mk.add_argument("--equip-type", default="AHU", help="equipType for column_map.json (default AHU)")
    mk.add_argument("--from-lbnl", type=Path, default=None, metavar="FILE",
                    help="An LBNL SDAHU CSV from open-fdd-ml download (roles and SI units are mapped for you)")
    mk.add_argument("--from", dest="start", default=None, help="First UTC date to keep (YYYY-MM-DD)")
    mk.add_argument("--to", dest="end", default=None, help="Last UTC date to keep (YYYY-MM-DD, inclusive)")
    mk.add_argument("--example", action="store_true", help="Write a small synthetic two-day AHU folder")
    mk.add_argument("--list-roles", action="store_true", help="Print the role names (short alias -> role) and exit")

    det = sub.add_parser("detect", help="Fit a detector on known-good rows of a device folder and flag the rest")
    det.add_argument("folder", type=Path, help="Device folder (history_wide.csv + column_map.json), SI values")
    det.add_argument("--method", choices=DETECT_METHODS, default="pca")
    det.add_argument("--train", type=Path, default=None, help="Device folder of known-good history to fit on")
    det.add_argument("--train-until", default=None, help="Fit on rows before this UTC date (YYYY-MM-DD) of FOLDER")
    det.add_argument("--out", type=Path, required=True, help="Output directory")
    det.add_argument("--seed", type=int, default=0)
    return parser


def role_frame_from_folder(folder: Path):
    """A device folder as a frame of Haystack role columns (``open_fdd.analytics.anomaly.io`` + role aliases)."""
    import pandas as pd

    from open_fdd.analytics.anomaly.io import load_device_folder
    from open_fdd.ml.detectors import canonical_roles

    device = load_device_folder(folder, ahu_only=False)
    cols = {}
    for role, column in device.points:
        if role not in cols:
            cols[role] = pd.to_numeric(device.frame[column], errors="coerce")
    frame = canonical_roles(pd.DataFrame(cols, index=device.frame.index))
    if frame.empty or frame.shape[1] == 0:
        raise ValueError(f"{folder}: no mapped roles found in column_map.json")
    return frame


def _cmd_download(args) -> int:
    from open_fdd.ml import lbnl

    names = [n.strip() for n in args.files.split(",")] if args.files else None
    for path in lbnl.download(names, args.cache, force=args.force):
        print(path)
    print(lbnl.ATTRIBUTION)
    return 0


def _cmd_benchmark(args) -> int:
    from open_fdd.ml.benchmark import run_benchmark, to_markdown

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    result = run_benchmark(args.cache, methods=methods, seed=args.seed, download=args.download,
                           log=lambda msg: print(msg, file=sys.stderr))
    text = to_markdown(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result.to_json(), indent=1, default=str), encoding="utf-8")
    return 0


def _cmd_detect(args) -> int:
    import pandas as pd

    from open_fdd.ml.detectors import PCASPE, active_mask, make_detector, plot_contributions

    frame = role_frame_from_folder(args.folder)
    if args.train is not None:
        train = role_frame_from_folder(args.train)
    elif args.train_until:
        cut = pd.Timestamp(args.train_until, tz="UTC")
        train = frame[frame.index < cut]
    else:
        train = frame
    det = make_detector(args.method, seed=args.seed)
    if det.needs_training:
        if train.empty:
            raise ValueError("no training rows: pass --train or a --train-until inside the data")
        det.fit(train)
    learned = list(getattr(det, "roles", []) or []) if det.needs_training else []
    if learned:
        from open_fdd.ml.detectors import canonical_roles

        target_cols = set(canonical_roles(frame).columns)
        lacking = [r for r in learned if r not in target_cols]
        if lacking:
            raise ValueError(f"the folder lacks role(s) the model was trained on: {', '.join(lacking)}")
    flags = det.flags(frame)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame({"flag": flags.astype(int), "active": active_mask(frame).astype(int)})
    scores = det.scores(frame) if args.method in {"pca", "grey_box"} else None
    if scores is not None:
        table["score"] = scores
    table.to_csv(out / "flags.csv", index_label="timestamp_utc")
    summary = {
        "method": args.method,
        "rows": int(len(frame)),
        "active_rows": int(table["active"].sum()),
        "flagged_rows": int(table["flag"].sum()),
        "train_rows": int(len(train)) if det.needs_training else 0,
        "roles": list(getattr(det, "roles", []) or frame.columns),
    }
    if args.method == "pca" and isinstance(det, PCASPE):
        contrib = det.contributions(frame)
        contrib.to_csv(out / "contributions.csv", index_label="timestamp_utc")
        top = contrib[flags].mean().sort_values(ascending=False)
        summary["spe_threshold"] = det.threshold_
        summary["top_contributors"] = {k: round(float(v), 4) for k, v in top.head(5).items() if pd.notna(v)}
        try:
            plot_contributions(contrib, flags, out / "contributions.png")
        except ImportError:
            pass
    if args.method == "grey_box":
        summary["thresholds"] = getattr(det, "thresholds_", {})
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, default=str))
    return 0


def _cmd_make_folder(args) -> int:
    from open_fdd.ml import folder as fm

    if args.list_roles:
        for short, role in fm.role_names().items():
            print(f"{short:28s} {role}")
        return 0
    if args.out is None:
        raise ValueError("--out is required")
    chosen = [bool(args.example), args.from_lbnl is not None, args.csv is not None]
    if sum(chosen) != 1:
        raise ValueError("pass exactly one source: CSV, --from-lbnl FILE or --example")
    if args.example:
        path = fm.example_folder(args.out)
    elif args.from_lbnl is not None:
        path = fm.folder_from_lbnl(args.from_lbnl, args.out, start=args.start, end=args.end)
    else:
        mapping = {}
        for item in args.map:
            role, sep, column = str(item).partition("=")
            if not sep or not role.strip() or not column.strip():
                raise ValueError(f"--map needs ROLE=COLUMN, got {item!r}")
            mapping[role.strip()] = column.strip()
        path, warnings = fm.folder_from_csv(args.csv, args.out, mapping=mapping, time_col=args.time_col, tz=args.tz,
                                            equip_type=args.equip_type, start=args.start, end=args.end)
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    print(json.dumps({"folder": str(path), "files": ["history_wide.csv", "column_map.json"]}))
    return 0


def _cmd_methods(args) -> int:
    from open_fdd.ml.applicability import METHOD_REQUIREMENTS, applicability, requirements_text

    if args.folder is None:
        print(json.dumps(METHOD_REQUIREMENTS, indent=1) if args.json else requirements_text())
        return 0
    rows = applicability(role_frame_from_folder(args.folder))
    if args.json:
        print(json.dumps({"folder": str(args.folder), "methods": rows}, indent=1))
        return 0
    print(requirements_text())
    print(f"\n{args.folder}:")
    for row in rows:
        state = "can run" if row["can_run"] else "cannot run"
        detail = f"roles {', '.join(row['roles'])}" if row["can_run"] else row["reason"]
        print(f"  {row['method']:9s} {state}: {detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    handlers = {"download": _cmd_download, "benchmark": _cmd_benchmark, "detect": _cmd_detect,
                "methods": _cmd_methods, "make-folder": _cmd_make_folder}
    if args.command not in handlers:
        parser.print_help()
        return 2
    try:
        return handlers[args.command](args)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
