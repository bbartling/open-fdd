"""Fault-confidence screening for rule-based FDD output.

    open-fdd-ml confidence --flags flags.csv --history history.csv --out-dir confidence_out

For every fault episode a rule flagged, estimate how likely it is to be a real fault, a false positive caused by
data or operating context, or a sign that the rule's threshold or applicability needs tuning. Also roll the episodes
up per equipment and per rule. The tool is advisory only: it reads rule output and point history and never changes
a rule, a tuner, a tag or a stored result.

Inputs are plain DataFrames (or CSV files), independent of the database that ran the rules:

* ``flags``: long format, one row per rule evaluation sample: ``timestamp``, ``equipment_id``, ``rule_id``, ``flag``
  (1/0, true/false or FAULT/PASS). Optional columns: ``value`` and ``threshold`` (the SI quantity the rule compared
  and its limit; enables margin and threshold-sensitivity features), ``direction`` (``above``/``below``) and
  ``running`` (1 when the equipment was proven on).
* ``history`` (optional): long format SI point history: ``timestamp``, ``equipment_id``, ``point_id``, ``value``.
  Used for data-quality and anomaly evidence.

Scores are heuristic log-odds, not a calibrated probability. Calibrating them needs labeled episodes; see the
documentation for what the numbers mean and do not mean. A quiet anomaly score never by itself labels an episode a
false positive; that label needs data-quality or operating-context evidence.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:  # pandas/numpy come with the ml extra; keep `open-fdd-ml --help` working on a core install
    import numpy as np
    import pandas as pd
except ImportError:  # pragma: no cover
    np = pd = None  # type: ignore[assignment]

_EXTRA_HINT = "open-fdd-ml confidence needs pandas and numpy: pip install 'open-fdd[ml]'"


def _require_pandas() -> None:
    if pd is None or np is None:
        raise ImportError(_EXTRA_HINT)

LABELS = ("likely_real", "likely_false_positive", "tuning_suggested", "uncertain")
_TRUE_TEXT = {"1", "true", "t", "yes", "y", "fault", "on"}


@dataclass(frozen=True)
class ConfidenceConfig:
    """Knobs for episode building and scoring. Defaults are deliberately conservative."""

    gap_samples: int = 1  # flagged runs separated by at most this many clear samples merge into one episode
    min_episode_samples: int = 1
    sensitivity_frac: float = 0.10  # threshold nudge as a fraction of the value's robust spread
    anomaly_z: float = 3.0  # robust |z| that counts a sample as abnormal
    peer_fire_share: float = 0.6  # rule firing on at least this share of its equipment suggests tuning
    chronic_share: float = 0.5  # rule flagged at least this share of the time on one equipment suggests tuning
    stale_run: int = 6  # identical consecutive readings that count as stale
    uncertain_below: float = 0.45  # top probability under this gives the label "uncertain"
    # rules whose purpose is sensor or data validation; their faults are confirmed, not discounted, by poor data
    data_quality_rules: tuple[str, ...] = ()


# --------------------------------------------------------------------------- input normalisation


def _as_flag(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.astype(int)
    if pd.api.types.is_numeric_dtype(series):
        return (series.fillna(0) > 0).astype(int)
    return series.astype(str).str.strip().str.lower().isin(_TRUE_TEXT).astype(int)


def normalize_flags(flags: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise a long fault-flag frame."""
    missing = {"timestamp", "equipment_id", "rule_id", "flag"} - set(flags.columns)
    if missing:
        raise ValueError(f"flags is missing columns: {sorted(missing)}")
    out = flags.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["equipment_id"] = out["equipment_id"].astype(str)
    out["rule_id"] = out["rule_id"].astype(str)
    out["flag"] = _as_flag(out["flag"])
    for col in ("value", "threshold"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "running" in out.columns:
        out["running"] = _as_flag(out["running"])
    return out.sort_values(["equipment_id", "rule_id", "timestamp"]).reset_index(drop=True)


def normalize_history(history: pd.DataFrame | None) -> pd.DataFrame | None:
    if history is None or history.empty:
        return None
    missing = {"timestamp", "equipment_id", "point_id", "value"} - set(history.columns)
    if missing:
        raise ValueError(f"history is missing columns: {sorted(missing)}")
    out = history.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["equipment_id"] = out["equipment_id"].astype(str)
    out["point_id"] = out["point_id"].astype(str)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.sort_values(["equipment_id", "point_id", "timestamp"]).reset_index(drop=True)


# --------------------------------------------------------------------------- episodes


def build_episodes(flags: pd.DataFrame, config: ConfidenceConfig | None = None) -> pd.DataFrame:
    """Group consecutive flagged samples per (equipment, rule) into episodes."""
    cfg = config or ConfidenceConfig()
    rows: list[dict[str, Any]] = []
    for (eq, rule), grp in flags.groupby(["equipment_id", "rule_id"], sort=False):
        f = grp["flag"].to_numpy()
        ts = grp["timestamp"].to_numpy()
        idx = np.flatnonzero(f == 1)
        if idx.size == 0:
            continue
        splits = np.flatnonzero(np.diff(idx) > cfg.gap_samples + 1)
        for chunk in np.split(idx, splits + 1):
            if chunk.size < cfg.min_episode_samples:
                continue
            lo, hi = int(chunk[0]), int(chunk[-1])
            span = f[lo : hi + 1]
            rows.append(
                {
                    "equipment_id": eq,
                    "rule_id": rule,
                    "start": pd.Timestamp(ts[lo]).tz_localize("UTC") if pd.Timestamp(ts[lo]).tzinfo is None else pd.Timestamp(ts[lo]),
                    "end": pd.Timestamp(ts[hi]).tz_localize("UTC") if pd.Timestamp(ts[hi]).tzinfo is None else pd.Timestamp(ts[hi]),
                    "row_lo": lo + int(grp.index[0]),
                    "row_hi": hi + int(grp.index[0]),
                    "n_samples": int(span.size),
                    "persistence": float(span.mean()),
                }
            )
    ep = pd.DataFrame(rows)
    if ep.empty:
        return ep
    ep["duration_h"] = (ep["end"] - ep["start"]).dt.total_seconds() / 3600.0
    ep.insert(0, "episode_id", [f"E{i + 1:05d}" for i in range(len(ep))])
    return ep


# --------------------------------------------------------------------------- features


def _robust_scale(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if x.size < 3:
        return float("nan")
    mad = float(np.median(np.abs(x - np.median(x)))) * 1.4826
    if mad > 0:
        return mad
    std = float(np.std(x))
    return std if std > 0 else float("nan")


def _margin_features(seg: pd.DataFrame, allv: pd.Series, cfg: ConfidenceConfig) -> dict[str, float]:
    if not {"value", "threshold"} <= set(seg.columns):
        return {"margin": float("nan"), "threshold_survival": float("nan")}
    flagged = seg[seg["flag"] == 1]
    v = flagged["value"].to_numpy(float)
    t = flagged["threshold"].to_numpy(float)
    ok = np.isfinite(v) & np.isfinite(t)
    if not ok.any():
        return {"margin": float("nan"), "threshold_survival": float("nan")}
    direction = str(flagged["direction"].iloc[0]).lower() if "direction" in flagged.columns else ""
    if direction not in {"above", "below"}:
        direction = "above" if float(np.nanmedian(v[ok] - t[ok])) >= 0 else "below"
    sign = 1.0 if direction == "above" else -1.0
    exceed = sign * (v[ok] - t[ok])
    scale = _robust_scale(allv.to_numpy(float))
    if not math.isfinite(scale):
        scale = float(np.nanmax(np.abs(t[ok]))) * 0.05 or 1.0
    delta = cfg.sensitivity_frac * scale
    return {
        "margin": float(np.median(exceed) / scale),
        "threshold_survival": float(np.mean(exceed > delta)),
    }


def _quality_features(hist: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp, cfg: ConfidenceConfig) -> dict[str, float]:
    nan = {"dq_stale": float("nan"), "dq_gap": float("nan"), "dq_clip": float("nan")}
    if hist is None or hist.empty:
        return nan
    win = hist[(hist["timestamp"] >= start) & (hist["timestamp"] <= end)]
    if win.empty:
        return {"dq_stale": float("nan"), "dq_gap": 1.0, "dq_clip": float("nan")}
    stale, gap, clip = [], [], []
    for _, s in win.groupby("point_id"):
        v = s["value"].to_numpy(float)
        gap.append(float(np.mean(~np.isfinite(v))))
        v = v[np.isfinite(v)]
        if v.size < 2:
            continue
        same = np.concatenate([[False], np.diff(v) == 0])
        runs = pd.Series(same).groupby((~pd.Series(same)).cumsum()).cumsum().to_numpy()
        stale.append(float(np.mean(runs >= cfg.stale_run - 1)) if np.ptp(v) > 0 else 1.0)
        full = hist.loc[hist["point_id"] == s["point_id"].iloc[0], "value"].to_numpy(float)
        full = full[np.isfinite(full)]
        if full.size > 10 and np.ptp(full) > 0:
            lo, hi = float(np.min(full)), float(np.max(full))
            at_edge = (np.isclose(v, lo) | np.isclose(v, hi))
            clip.append(float(np.mean(at_edge)) if np.mean(np.isclose(full, hi)) > 0.02 or np.mean(np.isclose(full, lo)) > 0.02 else 0.0)
    return {
        "dq_stale": float(np.mean(stale)) if stale else float("nan"),
        "dq_gap": float(np.mean(gap)) if gap else float("nan"),
        "dq_clip": float(np.mean(clip)) if clip else float("nan"),
    }


def _anomaly_feature(hist: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp, cfg: ConfidenceConfig) -> float:
    """Share of in-episode samples whose robust z (vs the same point outside the episode) exceeds ``anomaly_z``.

    Taken as the maximum over the equipment's points, so one clearly abnormal input is enough."""
    if hist is None or hist.empty:
        return float("nan")
    best = float("nan")
    inside_mask = (hist["timestamp"] >= start) & (hist["timestamp"] <= end)
    for pid, s in hist.groupby("point_id"):
        m = inside_mask.loc[s.index].to_numpy()
        inside = s["value"].to_numpy(float)[m]
        outside = s["value"].to_numpy(float)[~m]
        inside, outside = inside[np.isfinite(inside)], outside[np.isfinite(outside)]
        if inside.size == 0 or outside.size < 10:
            continue
        scale = _robust_scale(outside)
        if not math.isfinite(scale):
            continue
        share = float(np.mean(np.abs(inside - np.median(outside)) / scale > cfg.anomaly_z))
        best = share if not math.isfinite(best) else max(best, share)
    return best


def episode_features(
    flags: pd.DataFrame,
    episodes: pd.DataFrame,
    history: pd.DataFrame | None = None,
    config: ConfidenceConfig | None = None,
) -> pd.DataFrame:
    """Add explainable evidence columns to each episode."""
    cfg = config or ConfidenceConfig()
    if episodes.empty:
        return episodes
    ep = episodes.copy()
    hist_by_eq = {k: g for k, g in history.groupby("equipment_id")} if history is not None else {}

    # rule-level context: share of time flagged per (equipment, rule) and share of equipment that fired
    on_share = flags.groupby(["equipment_id", "rule_id"])["flag"].mean().rename("rule_on_share")
    fired = flags.groupby(["rule_id", "equipment_id"])["flag"].max().groupby("rule_id")
    peer = (fired.mean()).rename("peer_fire_share")
    peer_n = fired.size().rename("peer_equipment")
    ep = ep.join(on_share, on=["equipment_id", "rule_id"]).join(peer, on="rule_id").join(peer_n, on="rule_id")

    feats: list[dict[str, float]] = []
    for row in ep.itertuples(index=False):
        seg = flags.loc[row.row_lo : row.row_hi]
        allv = flags.loc[(flags["equipment_id"] == row.equipment_id) & (flags["rule_id"] == row.rule_id), "value"] if "value" in flags.columns else pd.Series(dtype=float)
        f: dict[str, float] = {}
        f.update(_margin_features(seg, allv, cfg))
        f["running_share"] = float(seg["running"].mean()) if "running" in seg.columns else float("nan")
        hist = hist_by_eq.get(row.equipment_id)
        f.update(_quality_features(hist, row.start, row.end, cfg))
        f["anomaly_share"] = _anomaly_feature(hist, row.start, row.end, cfg)
        others = ep[(ep["equipment_id"] == row.equipment_id) & (ep["rule_id"] != row.rule_id)]
        f["co_rules"] = float(others[(others["start"] <= row.end) & (others["end"] >= row.start)]["rule_id"].nunique())
        feats.append(f)
    return pd.concat([ep.reset_index(drop=True), pd.DataFrame(feats)], axis=1)


# --------------------------------------------------------------------------- scoring


def _nz(x: float, default: float = 0.0) -> float:
    return default if x is None or not math.isfinite(float(x)) else float(x)


def is_data_quality_rule(rule_id: str, cfg: ConfidenceConfig) -> bool:
    rid = str(rule_id).upper()
    return any(rid.startswith(p.upper()) for p in cfg.data_quality_rules)


def _score_row(r: pd.Series, cfg: ConfidenceConfig) -> dict[str, Any]:
    real, fp, tune = 0.0, -0.5, -0.5
    why_real: list[str] = []
    why_fp: list[str] = []
    why_tune: list[str] = []

    dq_parts = [r.get("dq_stale"), r.get("dq_gap"), r.get("dq_clip")]
    dq_assessed = any(x is not None and math.isfinite(float(x)) for x in dq_parts)
    dq = max(_nz(x) for x in dq_parts)
    if is_data_quality_rule(r.get("rule_id"), cfg):
        # a sensor-validation rule: measured poor data corroborates it; clean data argues against it
        if dq_assessed and dq >= 0.5:
            real += 1.0 + 2.0 * dq
            why_real.append(f"data-quality rule confirmed by the inputs (stale/gap/clipped share {dq:.0%})")
        elif dq_assessed and dq < 0.1:
            tune += 1.0
            why_tune.append("data-quality rule fired but the inputs look clean")
        dq = 0.0
    caveats: list[str] = []
    if not dq_assessed:
        real -= 0.5
        caveats.append("input data quality not assessed (no history for this equipment)")
    if dq >= 0.5:
        fp += 3.0 * dq
        why_fp.append(f"input data quality is poor during the episode (stale/gap/clipped share {dq:.0%})")
    run = r.get("running_share")
    if run is not None and math.isfinite(run) and run < 0.5:
        fp += 2.0 * (1 - run)
        why_fp.append(f"equipment proven running for only {run:.0%} of the episode")
    if _nz(r.get("n_samples"), 1) <= 2 and _nz(r.get("persistence"), 1) < 1.0:
        fp += 0.8
        why_fp.append("very short, intermittent episode")

    # evidence computed from untrusted inputs is discounted, not counted as proof of a real fault
    trust = 1.0 - dq
    pers = _nz(r.get("persistence"), 1.0)
    dur = _nz(r.get("duration_h"))
    real += trust * (1.0 * (pers - 0.5) + 0.6 * math.log1p(dur))
    if dur >= 1 and pers >= 0.8 and trust >= 0.5:
        why_real.append(f"persistent ({pers:.0%} of samples) for {dur:.1f} h")
    anom = r.get("anomaly_share")
    if anom is not None and math.isfinite(anom):
        real += trust * (2.5 * anom) - 0.3
        if anom >= 0.2 and trust >= 0.5:
            why_real.append(f"inputs are statistically abnormal for {anom:.0%} of the episode")
    margin = r.get("margin")
    surv = r.get("threshold_survival")
    if margin is not None and math.isfinite(margin):
        real += trust * 0.8 * min(margin, 3.0)
        if margin >= 1.0 and trust >= 0.5:
            why_real.append(f"exceeds the threshold by {margin:.1f} robust spreads")
    if surv is not None and math.isfinite(surv):
        tune += 2.5 * (1 - surv)
        if surv < 0.5:
            why_tune.append(f"marginal: only {surv:.0%} of flagged samples survive a small threshold nudge")
    co = _nz(r.get("co_rules"))
    if co > 0:
        real += trust * 0.6 * min(co, 3)
        why_real.append(f"{int(co)} other rule(s) fault on the same equipment at the same time")

    peer = _nz(r.get("peer_fire_share"))
    npeer = int(_nz(r.get("peer_equipment"), 1))
    if npeer >= 3 and peer >= cfg.peer_fire_share:
        tune += 2.0 * peer
        real -= 0.5
        why_tune.append(f"rule fires on {peer:.0%} of the {npeer} equipment it runs on")
    chronic = _nz(r.get("rule_on_share"))
    if chronic >= cfg.chronic_share:
        tune += 1.5 * chronic
        why_tune.append(f"rule is flagged {chronic:.0%} of the time on this equipment (chronic)")

    logits = np.array([real, fp, tune])
    p = np.exp(logits - logits.max())
    p = p / p.sum()
    k = int(np.argmax(p))
    label = LABELS[k] if p[k] >= cfg.uncertain_below else "uncertain"
    reasons = (why_real, why_fp, why_tune)[k] if label != "uncertain" else why_real + why_fp + why_tune
    reasons = list(reasons) + caveats
    return {
        "p_real": round(float(p[0]), 3),
        "p_false_positive": round(float(p[1]), 3),
        "p_tuning": round(float(p[2]), 3),
        "label": label,
        "reason": "; ".join(reasons) if reasons else "no strong evidence either way",
    }


def score_episodes(features: pd.DataFrame, config: ConfidenceConfig | None = None) -> pd.DataFrame:
    """Score each episode: ``p_real``, ``p_false_positive``, ``p_tuning``, ``label`` and ``reason``."""
    cfg = config or ConfidenceConfig()
    if features.empty:
        return features.assign(p_real=[], p_false_positive=[], p_tuning=[], label=[], reason=[])
    scored = pd.DataFrame([_score_row(r, cfg) for _, r in features.iterrows()])
    out = pd.concat([features.reset_index(drop=True), scored], axis=1).drop(columns=["row_lo", "row_hi"], errors="ignore")
    out["data_quality_rule"] = out["rule_id"].map(lambda rid: is_data_quality_rule(rid, cfg))
    return out


# --------------------------------------------------------------------------- roll-ups


def equipment_health(scored: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Per-equipment roll-up. Many distinct rules with high ``p_real`` point at the equipment, not the rules."""
    evaluated = flags.groupby("equipment_id").agg(rules_evaluated=("rule_id", "nunique"))
    if scored.empty:
        out = evaluated.assign(episodes=0, rules_faulting=0, expected_real=0.0, health="ok")
        return out.reset_index()
    g = scored.groupby("equipment_id")
    out = pd.DataFrame(
        {
            "episodes": g.size(),
            "rules_faulting": g["rule_id"].nunique(),
            "expected_real": g["p_real"].sum().round(2),
            "likely_real": g["label"].apply(lambda s: int((s == "likely_real").sum())),
            "tuning_suggested": g["label"].apply(lambda s: int((s == "tuning_suggested").sum())),
            "likely_false_positive": g["label"].apply(lambda s: int((s == "likely_false_positive").sum())),
            "fault_hours_weighted": (scored["duration_h"] * scored["p_real"]).groupby(scored["equipment_id"]).sum().round(2),
        }
    )
    out = evaluated.join(out, how="left").fillna(0)
    dq_mask = scored["data_quality_rule"] if "data_quality_rule" in scored.columns else pd.Series(False, index=scored.index)
    real = scored[(scored["label"] == "likely_real") & ~dq_mask]
    data_real = scored[(scored["label"] == "likely_real") & dq_mask]
    out["rules_likely_real"] = real.groupby("equipment_id")["rule_id"].nunique().reindex(out.index).fillna(0).astype(int)
    out["data_issues"] = data_real.groupby("equipment_id")["rule_id"].nunique().reindex(out.index).fillna(0).astype(int)

    def verdict(r: pd.Series) -> str:
        if r["rules_likely_real"] == 0 and r["data_issues"] > 0:
            return "sensor or data issue"
        if r["rules_likely_real"] >= 2:
            return "equipment issue likely"
        if r["rules_likely_real"] == 1:
            return "check equipment"
        if r["tuning_suggested"] > 0 and r["likely_real"] == 0:
            return "faults look like tuning"
        if r["likely_false_positive"] > 0 and r["likely_real"] == 0:
            return "faults look like data or context"
        return "ok" if r["episodes"] == 0 else "review"

    out["health"] = out.apply(verdict, axis=1)
    return out.reset_index().sort_values(["expected_real", "episodes"], ascending=False)


def rule_summary(scored: pd.DataFrame, flags: pd.DataFrame, config: ConfidenceConfig | None = None) -> pd.DataFrame:
    """Per-rule peer comparison. A rule firing everywhere is a tuning or applicability question."""
    base = flags.groupby("rule_id").agg(equipment_evaluated=("equipment_id", "nunique"), flagged_share=("flag", "mean"))
    if scored.empty:
        return base.assign(episodes=0, equipment_faulting=0).reset_index()
    g = scored.groupby("rule_id")
    out = base.join(
        pd.DataFrame(
            {
                "episodes": g.size(),
                "equipment_faulting": g["equipment_id"].nunique(),
                "mean_p_real": g["p_real"].mean().round(3),
                "mean_p_tuning": g["p_tuning"].mean().round(3),
                "mean_p_false_positive": g["p_false_positive"].mean().round(3),
            }
        ),
        how="left",
    ).fillna(0)
    out["flagged_share"] = out["flagged_share"].round(3)
    out["fires_on_share"] = (out["equipment_faulting"] / out["equipment_evaluated"]).round(3)
    out["suggestion"] = np.where(
        (out["mean_p_tuning"] >= 0.45) | ((out["fires_on_share"] >= 0.6) & (out["equipment_evaluated"] >= 3)),
        "review threshold or applicability",
        np.where(out["mean_p_real"] >= 0.5, "faults look real", "mixed"),
    )
    cfg = config or ConfidenceConfig()
    dq_rule = out.index.to_series().map(lambda rid: is_data_quality_rule(rid, cfg))
    out.loc[dq_rule & (out["mean_p_real"] >= 0.5) & (out["fires_on_share"] >= 0.6), "suggestion"] = (
        "data problem across equipment (check trending, polling or sensors)"
    )
    out.loc[out["episodes"] == 0, "suggestion"] = "no faults"
    return out.reset_index().sort_values(["episodes"], ascending=False)


# --------------------------------------------------------------------------- one-call API and CLI


def screen(
    flags: pd.DataFrame,
    history: pd.DataFrame | None = None,
    config: ConfidenceConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Run the whole screen. Returns ``episodes``, ``equipment`` and ``rules`` DataFrames."""
    _require_pandas()
    cfg = config or ConfidenceConfig()
    fl = normalize_flags(flags)
    hist = normalize_history(history)
    ep = build_episodes(fl, cfg)
    scored = score_episodes(episode_features(fl, ep, hist, cfg), cfg)
    return {"episodes": scored, "equipment": equipment_health(scored, fl), "rules": rule_summary(scored, fl, cfg)}


def summarize(result: dict[str, pd.DataFrame]) -> dict[str, Any]:
    ep = result["episodes"]
    counts = ep["label"].value_counts().to_dict() if not ep.empty else {}
    return {
        "episodes": len(ep),
        "labels": {k: int(counts.get(k, 0)) for k in LABELS},
        "equipment_flagged": int((result["equipment"]["episodes"] > 0).sum()) if not result["equipment"].empty else 0,
        "rules_to_review": result["rules"].loc[result["rules"]["suggestion"] == "review threshold or applicability", "rule_id"].tolist()
        if not result["rules"].empty
        else [],
        "note": "Advisory heuristic scores; no rule, tuner or stored result was changed.",
    }


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--flags", required=True, help="CSV of long fault flags: timestamp, equipment_id, rule_id, flag [, value, threshold, direction, running]")
    ap.add_argument("--history", help="optional CSV of long SI point history: timestamp, equipment_id, point_id, value")
    ap.add_argument("--out-dir", default="confidence_out", help="where to write episodes.csv, equipment.csv, rules.csv, summary.json")
    ap.add_argument("--gap-samples", type=int, default=ConfidenceConfig.gap_samples)
    ap.add_argument("--sensitivity-frac", type=float, default=ConfidenceConfig.sensitivity_frac)
    ap.add_argument("--data-quality-rules", default="", help="comma list of rule-id prefixes that are sensor/data validation rules")


def run_cli(args: argparse.Namespace) -> int:
    _require_pandas()
    dq_rules = tuple(p.strip() for p in (args.data_quality_rules or "").split(",") if p.strip())
    cfg = ConfidenceConfig(gap_samples=args.gap_samples, sensitivity_frac=args.sensitivity_frac, data_quality_rules=dq_rules)
    flags = pd.read_csv(args.flags)
    history = pd.read_csv(args.history) if args.history else None
    result = screen(flags, history, cfg)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in result.items():
        df.to_csv(out / f"{name}.csv", index=False)
    summary = summarize(result)
    summary["config"] = asdict(cfg)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="open-fdd-ml confidence", description=__doc__.split("\n\n")[0])
    add_arguments(ap)
    return run_cli(ap.parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
