"""Fault-confidence screening for rule-based FDD output.

    open-fdd-ml confidence --sqlite fdd.db --out-dir triage            # Open-FDD rule_result in SQLite
    open-fdd-ml confidence --duckdb fdd.duckdb --layout flags --table fault_flags
    open-fdd-ml confidence --flags flags.csv --history history.csv --out-dir triage

For every fault episode a rule flagged, estimate how likely it is to be a real fault, a false positive caused by
data or operating context, or a sign that the rule's threshold or applicability needs review. Roll the episodes up
per equipment and per rule, and write a compact JSON and Markdown triage report a person (or an agent relaying to a
person) can act on. Advisory only: it reads rule output and point history and never changes a rule, a tuner, a tag
or a stored result.

Episode building and per-rule totals run as portable SQL inside the database (SQLite, DuckDB, PostgreSQL,
TimescaleDB); see ``open_fdd.ml.confidence_sql``. DataFrame and CSV input goes through an in-memory SQLite database,
so both paths share one implementation. Point-history evidence (data quality, abnormality) is read only for the
episodes being scored, capped by ``max_history_episodes``.

Scores are heuristic log-odds turned into shares, not calibrated probabilities. A quiet anomaly score never by itself
labels an episode a false positive; that label needs data-quality or operating-context evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pandas/numpy come with the ml extra; keep `open-fdd-ml --help` working on a core install
    import numpy as np
    import pandas as pd
except ImportError:  # pragma: no cover
    np = pd = None  # type: ignore[assignment]

from open_fdd.ml.confidence_sql import (
    HistoryMap,
    SourceMap,
    episodes_sql,
    fetch,
    history_sql,
    paramstyle,
    totals_sql,
)

DESCRIPTION = ("Score rule-based fault episodes as likely real, likely false positive or rule review suggested, roll them up "
               "per equipment and rule, and write a JSON + Markdown triage report. Advisory only; nothing is tuned.")
LABELS = ("likely_real", "likely_false_positive", "tuning_suggested", "uncertain")
_EXTRA_HINT = "open-fdd-ml confidence needs pandas and numpy: pip install 'open-fdd[ml]'"

HistoryProvider = Callable[[str, Any, Any], "pd.DataFrame"]


def _require_pandas() -> None:
    if pd is None or np is None:
        raise ImportError(_EXTRA_HINT)


@dataclass(frozen=True)
class ConfidenceConfig:
    """Knobs for episode building and scoring. Defaults are deliberately conservative."""

    gap_samples: int = 1  # flagged runs separated by at most this many clear evaluations merge into one episode
    sensitivity_frac: float = 0.10  # threshold nudge as a fraction of the compared value's standard deviation
    anomaly_z: float = 3.0  # robust |z| that counts a sample as abnormal
    peer_fire_share: float = 0.6  # rule firing on at least this share of its equipment suggests review
    peer_min_equipment: int = 3
    chronic_share: float = 0.5  # rule flagged at least this share of the time on one unit suggests review
    stale_run: int = 6  # identical consecutive readings that count as stale
    expected_interval_s: float | None = None  # history cadence; None = each point's own median spacing
    baseline_hours: float = 72.0  # history read on each side of an episode for the abnormality baseline
    max_history_episodes: int = 500  # history evidence for the longest N episodes; the rest are marked unassessed
    uncertain_below: float = 0.45  # top share under this gives the label "uncertain"
    data_quality_rules: tuple[str, ...] = ()  # rule-id prefixes of sensor or data validation rules


# --------------------------------------------------------------------------- input adapters


def to_utc(values: Any) -> pd.Series:
    """Parse timestamps to UTC, accepting mixed ISO 8601 forms (with or without fractions or offsets)."""
    s = pd.Series(values)
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, utc=True)
    try:
        return pd.to_datetime(s, utc=True, format="ISO8601")
    except (ValueError, TypeError):
        return pd.to_datetime(s, utc=True, format="mixed")


def _iso(series: pd.Series) -> pd.Series:
    return to_utc(series).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ").set_axis(series.index)


def frame_to_sqlite(flags: pd.DataFrame | None = None, results: pd.DataFrame | None = None) -> tuple[sqlite3.Connection, SourceMap]:
    """Load a flags or Open-FDD results DataFrame into in-memory SQLite and return the matching ``SourceMap``."""
    _require_pandas()
    conn = sqlite3.connect(":memory:")
    if flags is not None:
        missing = {"timestamp", "equipment_id", "rule_id", "flag"} - set(flags.columns)
        if missing:
            raise ValueError(f"flags is missing columns: {sorted(missing)}")
        df = flags.copy()
        df["timestamp"] = _iso(df["timestamp"])
        for c in ("equipment_id", "rule_id"):
            df[c] = df[c].astype(str)
        cols = {c: c for c in ("value", "threshold", "running") if c in df.columns}
        keep = ["timestamp", "equipment_id", "rule_id", "flag", *cols]
        df[keep].to_sql("fault_flags", conn, index=False)
        src = SourceMap.for_flags("fault_flags", columns={"site_id": "", **{c: cols.get(c, "") for c in ("value", "threshold", "running")}})
        return conn, src
    if results is not None:
        missing = {"equipment_id", "rule_id", "window_start", "window_end", "status"} - set(results.columns)
        if missing:
            raise ValueError(f"results is missing columns: {sorted(missing)}")
        df = results.copy()
        df["window_start"], df["window_end"] = _iso(df["window_start"]), _iso(df["window_end"])
        opt = {c: (c if c in df.columns else "") for c in ("site_id", "subject_key", "fault_hours", "covered_hours")}
        df[["equipment_id", "rule_id", "window_start", "window_end", "status", *[c for c in opt.values() if c]]].to_sql(
            "rule_result", conn, index=False)
        return conn, SourceMap(table="rule_result", columns=opt)
    raise ValueError("pass flags or results")


def frame_history_provider(history: pd.DataFrame) -> HistoryProvider:
    """History provider over a long DataFrame: ``timestamp, equipment_id, point_id, value`` (optional ``kind``)."""
    missing = {"timestamp", "equipment_id", "point_id", "value"} - set(history.columns)
    if missing:
        raise ValueError(f"history is missing columns: {sorted(missing)}")
    h = history.copy()
    h["timestamp"] = to_utc(h["timestamp"]).set_axis(h.index)
    h["equipment_id"] = h["equipment_id"].astype(str)
    h["value"] = pd.to_numeric(h["value"], errors="coerce")
    if "kind" not in h.columns:
        h["kind"] = None
    groups = {k: g.sort_values("timestamp") for k, g in h.groupby("equipment_id")}

    def provide(equipment_id: str, start: Any, end: Any) -> pd.DataFrame:
        g = groups.get(str(equipment_id))
        if g is None:
            return pd.DataFrame(columns=["ts", "point_id", "value", "kind"])
        m = (g["timestamp"] >= start) & (g["timestamp"] <= end)
        return g.loc[m, ["timestamp", "point_id", "value", "kind"]].rename(columns={"timestamp": "ts"})

    return provide


def sql_history_provider(conn: Any, hm: HistoryMap | None = None) -> HistoryProvider:
    """History provider that reads one equipment's points per call with a parameterised query."""
    hm = hm or HistoryMap()
    ph = paramstyle(conn)
    sql = history_sql(hm, ph)
    text_ts = isinstance(conn, sqlite3.Connection)

    def provide(equipment_id: str, start: Any, end: Any) -> pd.DataFrame:
        a, b = (pd.Timestamp(start), pd.Timestamp(end))
        params = [equipment_id, *(x.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if text_ts else x.to_pydatetime() for x in (a, b))]
        cols, rows = fetch(conn, sql, params)
        df = pd.DataFrame(rows, columns=cols)
        if not df.empty:
            df["ts"] = to_utc(df["ts"]).set_axis(df.index)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df

    return provide


# --------------------------------------------------------------------------- episodes from SQL


def _merge_islands(isl: pd.DataFrame, gap: int) -> pd.DataFrame:
    if isl.empty:
        return isl
    isl = isl.sort_values(["equipment_id", "rule_id", "subject", "rn_min"]).reset_index(drop=True)
    key = isl["equipment_id"] + "\x1f" + isl["rule_id"] + "\x1f" + isl["subject"]
    prev_end = isl.groupby(key)["rn_max"].shift()
    new = prev_end.isna() | ((isl["rn_min"] - prev_end - 1) > gap)
    isl["ep"] = new.cumsum()
    w = isl["n_samples"]
    agg = isl.assign(
        _ex=isl["exceed_mean"] * isl["n_exceed"], _run=isl["running_share"] * w,
    ).groupby("ep").agg(
        equipment_id=("equipment_id", "first"), rule_id=("rule_id", "first"), subject=("subject", "first"),
        start=("start_ts", "min"), end=("end_ts", "max"), rn_min=("rn_min", "min"), rn_max=("rn_max", "max"),
        n_samples=("n_samples", "sum"), fault_h=("fault_h", "sum"), covered_h=("covered_h", "sum"),
        _ex=("_ex", "sum"), n_exceed=("n_exceed", "sum"), n_survive=("n_survive", "sum"),
        _run=("_run", "sum"), _runw=("running_share", lambda s: w.loc[s.dropna().index].sum()),
        _fhn=("fault_h", "count"), _chn=("covered_h", "count"),
    )
    agg["exceed_mean"] = np.where(agg["n_exceed"] > 0, agg["_ex"] / agg["n_exceed"].replace(0, np.nan), np.nan)
    agg["running_share"] = np.where(agg["_runw"] > 0, agg["_run"] / agg["_runw"].replace(0, np.nan), np.nan)
    agg.loc[agg["_fhn"] == 0, "fault_h"] = np.nan
    agg.loc[agg["_chn"] == 0, "covered_h"] = np.nan
    return agg.drop(columns=["_ex", "_run", "_runw", "_fhn", "_chn"]).reset_index(drop=True)


def load_episodes(conn: Any, src: SourceMap, config: ConfidenceConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the portable SQL and return ``(episodes, totals)`` DataFrames."""
    _require_pandas()
    cfg = config or ConfidenceConfig()
    ph = paramstyle(conn)
    tcols, trows = fetch(conn, *totals_sql(src, ph))
    totals = pd.DataFrame(trows, columns=tcols)
    for c in ("n_assessed", "n_flagged", "n_unassessed"):
        totals[c] = pd.to_numeric(totals[c]).fillna(0).astype(int)
    for c in ("v_mean", "v_sq_mean"):
        totals[c] = pd.to_numeric(totals[c], errors="coerce")
    totals["equipment_id"] = totals["equipment_id"].astype(str)
    totals["rule_id"] = totals["rule_id"].astype(str)
    ecols, erows = fetch(conn, *episodes_sql(src, cfg.sensitivity_frac, ph))
    isl = pd.DataFrame(erows, columns=ecols)
    if isl.empty:
        return pd.DataFrame(columns=["episode_id", "equipment_id", "rule_id", "subject", "start", "end"]), totals
    for c in ("equipment_id", "rule_id", "subject"):
        isl[c] = isl[c].astype(str)
    num = ("rn_min", "rn_max", "n_samples", "fault_h", "covered_h", "exceed_mean", "n_exceed", "n_survive", "running_share")
    for c in num:
        isl[c] = pd.to_numeric(isl[c], errors="coerce")
    isl["start_ts"] = to_utc(isl["start_ts"]).set_axis(isl.index)
    isl["end_ts"] = to_utc(isl["end_ts"]).set_axis(isl.index)
    ep = _merge_islands(isl, cfg.gap_samples)
    ep["duration_h"] = (ep["end"] - ep["start"]).dt.total_seconds() / 3600.0
    span = (ep["rn_max"] - ep["rn_min"] + 1).clip(lower=1)
    ratio = ep["fault_h"] / ep["covered_h"].where(ep["covered_h"] > 0)
    ep["persistence"] = ratio.clip(0, 1).fillna(ep["n_samples"] / span)
    t = totals.set_index(["equipment_id", "rule_id"])
    var = (t["v_sq_mean"] - t["v_mean"] ** 2).clip(lower=0)
    std = np.sqrt(var).where(var > 0)
    idx = pd.MultiIndex.from_frame(ep[["equipment_id", "rule_id"]])
    ep["margin"] = ep["exceed_mean"].to_numpy() / std.reindex(idx).to_numpy()
    ep["threshold_survival"] = np.where(ep["n_exceed"] > 0, ep["n_survive"] / ep["n_exceed"].replace(0, np.nan), np.nan)
    ep["rule_on_share"] = (t["n_flagged"] / t["n_assessed"].replace(0, np.nan)).reindex(idx).to_numpy()
    fired = (totals.assign(f=totals["n_flagged"] > 0).groupby("rule_id")["f"].agg(["mean", "size"]))
    ep["peer_fire_share"] = ep["rule_id"].map(fired["mean"])
    ep["peer_equipment"] = ep["rule_id"].map(fired["size"])
    ep = ep.sort_values(["equipment_id", "rule_id", "start"]).reset_index(drop=True)
    ep.insert(0, "episode_id", [f"E{i + 1:06d}" for i in range(len(ep))])
    ep["co_rules"] = _co_rules(ep)
    return ep.drop(columns=["rn_min", "rn_max", "exceed_mean", "n_exceed", "n_survive"]), totals


def _co_rules(ep: pd.DataFrame) -> np.ndarray:
    """Distinct other rules with an overlapping episode on the same equipment."""
    out = np.zeros(len(ep))
    for _, g in ep.groupby("equipment_id"):
        if g["rule_id"].nunique() < 2:
            continue
        s = g["start"].to_numpy()
        e = g["end"].to_numpy()
        r = g["rule_id"].to_numpy()
        order = np.argsort(s)
        for pos, i in enumerate(order):
            seen = set()
            for j in order[pos + 1:]:
                if s[j] > e[i]:
                    break
                if r[j] != r[i]:
                    seen.add(r[j])
            for j in order[:pos][::-1]:
                if e[j] >= s[i] and r[j] != r[i]:
                    seen.add(r[j])
            out[g.index[i]] = len(seen)
    return out


# --------------------------------------------------------------------------- history evidence


def _robust_scale(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if x.size < 3:
        return float("nan")
    mad = float(np.median(np.abs(x - np.median(x)))) * 1.4826
    if mad > 0:
        return mad
    std = float(np.std(x))
    return std if std > 0 else float("nan")


def _is_status_point(values: np.ndarray, kind: Any) -> bool:
    if isinstance(kind, str) and kind.lower() in {"bool", "text", "status"}:
        return True
    v = values[np.isfinite(values)]
    return v.size > 0 and bool(np.all(np.isin(v, (0.0, 1.0))))


def history_evidence(h: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, cfg: ConfidenceConfig) -> dict[str, float]:
    """Data quality and abnormality of one equipment's points during an episode.

    Status points (bool kind or only 0/1 values) are excluded from stale and clipping evidence; a fan that stays on is
    healthy. Gap evidence compares in-episode readings with the point's expected cadence (``expected_interval_s`` or
    its own median spacing); event-based points with irregular spacing are skipped."""
    nan = float("nan")
    res = {"dq_stale": nan, "dq_gap": nan, "dq_clip": nan, "anomaly_share": nan, "history_points": 0.0}
    if h is None or h.empty:
        return res
    stale, gap, clip, anom = [], [], [], []
    dur_s = max((end - start).total_seconds(), 0.0)
    for _, s in h.groupby("point_id"):
        s = s.sort_values("ts")
        ts = s["ts"].to_numpy()
        vals = s["value"].to_numpy(float)
        inside = (s["ts"] >= start).to_numpy() & (s["ts"] <= end).to_numpy()
        vin, vout = vals[inside], vals[~inside]
        status = _is_status_point(vals, s["kind"].iloc[0] if "kind" in s.columns else None)
        # gaps against the expected cadence
        if ts.size >= 20:
            d = np.diff(ts).astype("timedelta64[ms]").astype(float) / 1000.0
            d = d[d > 0]
            if d.size:
                cadence = cfg.expected_interval_s or float(np.median(d))
                regular = cfg.expected_interval_s is not None or float(np.std(d) / max(np.mean(d), 1e-9)) <= 0.5
                if regular and cadence > 0:
                    expected = dur_s / cadence + 1.0
                    observed = float(np.isfinite(vin).sum())
                    gap.append(float(np.clip(1.0 - observed / expected, 0.0, 1.0)))
        if not status:
            fin = vin[np.isfinite(vin)]
            if fin.size >= cfg.stale_run:
                same = np.concatenate([[False], np.diff(fin) == 0])
                # a sample is stale when it sits in a run of at least stale_run identical readings
                run_id = np.cumsum(~same)
                run_len = np.bincount(run_id)[run_id]
                stale.append(float(np.mean(run_len >= cfg.stale_run)))
            full = vals[np.isfinite(vals)]
            if full.size > 10 and np.ptp(full) > 0 and fin.size:
                lo, hi = float(np.min(full)), float(np.max(full))
                edge_hi, edge_lo = np.mean(np.isclose(full, hi)), np.mean(np.isclose(full, lo))
                if max(edge_hi, edge_lo) > 0.02:
                    clip.append(float(np.mean(np.isclose(fin, lo) | np.isclose(fin, hi))))
        vin_f, vout_f = vin[np.isfinite(vin)], vout[np.isfinite(vout)]
        if vin_f.size and vout_f.size >= 10:
            scale = _robust_scale(vout_f)
            if math.isfinite(scale):
                anom.append(float(np.mean(np.abs(vin_f - np.median(vout_f)) / scale > cfg.anomaly_z)))
    res.update(
        dq_stale=float(np.mean(stale)) if stale else nan,
        dq_gap=float(np.mean(gap)) if gap else nan,
        dq_clip=float(np.mean(clip)) if clip else nan,
        anomaly_share=float(np.max(anom)) if anom else nan,
        history_points=float(h["point_id"].nunique()),
    )
    return res


def add_history_evidence(ep: pd.DataFrame, provider: HistoryProvider | None, cfg: ConfidenceConfig) -> pd.DataFrame:
    cols = ["dq_stale", "dq_gap", "dq_clip", "anomaly_share", "history_points"]
    out = ep.copy()
    for c in cols:
        out[c] = np.nan
    out["history_assessed"] = False
    if provider is None or ep.empty:
        return out
    pick = ep.sort_values("duration_h", ascending=False).head(cfg.max_history_episodes)
    pad = pd.Timedelta(hours=cfg.baseline_hours)
    for eq, g in pick.groupby("equipment_id"):
        h = provider(eq, g["start"].min() - pad, g["end"].max() + pad)
        for i, row in g.iterrows():
            if h is not None and not h.empty:
                win = h[(h["ts"] >= row["start"] - pad) & (h["ts"] <= row["end"] + pad)]
            else:
                win = h
            ev = history_evidence(win, row["start"], row["end"], cfg)
            for c in cols:
                out.at[i, c] = ev[c]
            out.at[i, "history_assessed"] = bool(ev["history_points"] > 0)
    return out


# --------------------------------------------------------------------------- scoring


def is_data_quality_rule(rule_id: Any, cfg: ConfidenceConfig) -> bool:
    rid = str(rule_id).upper()
    return any(rid.startswith(p.upper()) for p in cfg.data_quality_rules)


def _nz(x: Any, default: float = 0.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _score_row(r: dict[str, Any], cfg: ConfidenceConfig) -> dict[str, Any]:
    real, fp, tune = 0.0, -0.5, -0.5
    why_real: list[str] = []
    why_fp: list[str] = []
    why_tune: list[str] = []
    caveats: list[str] = []

    dq_parts = [r.get("dq_stale"), r.get("dq_gap"), r.get("dq_clip")]
    dq_assessed = any(_nz(x, -1.0) >= 0 for x in dq_parts)
    dq = max(_nz(x) for x in dq_parts)
    if r.get("data_quality_rule"):
        if dq_assessed and dq >= 0.5:
            real += 1.0 + 2.0 * dq
            why_real.append(f"data-quality rule confirmed by the inputs (stale/gap/clipped share {dq:.0%})")
        elif dq_assessed and dq < 0.1:
            tune += 1.0
            why_tune.append("data-quality rule fired but the inputs look clean")
        dq = 0.0
    if not dq_assessed:
        real -= 0.5
        caveats.append("input data quality not assessed (no history read for this episode)")
    if dq >= 0.5:
        fp += 3.0 * dq
        why_fp.append(f"input data quality is poor during the episode (stale/gap/clipped share {dq:.0%})")
    run = r.get("running_share")
    if run is not None and math.isfinite(_nz(run, float("nan"))) and run < 0.5:
        fp += 2.0 * (1 - run)
        why_fp.append(f"equipment proven running for only {run:.0%} of the episode")
    if _nz(r.get("n_samples"), 1) <= 2 and _nz(r.get("persistence"), 1) < 1.0:
        fp += 0.8
        why_fp.append("very short, intermittent episode")

    trust = 1.0 - dq
    pers = _nz(r.get("persistence"), 1.0)
    dur = _nz(r.get("duration_h"))
    real += trust * (1.0 * (pers - 0.5) + 0.6 * math.log1p(dur))
    if dur >= 1 and pers >= 0.8 and trust >= 0.5:
        why_real.append(f"persistent ({pers:.0%} of the time) for {dur:.1f} h")
    anom = _nz(r.get("anomaly_share"), float("nan"))
    if math.isfinite(anom):
        real += trust * (2.5 * anom) - 0.3
        if anom >= 0.2 and trust >= 0.5:
            why_real.append(f"inputs are statistically abnormal for {anom:.0%} of the episode")
    margin = _nz(r.get("margin"), float("nan"))
    if math.isfinite(margin):
        real += trust * 0.8 * min(margin, 3.0)
        if margin >= 1.0 and trust >= 0.5:
            why_real.append(f"exceeds the threshold by {margin:.1f} standard deviations on average")
    surv = _nz(r.get("threshold_survival"), float("nan"))
    if math.isfinite(surv):
        tune += 2.5 * (1 - surv)
        if surv < 0.5:
            why_tune.append(f"marginal: only {surv:.0%} of flagged samples survive a small threshold nudge")
    co = _nz(r.get("co_rules"))
    if co > 0:
        real += trust * 0.6 * min(co, 3)
        why_real.append(f"{int(co)} other rule(s) fault on the same equipment at the same time")
    peer = _nz(r.get("peer_fire_share"))
    npeer = int(_nz(r.get("peer_equipment"), 1))
    if npeer >= cfg.peer_min_equipment and peer >= cfg.peer_fire_share:
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
    """Add ``p_real``, ``p_false_positive``, ``p_tuning``, ``label`` and ``reason`` to each episode."""
    cfg = config or ConfidenceConfig()
    f = features.copy()
    f["data_quality_rule"] = f["rule_id"].map(lambda rid: is_data_quality_rule(rid, cfg)) if len(f) else []
    if f.empty:
        for c in ("p_real", "p_false_positive", "p_tuning", "label", "reason"):
            f[c] = []
        return f
    scored = pd.DataFrame([_score_row(r, cfg) for r in f.to_dict("records")], index=f.index)
    return pd.concat([f, scored], axis=1)


# --------------------------------------------------------------------------- roll-ups


def equipment_health(scored: pd.DataFrame, totals: pd.DataFrame) -> pd.DataFrame:
    """Per-equipment roll-up. Several distinct equipment rules with high ``p_real`` point at the equipment."""
    base = totals.groupby("equipment_id").agg(rules_evaluated=("rule_id", "nunique"))
    cols = ["episodes", "rules_faulting", "expected_real", "likely_real", "tuning_suggested", "likely_false_positive",
            "fault_hours_weighted", "rules_likely_real", "data_issues"]
    out = base.copy()
    for c in cols:
        out[c] = 0.0
    if not scored.empty:
        g = scored.groupby("equipment_id")
        lab = scored.pivot_table(index="equipment_id", columns="label", values="episode_id", aggfunc="count", fill_value=0)
        dq = scored["data_quality_rule"].astype(bool)
        agg = pd.DataFrame({
            "episodes": g.size(),
            "rules_faulting": g["rule_id"].nunique(),
            "expected_real": g["p_real"].sum().round(2),
            "fault_hours_weighted": (scored["duration_h"] * scored["p_real"]).groupby(scored["equipment_id"]).sum().round(2),
            "rules_likely_real": scored[(scored["label"] == "likely_real") & ~dq].groupby("equipment_id")["rule_id"].nunique(),
            "data_issues": scored[(scored["label"] == "likely_real") & dq].groupby("equipment_id")["rule_id"].nunique(),
        })
        for c in ("likely_real", "tuning_suggested", "likely_false_positive"):
            agg[c] = lab[c] if c in lab.columns else 0
        out.update(agg)
        out = out.fillna(0)
    for c in ("episodes", "rules_faulting", "likely_real", "tuning_suggested", "likely_false_positive", "rules_likely_real", "data_issues"):
        out[c] = out[c].astype(int)

    def verdict(r: pd.Series) -> str:
        if r["episodes"] == 0:
            return "ok"
        if r["rules_likely_real"] >= 2:
            return "equipment issue likely"
        if r["rules_likely_real"] == 1:
            return "check equipment"
        if r["data_issues"] > 0:
            return "sensor or data issue"
        if r["tuning_suggested"] > 0 and r["likely_real"] == 0:
            return "faults look like tuning"
        if r["likely_false_positive"] > 0:
            return "faults look like data or context"
        return "review"

    out["health"] = out.apply(verdict, axis=1)
    return out.reset_index().sort_values(["rules_likely_real", "expected_real", "episodes"], ascending=False).reset_index(drop=True)


def rule_summary(scored: pd.DataFrame, totals: pd.DataFrame, config: ConfidenceConfig | None = None) -> pd.DataFrame:
    """Per-rule peer comparison. A rule firing on most of its equipment is a threshold or applicability question."""
    cfg = config or ConfidenceConfig()
    base = totals.groupby("rule_id").agg(
        equipment_evaluated=("equipment_id", "nunique"), n_assessed=("n_assessed", "sum"), n_flagged=("n_flagged", "sum"),
        n_unassessed=("n_unassessed", "sum"), equipment_faulting=("n_flagged", lambda s: int((s > 0).sum())),
    )
    base["flagged_share"] = (base["n_flagged"] / base["n_assessed"].replace(0, np.nan)).fillna(0).round(3)
    base["fires_on_share"] = (base["equipment_faulting"] / base["equipment_evaluated"].replace(0, np.nan)).fillna(0).round(3)
    for c in ("episodes", "mean_p_real", "mean_p_tuning", "mean_p_false_positive"):
        base[c] = 0.0
    if not scored.empty:
        g = scored.groupby("rule_id")
        base.update(pd.DataFrame({
            "episodes": g.size(),
            "mean_p_real": g["p_real"].mean().round(3),
            "mean_p_tuning": g["p_tuning"].mean().round(3),
            "mean_p_false_positive": g["p_false_positive"].mean().round(3),
        }))
    base["episodes"] = base["episodes"].astype(int)
    wide = (base["fires_on_share"] >= cfg.peer_fire_share) & (base["equipment_evaluated"] >= cfg.peer_min_equipment)
    sugg = np.where((base["mean_p_tuning"] >= 0.45) | wide, "review threshold or applicability",
                    np.where(base["mean_p_real"] >= 0.5, "faults look real",
                             np.where(base["mean_p_false_positive"] >= 0.45, "faults look like data or context", "mixed")))
    base["suggestion"] = sugg
    dq_rule = base.index.to_series().map(lambda rid: is_data_quality_rule(rid, cfg))
    base.loc[dq_rule & (base["mean_p_real"] >= 0.5) & wide, "suggestion"] = (
        "data problem across equipment (check trending, polling or sensors)")
    base.loc[base["episodes"] == 0, "suggestion"] = "no faults"
    return base.reset_index().sort_values(["episodes", "rule_id"], ascending=[False, True]).reset_index(drop=True)


# --------------------------------------------------------------------------- entry points


def screen_sql(
    conn: Any,
    source: SourceMap | None = None,
    history: HistoryProvider | HistoryMap | None = None,
    config: ConfidenceConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Screen rule output that lives in a database. Returns ``episodes``, ``equipment`` and ``rules`` DataFrames."""
    _require_pandas()
    cfg = config or ConfidenceConfig()
    src = source or SourceMap()
    ep, totals = load_episodes(conn, src, cfg)
    provider = sql_history_provider(conn, history) if isinstance(history, HistoryMap) else history
    ep = add_history_evidence(ep, provider, cfg) if not ep.empty else ep
    scored = score_episodes(ep, cfg)
    return {"episodes": scored, "equipment": equipment_health(scored, totals), "rules": rule_summary(scored, totals, cfg)}


def screen(
    flags: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
    config: ConfidenceConfig | None = None,
    *,
    results: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Screen in-memory rule output: sample ``flags`` or Open-FDD ``results`` windows, plus optional long history."""
    _require_pandas()
    conn, src = frame_to_sqlite(flags=flags, results=results)
    try:
        provider = frame_history_provider(history) if history is not None and not history.empty else None
        return screen_sql(conn, src, provider, config)
    finally:
        conn.close()


def summarize(result: dict[str, pd.DataFrame]) -> dict[str, Any]:
    ep = result["episodes"]
    counts = ep["label"].value_counts().to_dict() if not ep.empty else {}
    rules = result["rules"]
    return {
        "episodes": len(ep),
        "labels": {k: int(counts.get(k, 0)) for k in LABELS},
        "equipment_flagged": int((result["equipment"]["episodes"] > 0).sum()) if not result["equipment"].empty else 0,
        "rules_to_review": rules.loc[rules["suggestion"] == "review threshold or applicability", "rule_id"].tolist(),
        "note": "Advisory heuristic scores; no rule, tuner or stored result was changed.",
    }


# --------------------------------------------------------------------------- CLI


def _kv(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--map expects NAME=COLUMN, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def add_arguments(ap: argparse.ArgumentParser) -> None:
    src = ap.add_argument_group("rule output (pick one)")
    src.add_argument("--flags", help="CSV of sample flags: timestamp, equipment_id, rule_id, flag [, value, threshold, running]")
    src.add_argument("--results", help="CSV of Open-FDD rule_result rows (equipment_id, rule_id, window_start, window_end, status, ...)")
    src.add_argument("--sqlite", help="SQLite database file")
    src.add_argument("--duckdb", help="DuckDB database file (pip install duckdb)")
    src.add_argument("--postgres", action="store_true",
                     help="PostgreSQL/TimescaleDB; DSN from OPENFDD_CONFIDENCE_DSN (use read-only credentials; pip install psycopg)")
    db = ap.add_argument_group("database schema")
    db.add_argument("--layout", choices=("results", "flags"), default="results")
    db.add_argument("--table", help="rule output table (default fdd.rule_result, or rule_result on SQLite)")
    db.add_argument("--map", action="append", metavar="NAME=COLUMN", help="rename a column, e.g. --map equipment_id=equip")
    db.add_argument("--fault-status", default="FAULT", help="comma list of status values meaning fault")
    db.add_argument("--pass-status", default="PASS", help="comma list of status values meaning pass")
    db.add_argument("--site", help="only this site_id")
    db.add_argument("--since", help="only rows at or after this ISO timestamp")
    db.add_argument("--until", help="only rows before this ISO timestamp")
    db.add_argument("--history-table", help="SI history table (default fdd.input_sample, or input_sample on SQLite)")
    db.add_argument("--point-table", help="point table joined for equipment_id (default fdd.point); '' when history has equipment_id")
    db.add_argument("--history-map", action="append", metavar="NAME=COLUMN", help="rename a history column (ts, point_key, value, ...)")
    db.add_argument("--no-history", action="store_true", help="skip point-history evidence")
    ap.add_argument("--history", help="CSV of long SI history: timestamp, equipment_id, point_id, value (with --flags/--results)")
    ap.add_argument("--labels", help="CSV of reviewed verdicts (equipment_id, start_ts, end_ts, label [, rule_id]) to calibrate the scores")
    ap.add_argument("--data-quality-rules", default="", help="comma list of rule-id prefixes that are sensor/data validation rules")
    ap.add_argument("--gap-samples", type=int, default=ConfidenceConfig.gap_samples)
    ap.add_argument("--sensitivity-frac", type=float, default=ConfidenceConfig.sensitivity_frac)
    ap.add_argument("--max-history-episodes", type=int, default=ConfidenceConfig.max_history_episodes)
    ap.add_argument("--top", type=int, default=10, help="items per section in the triage report")
    ap.add_argument("--out-dir", default="confidence_out", help="writes episodes.csv, equipment.csv, rules.csv, report.json, report.md")
    ap.add_argument("--print", dest="print_format", choices=("json", "md", "none"), default="json", help="what to print to stdout")


def _connect(args: argparse.Namespace) -> tuple[Any, str]:
    if args.sqlite:
        if not Path(args.sqlite).is_file():
            raise FileNotFoundError(f"no SQLite database at {args.sqlite}")
        return sqlite3.connect(f"file:{Path(args.sqlite).as_posix()}?mode=ro", uri=True), "sqlite"
    if args.duckdb:
        import duckdb

        if not Path(args.duckdb).is_file():
            raise FileNotFoundError(f"no DuckDB database at {args.duckdb}")

        return duckdb.connect(args.duckdb, read_only=True), "duckdb"
    if args.postgres:
        import psycopg

        dsn = os.environ.get("OPENFDD_CONFIDENCE_DSN")
        if not dsn:
            raise ValueError("set OPENFDD_CONFIDENCE_DSN to a read-only PostgreSQL connection string")
        conn = psycopg.connect(dsn)
        conn.read_only = True
        return conn, "postgres"
    raise ValueError("pick one of --flags, --results, --sqlite, --duckdb, --postgres")


def run_cli(args: argparse.Namespace) -> int:
    _require_pandas()
    from open_fdd.ml.confidence_report import build_report, to_markdown

    dq_rules = tuple(p.strip() for p in (args.data_quality_rules or "").split(",") if p.strip())
    cfg = ConfidenceConfig(gap_samples=args.gap_samples, sensitivity_frac=args.sensitivity_frac,
                           data_quality_rules=dq_rules, max_history_episodes=args.max_history_episodes)
    if args.flags or args.results:
        history = pd.read_csv(args.history) if args.history else None
        if args.flags:
            result = screen(pd.read_csv(args.flags), history, cfg)
        else:
            result = screen(history=history, config=cfg, results=pd.read_csv(args.results))
        source_desc = {"input": "csv", "layout": "flags" if args.flags else "results"}
    else:
        conn, engine = _connect(args)
        try:
            schema = "" if engine == "sqlite" else "fdd."
            default_table = f"{schema}rule_result" if args.layout == "results" else "fault_flags"
            src = SourceMap(
                layout=args.layout, table=args.table or default_table, columns=_kv(args.map),
                fault_status=tuple(s.strip() for s in args.fault_status.split(",") if s.strip()),
                pass_status=tuple(s.strip() for s in args.pass_status.split(",") if s.strip()),
                site_id=args.site, since=args.since, until=args.until,
            )
            hm = None
            if not args.no_history:
                hm = HistoryMap(
                    table=args.history_table or f"{schema}input_sample",
                    point_table=args.point_table if args.point_table is not None else f"{schema}point",
                    columns=_kv(args.history_map),
                )
            result = screen_sql(conn, src, hm, cfg)
        finally:
            conn.close()
        source_desc = {"input": engine, "layout": args.layout, "table": src.table}
    calibration = None
    if args.labels:
        from open_fdd.ml.confidence_calibrate import calibrate

        result["episodes"], calibration = calibrate(result["episodes"], pd.read_csv(args.labels))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in result.items():
        df.to_csv(out / f"{name}.csv", index=False)
    report = build_report(result, top=args.top, config=cfg, source=source_desc, calibration=calibration)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    md = to_markdown(report)
    (out / "report.md").write_text(md, encoding="utf-8")
    if args.print_format == "json":
        print(json.dumps(report, default=str))
    elif args.print_format == "md":
        print(md)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="open-fdd-ml confidence", description=DESCRIPTION)
    add_arguments(ap)
    return run_cli(ap.parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
