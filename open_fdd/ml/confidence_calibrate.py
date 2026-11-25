"""Calibrate fault-confidence scores against reviewed episodes.

The heuristic ``p_real`` is a ranking, not a probability. When a site (or a public labeled data set) has reviewer
verdicts, this module compares the heuristic ``p_real`` with three fits on held-out folds, using only numpy:
temperature scaling (one parameter on the heuristic score), isotonic regression (a monotone map of that score), and
a small L2-regularised logistic regression on the episode evidence. None of these change a rule or a stored result.

Labels are rows of ``equipment_id, start_ts, end_ts, label`` with an optional ``rule_id``. ``label`` is ``fault`` or
``normal`` (``confirmed`` and ``false_positive`` are accepted). A label overlapping an episode applies to it; a
rule-specific label takes precedence over a rule-agnostic one, and a fault verdict over a normal one at the same
level. Unlabeled episodes stay unlabeled; they are scored but never used for fitting or metrics.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from open_fdd.ml.confidence import to_utc

LABEL_MAP = {"fault": 1, "confirmed": 1, "true_fault": 1, "real": 1, "normal": 0, "false_positive": 0, "healthy": 0, "tuning": 0, "review": 0}
MIN_LABELS = 20
MIN_PER_CLASS = 5


def label_episodes(episodes: pd.DataFrame, labels: pd.DataFrame) -> pd.Series:
    """1 (fault), 0 (normal) or NaN (unlabeled) per episode."""
    missing = {"equipment_id", "start_ts", "end_ts", "label"} - set(labels.columns)
    if missing:
        raise ValueError(f"labels is missing columns: {sorted(missing)}")
    lab = labels.copy()
    lab["y"] = lab["label"].astype(str).str.strip().str.lower().map(LABEL_MAP)
    lab = lab.dropna(subset=["y"])
    lab["start_ts"], lab["end_ts"] = to_utc(lab["start_ts"]).set_axis(lab.index), to_utc(lab["end_ts"]).set_axis(lab.index)
    lab["equipment_id"] = lab["equipment_id"].astype(str)
    if "rule_id" not in lab.columns:
        lab["rule_id"] = None
    by_eq = {k: g for k, g in lab.groupby("equipment_id")}
    out = np.full(len(episodes), np.nan)
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
            out[i] = float(use["y"].max())
    return pd.Series(out, index=episodes.index, name="verdict")


def features(ep: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Evidence matrix with missing-value indicators. Columns are documented by the returned names."""
    def col(name: str) -> np.ndarray:
        return pd.to_numeric(ep[name], errors="coerce").to_numpy(float) if name in ep.columns else np.full(len(ep), np.nan)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN rows mean "not assessed"
        dq = np.nanmax(np.vstack([col("dq_stale"), col("dq_gap"), col("dq_clip")]), axis=0) if len(ep) else np.array([])
    raw = {
        "persistence": col("persistence"),
        "log_duration_h": np.log1p(np.clip(col("duration_h"), 0, None)),
        "anomaly_share": col("anomaly_share"),
        "margin": np.clip(col("margin"), -3, 3),
        "threshold_survival": col("threshold_survival"),
        "co_rules": np.clip(col("co_rules"), 0, 3),
        "data_quality_bad": dq,
        "running_share": col("running_share"),
        "rule_on_share": col("rule_on_share"),
        "peer_fire_share": col("peer_fire_share"),
    }
    names, cols = [], []
    for k, v in raw.items():
        miss = ~np.isfinite(v)
        if miss.all():
            continue
        cols.append(np.where(miss, 0.0, v))
        names.append(k)
        if miss.any():
            cols.append(miss.astype(float))
            names.append(f"{k}_missing")
    x = np.column_stack(cols) if cols else np.zeros((len(ep), 0))
    return x, names


def _fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu, sd = x.mean(axis=0), x.std(axis=0)
    sd[sd == 0] = 1.0
    z = np.column_stack([np.ones(len(x)), (x - mu) / sd])
    w = np.zeros(z.shape[1])
    reg = np.full(z.shape[1], l2)
    reg[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(z @ w, -30, 30)))
        grad = z.T @ (p - y) + reg * w
        hess = (z * (p * (1 - p))[:, None]).T @ z + np.diag(reg + 1e-9)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w, mu, sd


def _predict(model: tuple[np.ndarray, np.ndarray, np.ndarray], x: np.ndarray) -> np.ndarray:
    w, mu, sd = model
    z = np.column_stack([np.ones(len(x)), (x - mu) / sd])
    return 1.0 / (1.0 + np.exp(-np.clip(z @ w, -30, 30)))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(p) - np.log(1.0 - p)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(np.asarray(z, dtype=float), -30, 30)))


def _nll(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1.0 - 1e-12)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _fit_temperature(p: np.ndarray, y: np.ndarray) -> float:
    """Positive temperature that minimises the negative log-likelihood of ``sigmoid(logit(p) / T)``.

    ``T > 1`` softens over-confident scores; ``T < 1`` sharpens under-confident ones. A coarse geometric
    grid is refined by ternary search. No site- or generator-specific default is used.
    """
    z = _logit(p)
    y = np.asarray(y, dtype=float)

    def loss(t: float) -> float:
        return _nll(y, _sigmoid(z / t))

    ts = np.geomspace(0.05, 20.0, 40)
    i = int(np.argmin([loss(t) for t in ts]))
    lo, hi = float(ts[max(0, i - 1)]), float(ts[min(len(ts) - 1, i + 1)])
    for _ in range(25):
        a, b = lo + (hi - lo) / 3.0, hi - (hi - lo) / 3.0
        if loss(a) < loss(b):
            hi = b
        else:
            lo = a
    return float((lo + hi) / 2.0)


def apply_temperature(p: np.ndarray, temperature: float) -> np.ndarray:
    return _sigmoid(_logit(p) / float(temperature))


def _fit_isotonic(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Monotone (non-decreasing) map from score to probability, by pooled adjacent violators.

    Tied scores are averaged first. Returns unique ``x`` and fitted ``y`` for interpolation.
    """
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    order = np.argsort(p, kind="mergesort")
    p, y = p[order], y[order]
    uniq, starts, counts = np.unique(p, return_index=True, return_counts=True)
    means = np.add.reduceat(y, starts) / counts
    blocks: list[list[float]] = []  # mean, weight, start_index, end_index into uniq
    for i, (m, w) in enumerate(zip(means, counts, strict=True)):
        blocks.append([float(m), float(w), float(i), float(i)])
        while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0] + 1e-15:
            m2, w2, _s2, e2 = blocks.pop()
            m1, w1, s1, _e1 = blocks.pop()
            blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2, s1, e2])
    yhat = np.empty(len(uniq), dtype=float)
    for m, _w, s, e in blocks:
        yhat[int(s):int(e) + 1] = m
    return uniq, yhat


def apply_isotonic(p: np.ndarray, model: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    xs, ys = model
    p = np.asarray(p, dtype=float)
    if len(xs) == 0:
        return np.full(len(p), np.nan)
    if len(xs) == 1:
        return np.full(len(p), float(ys[0]))
    return np.interp(p, xs, ys, left=float(ys[0]), right=float(ys[-1]))


def _metrics(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict[str, float]:
    brier = float(np.mean((p - y) ** 2))
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece = float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    # Mann-Whitney with average ranks for ties: same as pairwise counting with half credit, in O(n log n)
    ranks = pd.Series(p).rank(method="average").to_numpy()
    auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return {"brier": round(brier, 4), "ece": round(ece, 4), "auc": round(auc, 4)}


def calibrate(scored: pd.DataFrame, labels: pd.DataFrame, *, folds: int = 5, seed: int = 0) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Add ``verdict`` and calibrated scores to the scored episodes and return held-out metrics.

    Folds are grouped by equipment when there are enough units, so a unit never appears in both its fit and its test
    fold. Held-out metrics compare the heuristic ``p_real`` with temperature scaling, isotonic regression (both
    maps of that score) and the L2 logistic on the evidence features. ``p_real_calibrated`` remains the logistic
    fit, for compatibility; ``p_real_temperature`` and ``p_real_isotonic`` are also added.
    """
    out = scored.copy()
    out["verdict"] = label_episodes(out, labels)
    known = out["verdict"].notna().to_numpy()
    y_all = out["verdict"].to_numpy()
    n1, n0 = int((y_all[known] == 1).sum()), int((y_all[known] == 0).sum())
    info: dict[str, Any] = {"labeled_episodes": int(known.sum()), "fault": n1, "normal": n0}
    out["p_real_calibrated"] = np.nan
    out["p_real_temperature"] = np.nan
    out["p_real_isotonic"] = np.nan
    if known.sum() < MIN_LABELS or min(n0, n1) < MIN_PER_CLASS:
        info["status"] = f"not fitted: need at least {MIN_LABELS} labeled episodes and {MIN_PER_CLASS} of each verdict"
        return out, info
    x, names = features(out)
    xk, yk = x[known], y_all[known].astype(float)
    eq = out.loc[known, "equipment_id"].astype(str).to_numpy()
    units = np.unique(eq)
    rng = np.random.default_rng(seed)
    if len(units) >= folds:
        perm = rng.permutation(units)
        fold_of = {u: i % folds for i, u in enumerate(perm)}
        fold = np.array([fold_of[u] for u in eq])
        info["folds"] = f"{folds} folds grouped by equipment"
    else:
        fold = rng.permutation(len(yk)) % folds
        info["folds"] = f"{folds} random folds (fewer than {folds} labeled equipment)"
    held_log = np.full(len(yk), np.nan)
    held_temp = np.full(len(yk), np.nan)
    held_iso = np.full(len(yk), np.nan)
    heur = out.loc[known, "p_real"].to_numpy(float)
    temps: list[float] = []
    for f in range(folds):
        test = fold == f
        train = ~test
        if test.sum() == 0 or len(np.unique(yk[train])) < 2:
            continue
        held_log[test] = _predict(_fit_logistic(xk[train], yk[train]), xk[test])
        t = _fit_temperature(heur[train], yk[train])
        temps.append(t)
        held_temp[test] = apply_temperature(heur[test], t)
        held_iso[test] = apply_isotonic(heur[test], _fit_isotonic(heur[train], yk[train]))
    ho: dict[str, Any] = {"episodes": 0}
    for key, pred in (("logistic", held_log), ("temperature", held_temp), ("isotonic", held_iso)):
        ok = np.isfinite(pred)
        if ok.sum() and len(np.unique(yk[ok])) == 2:
            ho[key] = _metrics(yk[ok], pred[ok])
            ho["episodes"] = max(ho["episodes"], int(ok.sum()))
    ok_h = np.isfinite(heur)
    if ok_h.sum() and len(np.unique(yk[ok_h])) == 2:
        ho["heuristic"] = _metrics(yk[ok_h], heur[ok_h])
        ho["episodes"] = max(ho["episodes"], int(ok_h.sum()))
    if "logistic" in ho:
        ho["calibrated"] = ho["logistic"]  # compatibility with earlier reports
    if ho.get("episodes"):
        info["held_out"] = ho
    if temps:
        info["temperature"] = round(float(np.mean(temps)), 3)
    model = _fit_logistic(xk, yk)
    out["p_real_calibrated"] = np.round(_predict(model, x), 3)
    T = _fit_temperature(heur, yk)
    out["p_real_temperature"] = np.round(apply_temperature(out["p_real"].to_numpy(float), T), 3)
    out["p_real_isotonic"] = np.round(apply_isotonic(out["p_real"].to_numpy(float), _fit_isotonic(heur, yk)), 3)
    info["temperature_final"] = round(float(T), 3)
    w, _, _ = model
    info["weights"] = {n: round(float(v), 3) for n, v in sorted(zip(names, w[1:]), key=lambda t: -abs(t[1]))}
    info["status"] = "fitted"
    return out, info
