"""``open-fdd-ml``: ML FDD benchmark on public LBNL data, and ML detectors on a device folder.

Examples::

    open-fdd-ml download                              # LBNL single-duct AHU subset -> ~/.cache/open-fdd/lbnl
    open-fdd-ml benchmark --out bench.md --json bench.json
    open-fdd-ml detect ./AHU_1 --method pca --train-until 2026-06-01 --out ./ahu1_ml
    open-fdd-ml detect ./AHU_1 --method grey_box --train ./AHU_1_known_good --out ./ahu1_ml
    open-fdd-ml detect ./AHU_1 --method zscore --out ./ahu1_z            # no training needed

``detect`` reads the same device folder as ``open-fdd-anomaly`` (``history_wide.csv`` in SI + ``column_map.json``).
Learning methods (pca, grey_box, ocsvm, copod) need ONE explicit training source: ``--train`` (a folder the operator
asserts is known-good), ``--train-until`` (rows of FOLDER before that UTC date are training, the rest evaluation), or
``--exploratory-self-fit`` (fit on the rows being scored; labeled exploratory, never a healthy baseline). zscore/mad
need no training. ``flags.csv`` labels each row's ``phase``; summary counts cover evaluation rows only and
``summary.json`` records the training receipt. PCA adds ``contributions.csv`` and ``contributions.png``.
Needs ``pip install "open-fdd[ml]"``; ``--method copod`` also needs ``pyod``. Nothing here writes to a building system.
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

    det = sub.add_parser("detect", help="Fit a detector on known-good rows of a device folder and flag the rest",
                         description="Learning methods (pca, grey_box, ocsvm, copod) need exactly one training source: "
                                     "--train, --train-until or --exploratory-self-fit. zscore and mad need none.")
    det.add_argument("folder", type=Path, help="Device folder (history_wide.csv + column_map.json), SI values")
    det.add_argument("--method", choices=DETECT_METHODS, default="pca")
    source = det.add_mutually_exclusive_group()
    source.add_argument("--train", type=Path, default=None,
                        help="Device folder of history the operator asserts is known-good, to fit on")
    source.add_argument("--train-until", default=None,
                        help="Fit on rows of FOLDER before this UTC date/time (YYYY-MM-DD); score only the rows after")
    source.add_argument("--exploratory-self-fit", action="store_true",
                        help="Fit on the same rows being scored (exploration only; the output is labeled exploratory "
                             "and a recurring fault can become the baseline)")
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


LEARNING_HELP = "pass --train FOLDER, --train-until YYYY-MM-DD, or --exploratory-self-fit"


def _span(frame) -> dict:
    if len(frame) == 0:
        return {"start_utc": None, "end_utc": None}
    return {"start_utc": str(frame.index.min()), "end_utc": str(frame.index.max())}


def _identical_overlap(train, frame):
    """Timestamps present in both frames whose shared role values are all equal: the same data used twice."""
    import pandas as pd

    common_idx = frame.index.intersection(train.index)
    shared = [c for c in frame.columns if c in train.columns]
    if len(common_idx) == 0 or not shared:
        return pd.Index([]), int(len(common_idx))
    a = frame.loc[common_idx, shared]
    b = train.loc[common_idx, shared]
    a = a[~a.index.duplicated(keep="first")]
    b = b[~b.index.duplicated(keep="first")].reindex(a.index)
    same = ((a == b) | (a.isna() & b.isna())).all(axis=1)
    return a.index[same.to_numpy()], int(len(common_idx))


def _cmd_detect(args) -> int:
    import pandas as pd

    import open_fdd
    from open_fdd.ml.detectors import PCASPE, active_mask, canonical_roles, make_detector, plot_contributions

    frame = role_frame_from_folder(args.folder)
    det = make_detector(args.method, seed=args.seed)
    phase = pd.Series("evaluation", index=frame.index, dtype=object)
    overlap: dict = {}
    training: dict = {"source": "none", "used": False}
    train = frame.iloc[0:0]
    if det.needs_training:
        if args.train is not None:
            if args.train.resolve() == args.folder.resolve():
                raise ValueError("--train is the folder being scored; use --train-until or --exploratory-self-fit")
            train = role_frame_from_folder(args.train)
            training = {"source": "folder", "folder": str(args.train)}
        elif args.train_until:
            try:
                cut = pd.Timestamp(args.train_until)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"--train-until {args.train_until!r} is not a date/time") from exc
            cut = cut.tz_localize("UTC") if cut.tzinfo is None else cut.tz_convert("UTC")
            train = frame[frame.index < cut]
            phase[frame.index < cut] = "train"
            training = {"source": "cutoff", "cutoff_utc": str(cut)}
            if train.empty:
                raise ValueError(f"--train-until {cut} leaves no training rows (data starts {frame.index.min()})")
            if not (phase == "evaluation").any():
                raise ValueError(f"--train-until {cut} leaves no evaluation rows (data ends {frame.index.max()})")
        elif args.exploratory_self_fit:
            train = frame
            phase[:] = "exploratory_self_fit"
            training = {"source": "exploratory_self_fit",
                        "warning": "fitted on the rows it scores; flags are exploratory, not judged against a "
                                   "known-good baseline"}
        else:
            raise ValueError(f"--method {args.method} learns a baseline and needs a known-good training source: "
                             f"{LEARNING_HELP}")
        active_train = int(active_mask(canonical_roles(train)).sum()) if len(train) else 0
        training.update(_span(train), rows=int(len(train)), active_rows=active_train, used=True)
        if training["source"] in {"folder", "cutoff"}:
            training["assertion"] = "operator-asserted known-good (not an independently verified maintenance label)"
        if active_train == 0:
            raise ValueError(f"the training selection has no active rows ({len(train)} rows, fan off or missing)")
        det.fit(train)
    elif args.train is not None or args.train_until or args.exploratory_self_fit:
        training = {"source": "none", "used": False, "note": f"{args.method} needs no training; option ignored"}
    learned = list(getattr(det, "roles", []) or []) if det.needs_training else []
    if learned:
        target_cols = set(canonical_roles(frame).columns)
        lacking = [r for r in learned if r not in target_cols]
        if lacking:
            raise ValueError(f"the folder lacks role(s) the model was trained on: {', '.join(lacking)}")
    if training.get("source") == "folder":
        same, common = _identical_overlap(train, frame)
        if len(same):
            phase[frame.index.isin(same)] = "train_overlap"
        overlap = {"common_timestamps": common, "identical_rows_excluded": int(len(same)),
                   "policy": "rows identical to training rows are labeled train_overlap and excluded from evaluation"}
        if not (phase == "evaluation").any():
            raise ValueError("every row of FOLDER is also in the --train folder: no held-out evaluation rows")
    flags = det.flags(frame)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    active = active_mask(frame)
    table = pd.DataFrame({"phase": phase, "flag": flags.astype(int), "active": active.astype(int)})
    scores = det.scores(frame) if args.method in {"pca", "grey_box"} else None
    if scores is not None:
        table["score"] = scores
    table.to_csv(out / "flags.csv", index_label="timestamp_utc")
    scored = phase.isin(["evaluation", "exploratory_self_fit"])
    summary = {
        "method": args.method,
        "open_fdd_version": getattr(open_fdd, "__version__", None),
        "seed": args.seed,
        "exploratory": training.get("source") == "exploratory_self_fit",
        "folder_rows": int(len(frame)),
        "rows": int(scored.sum()),
        "active_rows": int((active & scored).sum()),
        "flagged_rows": int((flags & scored).sum()),
        "counts_cover": "evaluation rows only" if training.get("source") != "exploratory_self_fit"
        else "every row (exploratory self-fit)",
        "evaluation": _span(frame[scored.to_numpy()]),
        "train_rows": int(len(train)) if det.needs_training else 0,
        "training": training,
        "roles": list(getattr(det, "roles", []) or frame.columns),
        "units": "SI (device-folder contract)",
    }
    if overlap:
        summary["training_overlap"] = overlap
    from open_fdd.analytics.anomaly.activity import activity

    summary["activity"] = activity(frame, policy="proof").receipt()
    if args.method == "pca" and isinstance(det, PCASPE):
        contrib = det.contributions(frame)
        contrib.to_csv(out / "contributions.csv", index_label="timestamp_utc")
        top = contrib[flags & scored].mean().sort_values(ascending=False)
        summary["spe_threshold"] = det.threshold_
        summary["top_contributors"] = {k: round(float(v), 4) for k, v in top.head(5).items() if pd.notna(v)}
        try:
            plot_contributions(contrib, flags & scored, out / "contributions.png")
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
