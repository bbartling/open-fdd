"""Labeled held-out evaluation of the SQL + ML episode review policy (#1667, acceptance 5).

    python -m open_fdd.ml.review_eval labeled.json --out eval.json

``labeled.json`` is an object ``{"test_device_weeks": <total or {equipment: weeks}>, "episodes": [...]}`` (a bare
list or JSON Lines file of episodes also works; alert burden is then not reported). ``test_device_weeks`` is the
explicit exposure of the **test period**: every test equipment and the weeks it was monitored, including units that
raised no alert. One denominator, its total, is used for the overall block and every category block. The older,
ambiguous ``device_weeks`` key is not used for burden (it is reported as a note). Each episode has:

* ``equipment``, ``category`` (fault category such as ``sensor``, ``proof``, ``coil``) and ``split``
  (``train``, ``selection`` or ``test``; only ``test`` is scored).
* ``label``: ``fault``, ``healthy`` or ``unknown``, from independent evidence (maintenance record, functional test,
  engineer review). ``label_source`` says which. ``unknown`` episodes count toward burden and workload, never
  toward precision or recall.
* ``sql_verdict``: the saved SQL result (``fault`` when SQL raised it). A labeled fault SQL never raised is a
  missed genuine fault and counts against recall.
* ``review``: the record ``python -m open_fdd.ml.review`` wrote (or ``review_outcome`` alone).
* optional ``label_onset_utc`` and ``sql_start_utc`` for detection delay.

The review never removes a SQL alert, so the report compares *tiers*, not suppression:

* ``raw_sql``: every SQL fault.
* ``reviewed_priority``: SQL faults the review corroborated; the rest stay in the report for a person
  (``reviewer_workload``) and ``insufficient_evidence`` is reported as excluded coverage.
* ``method:<name>``: SQL faults a single method corroborated, from the review's method records.

Precision and recall carry Wilson 95 % intervals and every count is published, so a small corpus is visible as
such. ``claim_supported`` stays false unless the test split has enough labeled faults and healthy episodes and the
holdout checks pass; no alert-reduction number should be quoted otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

EVAL_VERSION = 1
LABELS = ("fault", "healthy", "unknown")
SPLITS = ("train", "selection", "test")
FAULT_VERDICTS = ("fault", "true", "1", "confirmed")


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Wilson score interval for k successes in n trials (None when n == 0)."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _ts(value: Any):
    import pandas as pd

    if value in (None, ""):
        return None
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def load_corpus(path: str | Path) -> dict:
    """Read a labeled corpus (object, list or JSON Lines) and validate each episode."""
    text = Path(path).read_text(encoding="utf-8").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    corpus = data if isinstance(data, dict) else {"episodes": data}
    if not isinstance(corpus.get("episodes"), list):
        raise ValueError(f"{path}: expected an 'episodes' list")
    for i, ep in enumerate(corpus["episodes"]):
        _validate(ep, i)
    return corpus


def _validate(ep: dict, i: int) -> None:
    if not isinstance(ep, dict):
        raise ValueError(f"episode {i}: must be a JSON object")
    for key in ("equipment", "category", "split", "label"):
        if ep.get(key) in (None, ""):
            raise ValueError(f"episode {i}: lacks {key}")
    if ep["label"] not in LABELS:
        raise ValueError(f"episode {i}: label {ep['label']!r} is not one of {', '.join(LABELS)}")
    if ep["split"] not in SPLITS:
        raise ValueError(f"episode {i}: split {ep['split']!r} is not one of {', '.join(SPLITS)}")


def _sql_alert(ep: dict) -> bool:
    return str(ep.get("sql_verdict", "")).lower() in FAULT_VERDICTS


def _outcome(ep: dict) -> str | None:
    review = ep.get("review") or {}
    return review.get("outcome") or ep.get("review_outcome")


def _method_status(ep: dict, method: str) -> str | None:
    rec = ((ep.get("review") or {}).get("methods") or {}).get(method) or {}
    return rec.get("status")


def _tier_alert(ep: dict, tier: str) -> bool:
    if not _sql_alert(ep):
        return False
    if tier == "raw_sql":
        return True
    if tier == "reviewed_priority":
        return _outcome(ep) == "corroborated"
    return _method_status(ep, tier.split(":", 1)[1]) == "corroborates"


def _score(eps: list[dict], tier: str, device_weeks: float | None) -> dict:
    alerts = [e for e in eps if _tier_alert(e, tier)]
    tp = sum(1 for e in alerts if e["label"] == "fault")
    fp = sum(1 for e in alerts if e["label"] == "healthy")
    faults = [e for e in eps if e["label"] == "fault"]
    fn = len(faults) - tp
    delays = []
    for e in alerts:
        onset, raised = _ts(e.get("label_onset_utc")), _ts(e.get("sql_start_utc"))
        if e["label"] == "fault" and onset is not None and raised is not None:
            delays.append((raised - onset).total_seconds() / 3600.0)
    return {
        "alerts": len(alerts),
        "alerts_per_device_week": round(len(alerts) / device_weeks, 4) if device_weeks else None,
        "true_alerts": tp, "false_alerts": fp, "unlabeled_alerts": len(alerts) - tp - fp,
        "labeled_faults": len(faults), "missed_faults": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None, "precision_ci95": wilson(tp, tp + fp),
        "recall": round(tp / len(faults), 4) if faults else None, "recall_ci95": wilson(tp, len(faults)),
        "median_delay_h": round(statistics.median(delays), 3) if delays else None, "delay_samples": len(delays),
        "missed": sorted(str(e.get("episode_id", e["equipment"])) for e in faults if not _tier_alert(e, tier)),
    }


def _holdout_checks(episodes: list[dict]) -> dict:
    test = [e for e in episodes if e["split"] == "test"]
    fit = [e for e in episodes if e["split"] != "test"]
    out: dict[str, Any] = {"chronological": None, "equipment_holdout": None, "notes": []}
    if not fit:
        out["notes"].append("no train/selection episodes listed; the holdout cannot be checked here")
        return out
    keys = ("start_utc", "end_utc", "sql_start_utc", "label_onset_utc")

    def times(e: dict) -> list:
        return [t for t in (_ts(e.get(k)) for k in keys) if t is not None]

    fit_ends = [max(ts) for ts in map(times, fit) if ts]  # latest time any fit episode touches
    test_starts = [min(ts) for ts in map(times, test) if ts]  # earliest time any test episode touches
    if fit_ends and test_starts:
        out["chronological"] = max(fit_ends) < min(test_starts)
        if not out["chronological"]:
            out["notes"].append(f"test starts {min(test_starts)} before train/selection ends {max(fit_ends)}")
    else:
        out["notes"].append("episode times missing; chronological holdout not checked")
    shared = sorted({e["equipment"] for e in test} & {e["equipment"] for e in fit})
    out["equipment_holdout"] = not shared
    out["shared_equipment"] = shared
    return out


def _test_device_weeks(corpus: dict) -> tuple[float | None, list[str]]:
    """``(total, notes)``: the explicit test-period exposure; ``None`` when it is not given.

    A dict ``{equipment: weeks}`` is summed over every listed equipment, not only the ones with episodes, so a unit
    that raised nothing still counts in the denominator.
    """
    dw = corpus.get("test_device_weeks")
    notes: list[str] = []
    if isinstance(dw, bool):
        dw = None
    if isinstance(dw, (int, float)):
        return (float(dw) or None), notes
    if isinstance(dw, dict):
        total = sum(float(v or 0) for v in dw.values())
        return (total or None), notes
    if "device_weeks" in corpus:
        notes.append("device_weeks is ignored: give test_device_weeks (the test-period exposure of every test "
                     "equipment) to report alerts per device-week")
    else:
        notes.append("no test_device_weeks: alerts per device-week not reported")
    return None, notes


def evaluate(corpus: dict, *, methods: Iterable[str] | None = None, min_labeled: int = 20) -> dict:
    """Score the review tiers on the corpus's test split. Pure: no files."""
    episodes = corpus["episodes"]
    for i, ep in enumerate(episodes):
        _validate(ep, i)
    test = [e for e in episodes if e["split"] == "test"]
    if not test:
        raise ValueError("no episodes with split 'test'; the evaluation scores held-out episodes only")
    if methods is None:
        methods = sorted({m for e in test for m in ((e.get("review") or {}).get("methods") or {})})
    tiers = ["raw_sql", "reviewed_priority"] + [f"method:{m}" for m in methods]
    categories = sorted({e["category"] for e in test})

    dw, exposure_notes = _test_device_weeks(corpus)
    tested = {e["equipment"] for e in test}
    listed = corpus.get("test_device_weeks")
    if isinstance(listed, dict):
        unlisted = sorted(tested - set(listed))
        if unlisted:
            exposure_notes.append(f"test equipment without exposure in test_device_weeks: {', '.join(unlisted)}")

    def block(eps: list[dict]) -> dict:
        sql = [e for e in eps if _sql_alert(e)]
        outcomes = {o: sum(1 for e in sql if _outcome(e) == o)
                    for o in ("corroborated", "needs_review", "insufficient_evidence")}
        outcomes["not_reviewed"] = len(sql) - sum(outcomes.values())
        return {
            "episodes": len(eps), "device_weeks": dw,
            "labels": {lab: sum(1 for e in eps if e["label"] == lab) for lab in LABELS},
            "review_outcomes": outcomes,
            "reviewer_workload": outcomes["needs_review"] + outcomes["insufficient_evidence"] + outcomes["not_reviewed"],
            "excluded_coverage": round(outcomes["insufficient_evidence"] / len(sql), 4) if sql else None,
            "tiers": {t: _score(eps, t, dw) for t in tiers},
        }

    overall = block(test)
    holdout = _holdout_checks(episodes)
    labels = overall["labels"]
    reasons = []
    if labels["fault"] < min_labeled or labels["healthy"] < min_labeled:
        reasons.append(f"needs at least {min_labeled} labeled fault and {min_labeled} labeled healthy test episodes "
                       f"(has {labels['fault']} and {labels['healthy']})")
    if holdout["chronological"] is not True:
        reasons.append("chronological holdout not demonstrated")
    import open_fdd

    return {
        "eval_version": EVAL_VERSION,
        "split_counts": {s: sum(1 for e in episodes if e["split"] == s) for s in SPLITS},
        "holdout": holdout,
        "overall": overall,
        "by_category": {c: block([e for e in test if e["category"] == c]) for c in categories},
        "claim_supported": not reasons,
        "claim_reasons": reasons,
        "exposure": {"test_device_weeks": dw, "notes": exposure_notes,
                     "denominator": "one total for the overall and every category block"},
        "claim_notes": ["the equipment holdout is reported (holdout.shared_equipment) but not required for the claim"],
        "policy_note": "the review never removes a SQL alert; reviewed_priority is a triage tier, and an episode "
                       "is only a false alert when its independent label is healthy",
        "open_fdd_version": getattr(open_fdd, "__version__", None),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m open_fdd.ml.review_eval",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("corpus", type=Path, help="labeled episodes (JSON object, list or JSON Lines)")
    p.add_argument("--methods", help="comma list of method tiers to score (default: every method in the reviews)")
    p.add_argument("--min-labeled", type=int, default=20,
                   help="labeled fault and healthy test episodes needed before claim_supported (default 20)")
    p.add_argument("--out", type=Path, help="write the evaluation JSON here (default: stdout only)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        corpus = load_corpus(args.corpus)
        methods = [m.strip() for m in args.methods.split(",") if m.strip()] if args.methods else None
        result = evaluate(corpus, methods=methods, min_labeled=args.min_labeled)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=1, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
