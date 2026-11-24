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


DEFAULT_SEEDS = (7, 11, 19, 23, 31)

# default mix: more operational episodes than the old "tight rule on every 15-min sample" design
def _mix(units_per_case: int) -> dict[str, int]:
    n = max(int(units_per_case), 1)
    out = {
        "real": n,
        "real_gap": max(n - 1, 1),
        "stale": max(n - 1, 1),
        "stale_partial": max(n - 1, 1),
        "off": n,
    }
    # majority healthy, so a well-tuned SAT rule does not look like a fleet-wide (tuning) fire
    out["clean"] = max(sum(out.values()), 2 * n)
    return out


def make_benchmark(
    *,
    units_per_case: int = 5,
    days: int = 8,
    freq: str = "15min",
    seed: int = 7,
    site_id: str = "bench",
    mix: dict[str, int] | None = None,
) -> Benchmark:
    """Build a multi-equipment flag + history set with planted ground truth.

    Equipment groups (counts from ``mix`` or ``units_per_case``):

    * ``real`` — a long supply-temperature excursion while the fan is on; a second rule co-faults.
    * ``real_gap`` — the same real fault, with a brief hole in the SAT history (a few missing samples).
    * ``stale`` — the sensor sticks above the threshold while the fan is on (false positive).
    * ``stale_partial`` — the sensor is stuck for only part of the episode, then moves again (false positive).
    * ``off`` — a noisy SAT excursion while the fan is off (false positive).
    * ``clean`` — no planted SAT fault; may see a brief noise spike.

    Rules are mixed: ``R-SAT-HIGH`` (15 °C) on every unit, ``R-COIL`` on planted real faults,
    ``R-TIGHT`` (chronic, 12.95 °C) on half the fleet, and ``R-MED`` (mildly tight, 14.3 °C) on the other half.
    SAT traces include realistic sensor noise.
    """
    _require_pandas()
    if units_per_case < 1:
        raise ValueError("units_per_case must be at least 1")
    counts = _mix(units_per_case) if mix is None else {k: int(v) for k, v in mix.items() if int(v) > 0}
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-03-01", periods=int(pd.Timedelta(days=days) / pd.Timedelta(freq)), freq=freq, tz="UTC")
    n = ts.size
    # windows sit in the middle of the record so each episode has baseline history on both sides
    real_sl = slice(int(n * 0.30), int(n * 0.30) + 40)    # 10 h
    stale_sl = slice(int(n * 0.50), int(n * 0.50) + 28)   # 7 h
    off_sl = slice(int(n * 0.65), int(n * 0.65) + 24)     # 6 h
    windows = {
        "real": real_sl, "real_gap": real_sl,
        "stale": stale_sl, "stale_partial": stale_sl,
        "off": off_sl, "clean": None,
    }
    flags, hist, labels, cases = [], [], [], []
    skip_sat: set[tuple[str, pd.Timestamp]] = set()
    for case, n_units in counts.items():
        sl = windows.get(case)
        for k in range(1, n_units + 1):
            prefix = {
                "real": "REA", "real_gap": "GAP",
                "stale": "STA", "stale_partial": "PST",
                "off": "OFF", "clean": "CLE",
            }.get(case, case[:3].upper())
            eq = f"AHU-{prefix}{k:02d}"
            cases.append({"equipment_id": eq, "case": case, "site_id": site_id})
            sat = 13.0 + rng.normal(0, 0.5, n)
            # occasional isolated spikes (noise), kept mostly below the well-tuned 15 °C rule
            spike_i = rng.choice(n, size=2, replace=False)
            sat[spike_i] += rng.choice([0.6, 0.8, 1.0], size=2)
            running = np.ones(n, dtype=int)
            coil = np.zeros(n, dtype=int)
            if case in {"real", "real_gap"} and sl is not None:
                sat[sl] = 13.0 + 5.5 + rng.normal(0, 0.25, sl.stop - sl.start)
                coil[sl] = 1
                if case == "real_gap":
                    mid = (sl.start + sl.stop) // 2
                    for t in ts[mid:mid + 3]:
                        skip_sat.add((eq, t))
            elif case == "stale" and sl is not None:
                sat[sl] = 18.0
            elif case == "stale_partial" and sl is not None:
                cut = sl.start + int(0.6 * (sl.stop - sl.start))
                sat[sl.start:cut] = 18.0
                sat[cut:sl.stop] = 16.0 + rng.normal(0, 0.3, sl.stop - cut)
            elif case == "off" and sl is not None:
                sat[sl] = 13.0 + 5.5 + rng.normal(0, 0.3, sl.stop - sl.start)
                running[sl] = 0
            tight = bool(rng.integers(0, 2))  # mixed tightness, reproducible from seed
            for i, t in enumerate(ts):
                if (eq, t) not in skip_sat:
                    hist.append((t, eq, "supply_air_temp", float(sat[i]), "numeric"))
                hist.append((t, eq, "fan_status", float(running[i]), "bool"))
                flags.append((t, eq, "R-SAT-HIGH", int(sat[i] > 15.0), float(sat[i]), 15.0, int(running[i])))
                flags.append((t, eq, "R-COIL", int(coil[i]), float("nan"), float("nan"), int(running[i])))
                if tight:
                    flags.append((t, eq, "R-TIGHT", int(sat[i] > 12.95), float(sat[i]), 12.95, int(running[i])))
                else:
                    flags.append((t, eq, "R-MED", int(sat[i] > 14.3), float(sat[i]), 14.3, int(running[i])))
            if case in {"real", "real_gap"} and sl is not None:
                labels.append((eq, ts[sl.start], ts[sl.stop - 1], "R-SAT-HIGH", "fault", case))
                labels.append((eq, ts[sl.start], ts[sl.stop - 1], "R-COIL", "fault", case))
            elif case in {"stale", "stale_partial", "off"} and sl is not None:
                labels.append((eq, ts[sl.start], ts[sl.stop - 1], "R-SAT-HIGH", "false_positive", case))
            if tight:
                labels.append((eq, ts[0], ts[-1], "R-TIGHT", "tuning", "tuning"))
            else:
                labels.append((eq, ts[0], ts[-1], "R-MED", "tuning", "tuning"))
    fl = pd.DataFrame(flags, columns=["timestamp", "equipment_id", "rule_id", "flag", "value", "threshold", "running"])
    hs = pd.DataFrame(hist, columns=["timestamp", "equipment_id", "point_id", "value", "kind"])
    lab = pd.DataFrame(labels, columns=["equipment_id", "start_ts", "end_ts", "rule_id", "label", "case"])
    lab["site_id"] = site_id
    eq = pd.DataFrame(cases)
    if eq["equipment_id"].duplicated().any():
        raise ValueError("make_benchmark assigned the same equipment_id to more than one case")
    meta = {
        "generator": "open_fdd.ml.confidence_evaluate.make_benchmark",
        "seed": seed, "days": days, "freq": freq, "units_per_case": units_per_case,
        "site_id": site_id, "n_equipment": len(eq), "n_flag_rows": len(fl),
        "cases": dict(counts),
        "rules": {
            "R-SAT-HIGH": 15.0,
            "R-COIL": "co-faults with the planted real SAT event",
            "R-TIGHT": 12.95,
            "R-MED": 14.3,
        },
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
    # operational = labeled real faults vs labeled false positives; tuning is reported separately
    op_mask = ep.loc[known, "truth"].isin(["real", "false_positive"]).to_numpy()
    if op_mask.any() and int((ep.loc[known, "truth"] == "real").sum()) and int((ep.loc[known, "truth"] == "false_positive").sum()):
        y_op, s_op = y[op_mask], scores[op_mask]
        pred_screen_op = pred_screen[op_mask]
        pred_raw_op = pred_raw[op_mask]
        report["operational"] = {
            "rule": _pr(y_op, pred_raw_op),
            "screen": _pr(y_op, pred_screen_op),
            "false_positive_reduction": _fp_reduction(y_op, s_op, targets),
            "truth": {"real": int(y_op.sum()), "false_positive": int((~y_op).sum())},
        }
        report["false_positive_reduction_operational"] = report["operational"]["false_positive_reduction"]
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
    tun = ep.loc[known & (ep["truth"] == "tuning"), "label"]
    if len(tun):
        report["tuning"] = {
            "episodes": len(tun),
            "labels": {lab: int((tun == lab).sum()) for lab in LABELS},
            "share_tuning_suggested": round(float((tun == "tuning_suggested").mean()), 4),
        }
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


def _conf_rate(report: dict[str, Any], truth: str, pred: str) -> float:
    conf = report.get("confusion") or {}
    rows, cols, counts = conf.get("rows") or [], conf.get("columns") or [], conf.get("counts") or []
    if truth not in rows or pred not in cols:
        return float("nan")
    row = counts[rows.index(truth)]
    tot = sum(row)
    return (row[cols.index(pred)] / tot) if tot else float("nan")


def _fpr_at(report: dict[str, Any], target: float = 0.9, *, operational: bool = True) -> float:
    key = "false_positive_reduction_operational" if operational else "false_positive_reduction"
    rows = report.get(key) or (report.get("operational") or {}).get("false_positive_reduction") or []
    for r in rows:
        if r.get("target_recall") == target and r.get("achieved"):
            return float(r["false_positive_reduction"])
    return float("nan")


def _stat(values: list[float]) -> dict[str, Any]:
    arr = np.array(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"mean": None, "std": None, "min": None, "max": None, "values": values}
    std = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    return {"mean": round(float(arr.mean()), 4), "std": round(std, 4),
            "min": round(float(arr.min()), 4), "max": round(float(arr.max()), 4),
            "values": [None if not np.isfinite(v) else round(float(v), 4) for v in values]}


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean and spread of the headline metrics across several evaluation reports (usually several seeds)."""

    def grab(fn):
        return _stat([fn(r) for r in reports])

    def op(r, side, key):
        return (r.get("operational") or {}).get(side, {}).get(key, float("nan"))

    return {
        "n": len(reports),
        "operational_screen_precision": grab(lambda r: op(r, "screen", "precision")),
        "operational_screen_recall": grab(lambda r: op(r, "screen", "recall")),
        "operational_rule_precision": grab(lambda r: op(r, "rule", "precision")),
        "operational_fp_reduction_at_0_9": grab(lambda r: _fpr_at(r, 0.9, operational=True)),
        "real_as_likely_real": grab(lambda r: _conf_rate(r, "real", "likely_real")),
        "false_positive_as_likely_false_positive": grab(lambda r: _conf_rate(r, "false_positive", "likely_false_positive")),
        "tuning_as_tuning_suggested": grab(lambda r: (r.get("tuning") or {}).get("share_tuning_suggested", float("nan"))),
        "heuristic_auc": grab(lambda r: ((r.get("calibration") or {}).get("heuristic") or {}).get("auc", float("nan"))),
        "heuristic_brier": grab(lambda r: ((r.get("calibration") or {}).get("heuristic") or {}).get("brier", float("nan"))),
    }


def evaluate_suite(seeds: tuple[int, ...] | list[int] = DEFAULT_SEEDS, config: ConfidenceConfig | None = None,
                   target_recall: float = 0.9, **kw: Any) -> dict[str, Any]:
    """Run the synthetic benchmark on several seeds and return per-seed reports plus a mean/spread summary."""
    per: list[dict[str, Any]] = []
    first_bench = first_result = None
    for seed in seeds:
        bench, result, report = evaluate_benchmark(config, target_recall=target_recall, seed=int(seed), **kw)
        if first_bench is None:
            first_bench, first_result = bench, result
        per.append({"seed": int(seed), **{k: report[k] for k in (
            "status", "episodes", "labeled_episodes", "truth", "rule", "screen", "operational", "tuning",
            "confusion", "calibration", "labels_by_truth", "false_positive_reduction",
            "false_positive_reduction_operational",
        ) if k in report}})
    out = {
        "evaluation_version": EVAL_VERSION,
        "advisory": "The screen is advisory; nothing was tuned or written back. Metrics are only as good as the labels.",
        "seeds": [int(s) for s in seeds],
        "summary": summarize_reports(per),
        "per_seed": per,
        "status": "ok",
    }
    # keep a representative single-seed view (first seed) so to_markdown and the CLI still work
    if per:
        for k, v in per[0].items():
            if k != "seed":
                out.setdefault(k, v)
        if first_bench is not None:
            out["source"] = {"input": "synthetic", "seeds": [int(s) for s in seeds], **first_bench.meta}
    out["_bench"] = first_bench
    out["_result"] = first_result
    return out


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
    if report.get("summary"):
        su = report["summary"]
        lines += ["", f"## Mean and spread across {su['n']} seeds", "",
                  "| Metric | Mean | Std | Min | Max |",
                  "|---| ---:| ---:| ---:| ---:|"]
        labels = (
            ("operational_screen_precision", "Operational precision (after screen)"),
            ("operational_screen_recall", "Operational recall (after screen)"),
            ("operational_rule_precision", "Operational precision (raw rule)"),
            ("operational_fp_reduction_at_0_9", "Operational FP reduction at 0.90 recall"),
            ("real_as_likely_real", "Real faults labeled likely_real"),
            ("false_positive_as_likely_false_positive", "False positives labeled likely_false_positive"),
            ("tuning_as_tuning_suggested", "Tuning episodes labeled tuning_suggested"),
            ("heuristic_auc", "Heuristic AUC"),
            ("heuristic_brier", "Heuristic Brier"),
        )
        for key, title in labels:
            st = su.get(key) or {}
            if st.get("mean") is None:
                continue
            lines.append(f"| {title} | {st['mean']:.3f} | {st['std']:.3f} | {st['min']:.3f} | {st['max']:.3f} |")
        lines.append("")
        if report.get("seeds"):
            lines.append("Figures below are the first seed. Tuning episodes are excluded from the operational tables.")
    op = report.get("operational")
    lines += ["", "## Precision and recall for real faults (operational: real vs false positive)", ""]
    block = op if op else report
    if "rule" in block and "screen" in block:
        lines += [
            "| Method | Precision | Recall | F1 | False positives | False negatives |",
            "|---| ---:| ---:| ---:| ---:| ---:|",
        ]
        for name, key in (("Raw rule (every flag is a predicted fault)", "rule"),
                          ("After screening (likely_real only)", "screen")):
            m = block[key]
            lines.append(f"| {name} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
                         f"{m['false_positives']} | {m['false_negatives']} |")
    if op and report.get("rule") and report.get("screen"):
        lines += ["", ("Including tuning episodes as not-real (overall): raw rule "
                    f"precision {report['rule']['precision']:.3f}, screen "
                    f"precision {report['screen']['precision']:.3f}, recall "
                    f"{report['screen']['recall']:.3f}.")]
    tun = report.get("tuning")
    if tun:
        lines += ["", f"## Tuning episodes ({tun['episodes']} labeled)", "",
                  ("{:.0%} were labeled `tuning_suggested` ({} of {}).".format(
                      tun["share_tuning_suggested"],
                      tun["labels"].get("tuning_suggested", 0),
                      tun["episodes"]))]
    rows = (report.get("operational") or {}).get("false_positive_reduction") or report.get("false_positive_reduction_operational") or report.get("false_positive_reduction") or []
    if rows:
        lines += ["", "## False-positive reduction at fixed real-fault recall (operational)", "",
                  "| Target recall | Achieved | Threshold `p_real` | Precision | FP after | FP raw | FP reduction |",
                  "| ---:|---| ---:| ---:| ---:| ---:| ---:|"]
        for r in rows:
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


def parse_seeds(args: Any) -> list[int]:
    raw = getattr(args, "seeds", None)
    if raw:
        seeds = [int(x.strip()) for x in str(raw).split(",") if x.strip()]
        if not seeds:
            raise ValueError("--seeds needs at least one integer")
        return seeds
    return list(DEFAULT_SEEDS)


def add_evaluate_arguments(ap: Any) -> None:
    ev = ap.add_argument_group("evaluation")
    ev.add_argument("--evaluate", action="store_true",
                    help="compare raw rule flags with the screen: synthetic benchmark if no input is given, "
                         "otherwise your --flags/--results (or database) plus --labels")
    ev.add_argument("--synthetic", action="store_true", help="run the built-in planted-fault benchmark (with --evaluate)")
    ev.add_argument("--write-benchmark", metavar="DIR", help="write the synthetic flags, history and labels CSVs to DIR")
    ev.add_argument("--target-recall", type=float, default=0.9,
                    help="real-fault recall at which to report false-positive reduction (default 0.9)")
    ev.add_argument("--seed", type=int, default=7, help="generator seed for --write-benchmark or a single --evaluate run")
    ev.add_argument("--seeds", default=None,
                    help="comma list of generator seeds for --evaluate (default 7,11,19,23,31); pass one seed for a faster run")
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
