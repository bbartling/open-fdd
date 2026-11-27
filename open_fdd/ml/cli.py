"""``open-fdd-ml``: ML FDD benchmark on public LBNL data, and ML detectors on a device folder.

Examples::

    open-fdd-ml download                              # LBNL single-duct AHU subset -> ~/.cache/open-fdd/lbnl
    open-fdd-ml export --out ./lbnl_long              # history_long.csv (roles, SI) + labels.csv for open-fdd-scorecard
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

    from open_fdd.ml import confidence as _confidence

    conf = sub.add_parser("confidence", help="Score rule fault episodes as likely real, false positive or tuning (advisory)",
                          description=_confidence.DESCRIPTION)
    _confidence.add_arguments(conf)

    dl = sub.add_parser("download", help="Fetch the 8-file LBNL single-duct AHU subset (about 1.1 GB of CSV on disk) into the cache",
                        description="Fetch the LBNL single-duct AHU (SDAHU) benchmark files from fdddata.lbl.gov "
                                    "(DOI 10.25984/1881324, CC BY 4.0). Only the needed zip members are read with HTTP "
                                    "range requests (about 30 MB compressed each, about 240 MB in all); the 8 "
                                    "default CSVs take about 1.1 GB on disk. Nothing is uploaded.")
    dl.add_argument("--cache", type=Path, default=None, help="Cache dir (default $OPENFDD_ML_CACHE or ~/.cache/open-fdd/lbnl)")
    dl.add_argument("--files", default=None, help="Comma-separated file names (default: the benchmark subset)")
    dl.add_argument("--force", action="store_true", help="Download again even when cached")

    ex = sub.add_parser("export", help="Write cached LBNL files as long-format SI history + labels.csv for any SQL DB")
    ex.add_argument("--cache", type=Path, default=None, help="Cache dir with the LBNL CSVs")
    ex.add_argument("--files", default=None, help="Comma-separated file names (default: the benchmark subset)")
    ex.add_argument("--download", action="store_true", help="Download missing files first")
    ex.add_argument("--step-minutes", type=int, default=5)
    ex.add_argument("--out", type=Path, required=True, help="Output directory")

    bench = sub.add_parser("benchmark", help="Score the rule pack and the ML detectors on the cached LBNL subset")
    bench.add_argument("--cache", type=Path, default=None, help="Cache dir with the LBNL CSVs")
    bench.add_argument("--download", action="store_true", help="Download missing files first")
    bench.add_argument("--methods", default="rules,pca,grey_box,ocsvm,copod,zscore,mad",
                       help="Comma-separated: rules,pca,grey_box,ocsvm,copod,zscore,mad")
    bench.add_argument("--seed", type=int, default=0,
                       help="Random seed for the ocsvm / copod training subsample; default 0")
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

    det = sub.add_parser("detect", help="Fit a detector on known-good rows of a device folder and flag the rest",
                         description="Learning methods (pca, grey_box, ocsvm, copod) need exactly one training source: "
                                     "--train, --train-until or --exploratory-self-fit. zscore and mad need none.")
    det.add_argument("folder", type=Path, help="Device folder (history_wide.csv + column_map.json), SI values")
    det.add_argument("--method", choices=DETECT_METHODS, default="pca", metavar="METHOD",
                     help="pca (default): PCA / SPE on the feature roles, with per-role contributions; "
                          "grey_box: physics residuals (mixed-air balance, coil delta-T, SAT error); "
                          "ocsvm / copod: one novelty model per operating mode (copod needs pyod); "
                          "zscore / mad: rolling per-role screens, no training. "
                          "The first four need a training source")
    source = det.add_mutually_exclusive_group()
    source.add_argument("--train", type=Path, default=None,
                        help="Device folder of history the operator asserts is known-good, to fit on")
    source.add_argument("--train-until", default=None,
                        help="Fit on rows of FOLDER before this date/time (YYYY-MM-DD[THH:MM]) and score only the rows "
                             "after. It is compared with timestamp_utc; a value without a zone is read as "
                             "UTC, the same convention as timestamps written without a zone (e.g. LBNL files)")
    source.add_argument("--exploratory-self-fit", action="store_true",
                        help="Fit on the same rows being scored (exploration only; the output is labeled exploratory "
                             "and a recurring fault can become the baseline)")
    det.add_argument("--out", type=Path, required=True, help="Output directory")
    det.add_argument("--seed", type=int, default=0,
                     help="Random seed for the ocsvm / copod training subsample; default 0")
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


def _cmd_export(args) -> int:
    from open_fdd.ml import lbnl

    names = [n.strip() for n in args.files.split(",")] if args.files else [f.name for f in lbnl.SDAHU_SUBSET]
    cache = Path(args.cache) if args.cache else lbnl.default_cache_dir()
    if args.download:
        lbnl.download(names, cache)
    missing = [n for n in names if not (cache / n).is_file()]
    if missing:
        print(f"not in the cache {cache}: {', '.join(missing)} (run open-fdd-ml download or pass --download)",
              file=sys.stderr)
        return 2
    paths = lbnl.export_long([cache / n for n in names], args.out, step_minutes=args.step_minutes)
    for path in paths.values():
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


#: Roles behind each AHU gray-box residual (the single-zone families come from ``grey_box_families`` when present).
_GREY_BOX_ROLES = {
    "oa_fraction": ["mixed-air-temp", "return-air-temp", "outside-air-temp", "outside-air-damper"],
    "coil_delta_t": ["mixed-air-temp", "discharge-air-temp", "cooling-valve"],
    "sat_error": ["discharge-air-temp", "discharge-air-temp-sp", "cooling-valve"],
}


def _role_report(det, frame) -> dict:
    """Configured, used and missing roles (#1660): ``roles`` is the set actually scored."""
    from open_fdd.ml import detectors as dm

    present = set(dm.canonical_roles(frame).columns)
    if isinstance(det, dm.GreyBox):
        families = getattr(dm, "grey_box_families", None)
        role_sets = {**_GREY_BOX_ROLES, **(families(present) if families else {})}
        fitted = set(getattr(det, "thresholds_", {}) or {})
        usable = sorted(k for k in det._raw(frame) if k in fitted)
        used = sorted({r for k in usable for r in role_sets.get(k, [])})
        configured = sorted({r for roles in _GREY_BOX_ROLES.values() for r in roles} |
                            {r for roles in role_sets.values() for r in roles})
        return {"roles": used, "roles_used": used, "roles_configured": configured,
                "roles_missing": [r for r in configured if r not in present], "residuals_used": usable}
    configured = list(getattr(det, "feature_roles", None) or getattr(det, "roles", None) or dm.FEATURE_ROLES)
    used = det.scored_roles(frame) if isinstance(det, dm.RollingAnomaly) else list(getattr(det, "roles", []) or [])
    return {"roles": used, "roles_used": used, "roles_configured": configured,
            "roles_missing": [r for r in configured if r not in present]}


def _row_argmax(values):
    """Column name of each row's largest value; empty where the row has no value."""
    has = values.notna().any(axis=1)
    top = values.fillna(float("-inf")).idxmax(axis=1)
    return top.where(has, "")


def _explanations(det, frame, flags):
    """Per-row explanation columns for flags.csv (#1660); blank on rows that are not flagged."""
    import pandas as pd

    from open_fdd.ml.detectors import PCASPE, GreyBox, RollingAnomaly

    out = pd.DataFrame(index=frame.index)
    on = flags.reindex(frame.index).fillna(False).astype(bool)
    if isinstance(det, PCASPE):
        contrib = det.contributions(frame)
        top = _row_argmax(contrib)
        out["top_role"] = top.where(on, "")
        out["top_share"] = contrib.max(axis=1).round(4).where(on)
    elif isinstance(det, GreyBox):
        resid = det.residuals(frame)
        ratios = pd.DataFrame({k: resid[k].abs() / max(det.thresholds_[k], 1e-9) for k in resid.columns},
                              index=frame.index)
        for k in ratios.columns:
            out[f"ratio_{k}"] = ratios[k].round(4)
        top = _row_argmax(ratios) if len(ratios.columns) else None
        out["top_residual"] = top.where(on, "") if top is not None else ""
    elif isinstance(det, RollingAnomaly):
        per = det.role_flags(frame)
        names = per.apply(lambda row: ";".join(c for c in per.columns if row[c]), axis=1) if len(per.columns) else ""
        out["flagged_roles"] = names.where(on, "") if len(per.columns) else ""
    return out


def _assessment_report(assessment, active, scored) -> dict:
    """Assessed vs unassessed scored rows (#1666): a row the model could not judge is never counted as healthy."""
    if assessment is None:
        return {"assessed_rows": None, "assessed_coverage": None,
                "assessment_note": "this method does not report per-row assessment; flagged_rows covers active rows"}
    pool = active.to_numpy() & scored.to_numpy()
    states = assessment[pool]
    n_active = int(pool.sum())
    assessed = int((states == "assessed").sum())
    reasons = {str(k): int(v) for k, v in states[states != "assessed"].value_counts().sort_index().items()}
    report = {"assessed_rows": assessed, "unassessed_rows": n_active - assessed, "unassessed_reasons": reasons,
              "assessed_coverage": round(assessed / n_active, 4) if n_active else None}
    if not n_active:
        report["assessed_coverage_reason"] = "no active scored rows"
    return report


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
    assessment = det.assessment(frame).reindex(frame.index) if hasattr(det, "assessment") else None
    if assessment is not None:
        table["assessment"] = assessment
    explain = _explanations(det, frame, flags)
    for col in explain.columns:
        table[col] = explain[col]
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
        **_role_report(det, frame),
        "units": "SI (device-folder contract)",
    }
    summary.update(_assessment_report(assessment, active, scored))
    if overlap:
        summary["training_overlap"] = overlap
    from open_fdd.analytics.anomaly.activity import activity

    # scoped like the other counts: the scored (evaluation) rows, not the training rows of the folder
    summary["activity"] = activity(frame[scored.to_numpy()], policy="proof").receipt()
    if args.method == "pca" and isinstance(det, PCASPE):
        contrib = det.contributions(frame)
        contrib.to_csv(out / "contributions.csv", index_label="timestamp_utc")
        picked = contrib[(flags & scored).to_numpy()].dropna(how="all")
        top = picked.mean().sort_values(ascending=False) if len(picked) else pd.Series(dtype=float)
        summary["spe_threshold"] = det.threshold_
        summary["top_contributors"] = {k: round(float(v), 4) for k, v in top.head(5).items() if pd.notna(v)}
        summary["contribution_population"] = {"basis": "flagged scored rows", "rows": int(len(picked)),
                                              **_span(picked)}
        try:
            plot_contributions(contrib, flags & scored, out / "contributions.png")
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


def _cmd_confidence(args: argparse.Namespace) -> int:
    from open_fdd.ml.confidence import run_cli

    return run_cli(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    handlers = {"download": _cmd_download, "export": _cmd_export, "benchmark": _cmd_benchmark, "detect": _cmd_detect,
                "methods": _cmd_methods, "make-folder": _cmd_make_folder,
                "confidence": _cmd_confidence}
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
