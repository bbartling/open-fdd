"""Review one saved SQL fault episode against ML evidence (first slice of #1667).

    python -m open_fdd.ml.review episode.json ./AHU_1 --train ./AHU_1_known_good --out review.json
    python -m open_fdd.ml.review episode.json ./AHU_1 --train-until 2026-06-01 --methods grey_box,pca

The episode is a JSON object with at least ``rule_id``, ``verdict``, ``start_utc`` and ``end_utc`` (plus any identity,
tuner, coverage, proof and revision fields the caller has; they are copied into the review unchanged). The folder is
the SI device folder the other tools read (``history_wide.csv`` + ``column_map.json``).

The review never removes or rewrites the SQL verdict. Its ``outcome`` is one of:

* ``corroborated``: at least one ML method, fitted on an explicit training source that does not overlap the episode,
  assessed enough of the episode's active rows and flagged at least ``corroborate_share`` of them.
* ``needs_review``: the methods assessed the episode and stayed quiet. A quiet or unsupported detector cannot make a
  SQL fault a false positive; that label needs independent healthy or maintenance evidence, so it is never emitted.
* ``insufficient_evidence``: no training source, a training range that overlaps the episode, no data, no run proof or no
  proven running rows in the window, an unassessed SQL episode, or no method able to assess enough of it. ``reasons`` says which.

Tuning replay (SQL and pandas before/after) and RDF-resolved inputs are later slices of #1667.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

LEARNING_METHODS = ("grey_box", "pca", "ocsvm", "copod")
DEFAULT_METHODS = ("grey_box", "pca", "ocsvm")
OUTCOMES = ("corroborated", "needs_review", "insufficient_evidence")
REQUIRED_EPISODE_KEYS = ("rule_id", "verdict", "start_utc", "end_utc")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _folder_fingerprint(folder: Path) -> dict[str, str | None]:
    return {name: _sha256(folder / name) for name in ("history_wide.csv", "column_map.json")}


def _utc(value: Any, what: str):
    import pandas as pd

    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} {value!r} is not a date/time") from exc
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def load_episode(path: str | Path) -> dict:
    episode = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(episode, dict):
        raise ValueError(f"{path}: an episode must be a JSON object")
    missing = [k for k in REQUIRED_EPISODE_KEYS if episode.get(k) in (None, "")]
    if missing:
        raise ValueError(f"{path}: episode lacks {', '.join(missing)}")
    return episode


def _assessed(det, frame, active):
    """Rows the fitted detector actually judged (not just 'not flagged')."""
    import pandas as pd

    from open_fdd.ml.detectors import _features, canonical_roles, operating_mode

    if hasattr(det, "assessed_mask"):  # mode-gated models expose this once #1677 lands
        return det.assessed_mask(frame).reindex(frame.index).fillna(False).astype(bool) & active
    if getattr(det, "name", "") in ("pca", "grey_box"):
        return det.scores(frame).notna() & active
    roles = list(getattr(det, "roles", []) or [])
    models = getattr(det, "models_", None)
    if roles and models is not None:
        f = canonical_roles(frame)
        ok = _features(f, roles).notna().all(axis=1)
        return ok & operating_mode(f).isin(list(models)) & active
    return pd.Series(False, index=frame.index)


def _proof_active(frame):
    """``(active, source)``: rows proven running under the run-proof contract, ``(None, "")`` with no proof.

    The proof is :func:`open_fdd.run_proof.derive_run_proof` (a resolved ``run-proof`` column first, then the own
    status roles, then the own command roles, honouring ``attrs["run_proof_resolved"]``), running when above the
    contract threshold (:func:`open_fdd.run_proof.proof_on`). A missing proof sample is not running. When an
    ``occupied`` role has data, unoccupied rows are not active either.
    """
    import pandas as pd

    from open_fdd.run_proof import derive_run_proof, proof_on

    f = frame.rename(columns={"run_proof": "run-proof"}) if "run_proof" in frame.columns and "run-proof" not in frame.columns else frame
    f.attrs = dict(frame.attrs)
    series, source = derive_run_proof(f)
    if series is None:
        return None, ""
    active = proof_on(pd.to_numeric(series, errors="coerce"))
    if "occupied" in f.columns:
        occ = pd.to_numeric(f["occupied"], errors="coerce")
        if occ.notna().any():
            active &= occ.gt(0.5).fillna(False)
    return active.astype(bool), source


def review_episode(episode: dict, frame, *, train=None, training: dict | None = None,
                   methods: tuple[str, ...] = DEFAULT_METHODS, seed: int = 0, min_assessed: float = 0.5,
                   corroborate_share: float = 0.25) -> dict:
    """The review record for ``episode`` on the role ``frame`` (SI, UTC index). Pure: no files."""
    import pandas as pd

    from open_fdd.ml.detectors import canonical_roles, make_detector

    frame = canonical_roles(frame)
    training = dict(training or {"source": "none"})
    start, end = _utc(episode["start_utc"], "start_utc"), _utc(episode["end_utc"], "end_utc")
    if end <= start:
        raise ValueError(f"episode end_utc {end} is not after start_utc {start}")
    window = frame[(frame.index >= start) & (frame.index < end)]
    window.attrs = dict(frame.attrs)
    proof, proof_source = _proof_active(window)
    active = proof if proof is not None else pd.Series(False, index=window.index)
    reasons: list[dict] = []

    def gate(code: str, detail: str) -> None:
        reasons.append({"code": code, "detail": detail})

    if str(episode.get("verdict", "")).lower() not in ("fault", "true", "1", "confirmed"):
        gate("not_a_fault_episode", f"verdict is {episode.get('verdict')!r}; only saved faults are reviewed")
    if episode.get("assessed") is False or episode.get("run_proof") is False:
        gate("sql_episode_unassessed", "the saved SQL result says it was not assessed or lacked run proof")
    elif ("run_proof_source" in episode and episode.get("run_proof_source") in (None, "")) or str(
        episode.get("skip_reason", "")
    ) == "no_run_proof":
        gate("sql_episode_unassessed", "the saved SQL result has no run proof (run_proof_source null or "
             "skip_reason no_run_proof)")
    if train is None or len(train) == 0:
        gate("training_source_missing", "no --train folder or --train-until cutoff: no known-good baseline to compare")
    else:
        train = canonical_roles(train)
        train_proof, train_source = _proof_active(train)
        if train_proof is None:
            gate("training_no_run_proof", "the training rows have no run proof (run-proof, status or command role); "
                 "a baseline must be learned on proven running rows only")
        else:
            training.update(proof_source=train_source, proven_rows=int(train_proof.sum()))
            train = train[train_proof.to_numpy()]
        t0, t1 = train.index.min(), train.index.max()
        training.update(start_utc=str(t0), end_utc=str(t1), rows=int(len(train)))
        if t1 >= start and t0 < end:
            gate("training_overlaps_episode",
                 f"training rows {t0}..{t1} overlap the episode {start}..{end}; the fault could be in the baseline")
    if window.empty:
        gate("no_data_in_window", f"the folder has no rows between {start} and {end}")
    elif proof is None:
        gate("no_run_proof", "the window has no run proof (no run-proof, status or command role with data); ML "
             "scores proven running rows only, so it cannot judge rows SQL never judged")
    elif not active.any():
        gate("no_active_rows", "the run proof never says running in the window; ML scores proven running rows only")

    method_records: dict[str, dict] = {}
    if not reasons:
        n_active = int(active.sum())
        for m in methods:
            rec: dict[str, Any] = {"method": m}
            if m not in LEARNING_METHODS:
                rec.update(status="not_used", reason="only baseline-learning methods are used in a review")
                method_records[m] = rec
                continue
            try:
                det = make_detector(m, seed=seed)
                det.fit(train)
            except (ValueError, ImportError) as exc:
                rec.update(status="unsupported", reason=str(exc))
                method_records[m] = rec
                continue
            assessed = _assessed(det, window, active)
            flags = det.flags(window).reindex(window.index).fillna(False).astype(bool) & assessed
            n_assessed, n_flag = int(assessed.sum()), int(flags.sum())
            coverage = n_assessed / n_active if n_active else 0.0
            share = n_flag / n_assessed if n_assessed else None
            rec.update(roles=list(getattr(det, "roles", []) or getattr(det, "thresholds_", {}).keys()),
                       active_rows=n_active, assessed_rows=n_assessed, flagged_rows=n_flag,
                       assessed_coverage=round(coverage, 4), flagged_share=None if share is None else round(share, 4))
            if coverage < min_assessed:
                rec.update(status="unassessed",
                           reason=f"assessed {n_assessed} of {n_active} active rows (< {min_assessed:.0%}): missing "
                                  "inputs or an operating mode the baseline never saw")
            elif share is not None and share >= corroborate_share:
                rec["status"] = "corroborates"
            else:
                rec["status"] = "quiet"
            if m == "pca" and rec["status"] == "corroborates" and hasattr(det, "contributions"):
                contrib = det.contributions(window)[flags].mean().sort_values(ascending=False).head(3)
                rec["top_contributors"] = {k: round(float(v), 4) for k, v in contrib.items() if v == v}
            if m == "grey_box" and n_flag and hasattr(det, "residuals"):
                ratio = det.residuals(window)[flags].abs().median()
                rec["residuals_median_abs"] = {k: round(float(v), 4) for k, v in ratio.items() if v == v}
            method_records[m] = rec
        statuses = [r["status"] for r in method_records.values()]
        if "corroborates" in statuses:
            outcome = "corroborated"
        elif "quiet" in statuses:
            outcome = "needs_review"
            gate("ml_quiet", "the assessing methods did not flag the episode; this is not evidence of a false "
                             "positive (needs independent healthy or maintenance evidence)")
        else:
            outcome = "insufficient_evidence"
            gate("no_method_assessed", "no method could assess enough of the episode: "
                 + "; ".join(f"{k}: {v.get('reason', v['status'])}" for k, v in method_records.items()))
    else:
        outcome = "insufficient_evidence"

    import open_fdd

    return {
        "review_version": 1,
        "outcome": outcome,
        "sql_verdict": episode.get("verdict"),
        "sql_verdict_kept": True,
        "report_inclusion": "keep",
        "reasons": reasons,
        "episode": episode,
        "window": {"start_utc": str(start), "end_utc": str(end), "rows": int(len(window)),
                   "active_rows": int(active.sum()) if len(window) else 0, "proof_source": proof_source or None},
        "training": training,
        "methods": method_records,
        "policy": {"min_assessed": min_assessed, "corroborate_share": corroborate_share, "seed": seed,
                   "false_positive_label": "never emitted here; needs independent healthy or maintenance evidence"},
        "open_fdd_version": getattr(open_fdd, "__version__", None),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m open_fdd.ml.review",
                                description=__doc__.split("\n\n")[0] + " Writes a JSON review; never changes the "
                                "SQL verdict.")
    p.add_argument("episode", type=Path, help="saved SQL fault episode (JSON: rule_id, verdict, start_utc, end_utc, ...)")
    p.add_argument("folder", type=Path, help="device folder (history_wide.csv + column_map.json), SI")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--train", type=Path, help="device folder of operator-asserted known-good history")
    src.add_argument("--train-until", help="known-good rows of FOLDER before this UTC date/time")
    p.add_argument("--methods", default=",".join(DEFAULT_METHODS),
                   help=f"comma list from {', '.join(LEARNING_METHODS)} (default {','.join(DEFAULT_METHODS)})")
    p.add_argument("--seed", type=int, default=0, help="seed for the ocsvm / copod training subsample (default 0)")
    p.add_argument("--min-assessed", type=float, default=0.5,
                   help="share of the episode's active rows a method must assess to count (default 0.5)")
    p.add_argument("--corroborate-share", type=float, default=0.25,
                   help="share of assessed rows a method must flag to corroborate (default 0.25)")
    p.add_argument("--out", type=Path, help="write the review JSON here (default: stdout only)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from open_fdd.ml.cli import role_frame_from_folder

        episode = load_episode(args.episode)
        frame = role_frame_from_folder(args.folder)
        train, training = None, {"source": "none"}
        if args.train is not None:
            if args.train.resolve() == args.folder.resolve():
                raise ValueError("--train is the folder being reviewed; use --train-until")
            train = role_frame_from_folder(args.train)
            training = {"source": "folder", "folder": str(args.train), "fingerprint": _folder_fingerprint(args.train)}
        elif args.train_until:
            cut = _utc(args.train_until, "--train-until")
            train = frame[frame.index < cut]
            training = {"source": "cutoff", "cutoff_utc": str(cut)}
        if train is not None:
            training["assertion"] = "operator-asserted known-good (not an independently verified maintenance label)"
        methods = tuple(m.strip().lower().replace("-", "_") for m in args.methods.split(",") if m.strip())
        review = review_episode(episode, frame, train=train, training=training, methods=methods, seed=args.seed,
                                min_assessed=args.min_assessed, corroborate_share=args.corroborate_share)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    review["inputs"] = {"episode_sha256": _sha256(args.episode), "folder": _folder_fingerprint(args.folder)}
    text = json.dumps(review, indent=1, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
