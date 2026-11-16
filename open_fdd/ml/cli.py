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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open-fdd-ml", description="ML FDD benchmark (LBNL data) and ML detectors.")
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
    learned = list(getattr(det, "roles", []) or [])
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    handlers = {"download": _cmd_download, "benchmark": _cmd_benchmark, "detect": _cmd_detect}
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
