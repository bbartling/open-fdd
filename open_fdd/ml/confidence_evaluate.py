"""Evaluate the fault-confidence screen against ground truth, including a synthetic benchmark.

The raw rule treats every flagged episode as a predicted real fault. The screen keeps only the episodes it labels
``likely_real`` (or those whose ``p_real`` clears a recall-targeted threshold). Comparing the two shows whether
screening removes false positives without dropping real faults.

Ground-truth labels are ``fault`` / ``false_positive`` / ``tuning`` (see ``CLASS_MAP``). The built-in generator plants
all three across several equipment, plus a tight-threshold rule that fires on healthy operation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from open_fdd.ml.confidence import (
    LABELS,
    ConfidenceConfig,
    _require_pandas,
    screen,
    to_utc,
)
from open_fdd.ml.confidence_calibrate import (
    MIN_LABELS,
    MIN_PER_CLASS,
    _metrics,
    calibrate,
)

TRUE_CLASSES = ("real", "false_positive", "tuning")
PRED_LABELS = ("likely_real", "likely_false_positive", "tuning_suggested", "uncertain")
CLASS_MAP = {
    "fault": "real", "real": "real", "true_fault": "real", "confirmed": "real",
    "false_positive": "false_positive", "normal": "false_positive", "stale": "false_positive",
    "off": "false_positive", "healthy": "false_positive",
    "tuning": "tuning", "review": "tuning",
}
EVAL_VERSION = 1


@dataclass
class Benchmark:
    """Synthetic flags, SI history and episode-level ground truth."""

    flags: pd.DataFrame
    history: pd.DataFrame
    labels: pd.DataFrame
    cases: pd.DataFrame
    meta: dict[str, Any] = field(default_factory=dict)


def make_benchmark(
    *,
    units_per_case: int = 5,
    days: int = 8,
    freq: str = "15min",
    seed: int = 7,
    site_id: str = "bench",
) -> Benchmark:
    """Build a multi-equipment flag + history set with planted ground truth.

    Four equipment groups, each with ``units_per_case`` units:

    * ``real`` — a long supply-temperature excursion while the fan is on; a second rule co-faults.
    * ``stale`` — the sensor sticks above the threshold while the fan is on (false positive).
    * ``off`` — the same excursion while the fan is off (false positive).
    * ``clean`` — no planted SAT fault, only the tight-threshold rule (tuning).

    Every unit also carries ``R-TIGHT``, a threshold inside normal noise, labeled ``tuning``.
    """
    _require_pandas()
    if units_per_case < 1:
        raise ValueError("units_per_case must be at least 1")
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-03-01", periods=int(pd.Timedelta(days=days) / pd.Timedelta(freq)), freq=freq, tz="UTC")
    n = ts.size
    # windows sit in the middle of the record so each episode has baseline history on both sides
    real_sl = slice(int(n * 0.30), int(n * 0.30) + 40)   # 10 h at 15 min
    stale_sl = slice(int(n * 0.50), int(n * 0.50) + 24)  # 6 h stuck
    off_sl = slice(int(n * 0.65), int(n * 0.65) + 24)    # 6 h off
    groups = (("real", real_sl), ("stale", stale_sl), ("off", off_sl), ("clean", None))
    flags, hist, labels, cases = [], [], [], []
    for case, sl in groups:
        for k in range(1, units_per_case + 1):
            eq = f"AHU-{case[:3].upper()}{k:02d}"
            cases.append({"equipment_id": eq, "case": case, "site_id": site_id})
            sat = 13.0 + rng.normal(0, 0.35, n)
            running = np.ones(n, dtype=int)
            if case == "real" and sl is not None:
                sat[sl] += 6.0
            elif case == "stale" and sl is not None:
                sat[sl] = 18.0
            elif case == "off" and sl is not None:
                sat[sl] += 6.0
                running[sl] = 0
            coil = np.zeros(n, dtype=int)
            if case == "real" and sl is not None:
                coil[sl] = 1
            for i, t in enumerate(ts):
                hist.append((t, eq, "supply_air_temp", float(sat[i]), "numeric"))
                hist.append((t, eq, "fan_status", float(running[i]), "bool"))
                flags.append((t, eq, "R-SAT-HIGH", int(sat[i] > 15.0), float(sat[i]), 15.0, int(running[i])))
                flags.append((t, eq, "R-TIGHT", int(sat[i] > 13.2), float(sat[i]), 13.2, int(running[i])))
                flags.append((t, eq, "R-COIL", int(coil[i]), float("nan"), float("nan"), int(running[i])))
            if case == "real" and sl is not None:
                labels.append((eq, ts[sl.start], ts[sl.stop - 1], "R-SAT-HIGH", "fault", case))
                labels.append((eq, ts[sl.start], ts[sl.stop - 1], "R-COIL", "fault", case))
            elif case in {"stale", "off"} and sl is not None:
                labels.append((eq, ts[sl.start], ts[sl.stop - 1], "R-SAT-HIGH", "false_positive", case))
            # the tight rule is a threshold problem on every unit, including those with a planted SAT event
            labels.append((eq, ts[0], ts[-1], "R-TIGHT", "tuning", "tuning"))
    fl = pd.DataFrame(flags, columns=["timestamp", "equipment_id", "rule_id", "flag", "value", "threshold", "running"])
    hs = pd.DataFrame(hist, columns=["timestamp", "equipment_id", "point_id", "value", "kind"])
    lab = pd.DataFrame(labels, columns=["equipment_id", "start_ts", "end_ts", "rule_id", "label", "case"])
    lab["site_id"] = site_id
    eq = pd.DataFrame(cases)
    meta = {
        "generator": "open_fdd.ml.confidence_evaluate.make_benchmark",
        "seed": seed, "days": days, "freq": freq, "units_per_case": units_per_case,
        "site_id": site_id, "n_equipment": len(eq), "n_flag_rows": len(fl),
        "cases": {c: units_per_case for c, _ in groups},
        "rules": {"R-SAT-HIGH": 15.0, "R-TIGHT": 13.2, "R-COIL": "co-faults with the planted real SAT event"},
    }
    return Benchmark(flags=fl, history=hs, labels=lab, cases=eq, meta=meta)


def write_benchmark(bench: Benchmark, out: Path) -> None:
    """Write ``flags.csv``, ``history.csv``, ``labels.csv``, ``cases.csv`` and ``meta.json`` into ``out``."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bench.flags.to_csv(out / "flags.csv", index=False)
    bench.history.to_csv(out / "history.csv", index=False)
    bench.labels.to_csv(out / "labels.csv", index=False)
    bench.cases.to_csv(out / "cases.csv", index=False)
    (out / "meta.json").write_text(json.dumps(bench.meta, indent=1, default=str), encoding="utf-8")


def class_labels(episodes: pd.DataFrame, labels: pd.DataFrame) -> pd.Series:
    """Map each episode to ``real``, ``false_positive``, ``tuning`` or NaN (unlabeled).

    Overlap and precedence match :func:`open_fdd.ml.confidence_calibrate.label_episodes`: a rule-specific label
    wins over a rule-agnostic one; when several labels of the same specificity overlap, ``real`` beats
    ``false_positive``, which beats ``tuning``.
    """
    missing = {"equipment_id", "start_ts", "end_ts", "label"} - set(labels.columns)
    if missing:
        raise ValueError(f"labels is missing columns: {sorted(missing)}")
    lab = labels.copy()
    lab["cls"] = lab["label"].astype(str).str.strip().str.lower().map(CLASS_MAP)
    lab = lab.dropna(subset=["cls"])
    lab["start_ts"], lab["end_ts"] = to_utc(lab["start_ts"]).set_axis(lab.index), to_utc(lab["end_ts"]).set_axis(lab.index)
    lab["equipment_id"] = lab["equipment_id"].astype(str)
    if "rule_id" not in lab.columns:
        lab["rule_id"] = None
    rank = {"real": 2, "false_positive": 1, "tuning": 0}
    by_eq = {k: g for k, g in lab.groupby("equipment_id")}
    out: list[Any] = [np.nan] * len(episodes)
    for i, r in enumerate(episodes.itertuples(index=False)):
        g = by_eq.get(str(r.equipment_id))
        if g is None:
            continue
        hit = g[(g["start_ts"] <= r.end) & (g["end_ts"] >= r.start)]
        if hit.empty:
            continue
        specific = hit[hit["rule_id"].astype(str) == str(r.rule_id)]
        use = specific if not specific.empty else hit[hit["rule_id"].isna() | (hit["rule_id"].astype(str) == "")]
        if not use.empty:
            out[i] = use.loc[use["cls"].map(rank).idxmax(), "cls"]
    return pd.Series(out, index=episodes.index, name="truth")


def _pr(y: np.ndarray, pred: np.ndarray) -> dict[str, float | int]:
    tp = int(((y == 1) & pred).sum())
    fp = int(((y == 0) & pred).sum())
    fn = int(((y == 1) & ~pred).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "true_positives": tp, "false_positives": fp, "false_negatives": fn, "support_real": int((y == 1).sum()),
            "support_not_real": int((y == 0).sum())}


def _fp_reduction(y: np.ndarray, scores: np.ndarray, targets: tuple[float, ...] = (0.8, 0.9, 1.0)) -> list[dict[str, Any]]:
    """For each target real-fault recall, the tightest ``p_real`` cut and how many non-real flags it drops vs the raw rule."""
    raw_fp = int((y == 0).sum())
    n_real = int((y == 1).sum())
    out = []
    if n_real == 0:
        return out
    order = np.argsort(-scores)
    y_s, s_s = y[order], scores[order]
    tp = np.cumsum(y_s == 1)
    recall = tp / n_real
    fp = np.cumsum(y_s == 0)
    for t in targets:
        hit = np.where(recall >= t)[0]
        if hit.size == 0:
            out.append({"target_recall": t, "achieved": False})
            continue
        i = int(hit[0])
        fp_after = int(fp[i])
        red = (1.0 - fp_after / raw_fp) if raw_fp else 0.0
        pred = scores >= s_s[i]
        out.append({
            "target_recall": t, "achieved": True, "recall": round(float(recall[i]), 4),
            "threshold_p_real": round(float(s_s[i]), 4), "precision": round(_pr(y, pred)["precision"], 4),
            "false_positives": fp_after, "false_positives_raw": raw_fp,
            "false_positive_reduction": round(red, 4),
        })
    return out


def evaluate(scored: pd.DataFrame, labels: pd.DataFrame, *, target_recall: float = 0.9,
             config: ConfidenceConfig | None = None) -> dict[str, Any]:
    """Compare raw rule flags with the screen on labeled episodes. Does not change any rule or stored result."""
    ep = scored.copy()
    ep["truth"] = class_labels(ep, labels)
    known = ep["truth"].notna()
    report: dict[str, Any] = {
        "evaluation_version": EVAL_VERSION,
        "advisory": "The screen is advisory; nothing was tuned or written back. Metrics are only as good as the labels.",
        "episodes": len(ep),
        "labeled_episodes": int(known.sum()),
        "unlabeled_episodes": int((~known).sum()),
        "truth": {c: int((ep.loc[known, "truth"] == c).sum()) for c in TRUE_CLASSES},
    }
    if not known.any():
        report["status"] = "no labeled episodes overlapped the screen's output"
        return report
    y = (ep.loc[known, "truth"] == "real").to_numpy()
    scores = pd.to_numeric(ep.loc[known, "p_real"], errors="coerce").fillna(0.0).to_numpy(float)
    pred_screen = (ep.loc[known, "label"] == "likely_real").to_numpy()
    pred_raw = np.ones(int(known.sum()), dtype=bool)  # every flagged episode is a raw-rule positive
    report["rule"] = _pr(y, pred_raw)
    report["screen"] = _pr(y, pred_screen)
    targets = tuple(sorted({0.8, 0.9, 1.0, float(target_recall)}))
    report["false_positive_reduction"] = _fp_reduction(y, scores, targets)
    # same curve but only on real vs planted false positives, so a noisy tight rule does not dominate
    op = ep.loc[known, "truth"].isin(["real", "false_positive"]).to_numpy()
    if op.any() and int((ep.loc[known, "truth"] == "real").sum()) and int((ep.loc[known, "truth"] == "false_positive").sum()):
        y_op = (ep.loc[known, "truth"][op] == "real").to_numpy()
        report["false_positive_reduction_operational"] = _fp_reduction(y_op, scores[op], targets)
    truth = ep.loc[known, "truth"].to_numpy()
    pred = ep.loc[known, "label"].to_numpy()
    matrix = [[int(((truth == t) & (pred == p)).sum()) for p in PRED_LABELS] for t in TRUE_CLASSES]
    report["confusion"] = {"rows": list(TRUE_CLASSES), "columns": list(PRED_LABELS), "counts": matrix}
    if y.sum() and (1 - y).sum():
        report["calibration"] = {"heuristic": _metrics(y.astype(float), scores)}
        n1, n0 = int(y.sum()), int((~y).sum())
        if known.sum() >= MIN_LABELS and min(n0, n1) >= MIN_PER_CLASS:
            cal_ep, info = calibrate(ep, labels)
            report["calibration"]["status"] = info.get("status")
            if "held_out" in info:
                report["calibration"]["held_out"] = info["held_out"]
            else:
                report["calibration"]["note"] = info.get("status")
            if "p_real_calibrated" in cal_ep.columns and cal_ep.loc[known, "p_real_calibrated"].notna().any():
                pcal = pd.to_numeric(cal_ep.loc[known, "p_real_calibrated"], errors="coerce").to_numpy(float)
                pcal = np.where(np.isfinite(pcal), pcal, scores)
                report["calibration"]["calibrated"] = _metrics(y.astype(float), pcal)
        else:
            report["calibration"]["status"] = (
                f"logistic calibration not fitted: need at least {MIN_LABELS} labeled episodes "
                f"and {MIN_PER_CLASS} real and {MIN_PER_CLASS} not-real"
            )
    by_truth: dict[str, Any] = {}
    for c in TRUE_CLASSES:
        sub = ep.loc[known & (ep["truth"] == c), "label"]
        by_truth[c] = {lab: int((sub == lab).sum()) for lab in LABELS}
    report["labels_by_truth"] = by_truth
    if config is not None:
        report["uncertain_below"] = config.uncertain_below
    report["status"] = "ok"
    return report


def evaluate_benchmark(config: ConfidenceConfig | None = None, target_recall: float = 0.9, **kw: Any) -> tuple[Benchmark, dict[str, pd.DataFrame], dict[str, Any]]:
    """Generate the synthetic set, screen it and evaluate. Convenience for the CLI and tests."""
    cfg = config or ConfidenceConfig()
    bench = make_benchmark(**kw)
    # The tight-threshold rule produces many long merged episodes; keep enough history budget
    # that the planted stale/off/real windows still get a history read.
    if cfg.max_history_episodes < 10_000:
        cfg = replace(cfg, max_history_episodes=10_000)
    result = screen(bench.flags, bench.history, cfg)
    report = evaluate(result["episodes"], bench.labels, target_recall=target_recall, config=cfg)
    report["source"] = {"input": "synthetic", **bench.meta}
    return bench, result, report


def to_markdown(report: dict[str, Any]) -> str:
    """A short Markdown summary of an evaluation report."""
    lines = ["# Rule vs screen evaluation", ""]
    if report.get("advisory"):
        lines += [f"*{report['advisory']}*", ""]
    lines.append(f"Labeled episodes: {report.get('labeled_episodes', 0)} of {report.get('episodes', 0)} "
                 f"(unlabeled {report.get('unlabeled_episodes', 0)}).")
    truth = report.get("truth") or {}
    if truth:
        bits = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in truth.items())
        lines.append(f"Ground truth: {bits}.")
    lines += ["", "## Precision and recall for real faults", ""]
    if "rule" in report and "screen" in report:
        lines += [
            "| Method | Precision | Recall | F1 | False positives | False negatives |",
            "|---| ---:| ---:| ---:| ---:| ---:|",
        ]
        for name, key in (("Raw rule (every flag is a predicted fault)", "rule"),
                          ("After screening (`likely_real` only)", "screen")):
            m = report[key]
            lines.append(f"| {name} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
                         f"{m['false_positives']} | {m['false_negatives']} |")
    rows = report.get("false_positive_reduction") or []
    if rows:
        lines += ["", "## False-positive reduction at fixed real-fault recall", "",
                  "| Target recall | Achieved | Threshold `p_real` | Precision | FP after | FP raw | FP reduction |",
                  "| ---:|---| ---:| ---:| ---:| ---:| ---:|"]
        for r in rows:
            if not r.get("achieved"):
                lines.append(f"| {r['target_recall']:.2f} | no | — | — | — | — | — |")
                continue
            lines.append(f"| {r['target_recall']:.2f} | {r['recall']:.3f} | {r['threshold_p_real']:.3f} | "
                         f"{r['precision']:.3f} | {r['false_positives']} | {r['false_positives_raw']} | "
                         f"{r['false_positive_reduction']:.1%} |")
        op_rows = report.get("false_positive_reduction_operational") or []
        if op_rows:
            lines += ["", "Restricted to labeled real faults vs labeled false positives (tuning episodes omitted):", ""]
            lines += ["| Target recall | Achieved | Threshold `p_real` | Precision | FP after | FP raw | FP reduction |",
                      "| ---:|---| ---:| ---:| ---:| ---:| ---:|"]
            for r in op_rows:
                if not r.get("achieved"):
                    lines.append(f"| {r['target_recall']:.2f} | no | — | — | — | — | — |")
                    continue
                lines.append(f"| {r['target_recall']:.2f} | {r['recall']:.3f} | {r['threshold_p_real']:.3f} | "
                             f"{r['precision']:.3f} | {r['false_positives']} | {r['false_positives_raw']} | "
                             f"{r['false_positive_reduction']:.1%} |")
    conf = report.get("confusion")
    if conf:
        lines += ["", "## Confusion (truth \\ predicted)", "",
                  "| Truth \\ predicted | " + " | ".join(c.replace("_", " ") for c in conf["columns"]) + " |",
                  "|" + "---|" * (1 + len(conf["columns"]))]
        for name, counts in zip(conf["rows"], conf["counts"], strict=True):
            lines.append("| " + name.replace("_", " ") + " | " + " | ".join(str(c) for c in counts) + " |")
    cal = report.get("calibration")
    if cal and "heuristic" in cal:
        lines += ["", "## Calibration of `p_real` (real vs not-real)", "",
                  "| Model | Brier | ECE | AUC |", "|---| ---:| ---:| ---:|"]
        h = cal["heuristic"]
        lines.append(f"| Heuristic | {h['brier']:.3f} | {h['ece']:.3f} | {h['auc']:.3f} |")
        if "held_out" in cal:
            ho = cal["held_out"]
            for key, title in (("heuristic", "Heuristic (held-out)"), ("calibrated", "Calibrated (held-out)")):
                if key in ho:
                    m = ho[key]
                    lines.append(f"| {title} | {m['brier']:.3f} | {m['ece']:.3f} | {m['auc']:.3f} |")
        elif cal.get("status") and cal["status"] != "fitted":
            lines += ["", cal["status"]]
    lines += ["", "The screen does not change a rule, a threshold or a stored result."]
    return "\n".join(lines) + "\n"


def add_evaluate_arguments(ap: Any) -> None:
    ev = ap.add_argument_group("evaluation")
    ev.add_argument("--evaluate", action="store_true",
                    help="compare raw rule flags with the screen: synthetic benchmark if no input is given, "
                         "otherwise your --flags/--results (or database) plus --labels")
    ev.add_argument("--synthetic", action="store_true", help="run the built-in planted-fault benchmark (with --evaluate)")
    ev.add_argument("--write-benchmark", metavar="DIR", help="write the synthetic flags, history and labels CSVs to DIR")
    ev.add_argument("--target-recall", type=float, default=0.9,
                    help="real-fault recall at which to report false-positive reduction (default 0.9)")
    ev.add_argument("--seed", type=int, default=7, help="generator seed for --synthetic / --write-benchmark")
    ev.add_argument("--units-per-case", type=int, default=5, help="equipment in each planted case group (default 5)")


def run_evaluate(args: Any, cfg: ConfidenceConfig, result: dict[str, pd.DataFrame] | None = None,
                 labels: pd.DataFrame | None = None) -> dict[str, Any]:
    """Build or reuse a screen result and return the evaluation report. Writes CSVs when asked."""
    bench = None
    if args.synthetic or result is None:
        bench, result, report = evaluate_benchmark(
            cfg, target_recall=args.target_recall, seed=args.seed, units_per_case=args.units_per_case,
        )
        if args.write_benchmark:
            write_benchmark(bench, Path(args.write_benchmark))
        return report
    if labels is None:
        raise ValueError("--evaluate on your own rule output needs --labels (or pass --synthetic for the built-in benchmark)")
    report = evaluate(result["episodes"], labels, target_recall=args.target_recall, config=cfg)
    report["source"] = {"input": "user"}
    return report
