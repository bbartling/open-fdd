"""Rule scorecard core: load results + labels, run scorecard.sql, compute precision / recall / FPR.

Precision of a rule is the share of its FAULT windows that a label confirms; ``1 - precision`` is the
false-positive share, i.e. an estimate of the probability that the next FAULT from this rule is a false alarm.
A prior scorecard (for example one computed on the LBNL labeled data) can be blended in as a Beta prior, so a
site starts from the public-data estimate and moves toward its own confirmed labels as verdicts accumulate.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SQL_PATH = Path(__file__).with_name("scorecard.sql")

RESULT_FIELDS = ("equipment_id", "rule_id", "window_start", "window_end", "status")
LABEL_FIELDS = ("equipment_id", "start_ts", "end_ts", "label", "rule_id", "fault_type", "source")


@dataclass
class Config:
    """Column names in YOUR tables / CSVs, mapped to the scorecard's names. Nothing site-specific is built in."""

    results: dict[str, str] = field(default_factory=lambda: {f: f for f in RESULT_FIELDS})
    labels: dict[str, str] = field(default_factory=lambda: {f: f for f in LABEL_FIELDS})
    # Your status values -> FAULT / PASS; anything not listed is "not assessed".
    status_map: dict[str, str] = field(default_factory=lambda: {"FAULT": "FAULT", "PASS": "PASS"})
    # Your label values -> fault / normal.
    label_map: dict[str, str] = field(default_factory=lambda: {
        "fault": "fault", "normal": "normal", "confirmed": "fault", "false_positive": "normal"})
    naive_timezone: str = "UTC"  # timestamps without an offset are read as UTC


def load_config(path: str | Path | None) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = set(raw) - {"results", "labels", "status_map", "label_map", "naive_timezone"}
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    for key in ("results", "labels"):
        if key in raw:
            getattr(cfg, key).update(raw[key])
    for key in ("status_map", "label_map"):
        if key in raw:
            setattr(cfg, key, dict(raw[key]))
    if raw.get("naive_timezone", "UTC") != "UTC":
        raise ValueError("naive_timezone: only UTC is supported; export timestamps with an offset")
    return cfg


def _ts(value: Any) -> str:
    """Any ISO-8601 timestamp -> canonical UTC text that sorts and compares correctly in SQLite."""
    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text.replace(" ", "T", 1) if "T" not in text else text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _hours(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600.0


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _pick(row: dict[str, Any], column: str, *, required: bool, what: str) -> Any:
    if column in row:
        value = row[column]
        return None if value in ("", None) else value
    if required:
        raise KeyError(f"{what}: column {column!r} not found (have {sorted(row)}); map it in the config")
    return None


def _load(conn: sqlite3.Connection, results: Iterable[dict], labels: Iterable[dict], cfg: Config) -> dict[str, int]:
    conn.execute("CREATE TABLE scorecard_results (equipment_id TEXT, rule_id TEXT, window_start TEXT,"
                 " window_end TEXT, status TEXT)")
    conn.execute("CREATE TABLE scorecard_labels (equipment_id TEXT, start_ts TEXT, end_ts TEXT, label TEXT,"
                 " rule_id TEXT, fault_type TEXT, source TEXT)")
    n_res = n_lab = 0
    rows = []
    for row in results:
        rc = cfg.results
        raw_status = str(_pick(row, rc["status"], required=True, what="results") or "")
        rows.append((
            str(_pick(row, rc["equipment_id"], required=True, what="results")),
            str(_pick(row, rc["rule_id"], required=True, what="results")),
            _ts(_pick(row, rc["window_start"], required=True, what="results")),
            _ts(_pick(row, rc["window_end"], required=True, what="results")),
            cfg.status_map.get(raw_status, cfg.status_map.get(raw_status.upper(), "NA")),
        ))
        n_res += 1
    conn.executemany("INSERT INTO scorecard_results VALUES (?,?,?,?,?)", rows)
    rows = []
    for row in labels:
        lc = cfg.labels
        raw_label = str(_pick(row, lc["label"], required=True, what="labels") or "").strip()
        if not raw_label:  # an unfilled verdict-template row: not reviewed yet
            continue
        label = cfg.label_map.get(raw_label, cfg.label_map.get(raw_label.lower()))
        if label not in ("fault", "normal"):
            raise ValueError(f"labels: value {raw_label!r} is not mapped to fault/normal (set label_map)")
        start, end = (_ts(_pick(row, lc["start_ts"], required=True, what="labels")),
                      _ts(_pick(row, lc["end_ts"], required=True, what="labels")))
        if end <= start:
            raise ValueError(f"labels: end_ts {end} is not after start_ts {start}")
        rule = _pick(row, lc["rule_id"], required=False, what="labels")
        rows.append((str(_pick(row, lc["equipment_id"], required=True, what="labels")), start, end, label,
                     None if rule is None else str(rule),
                     _pick(row, lc["fault_type"], required=False, what="labels"),
                     _pick(row, lc["source"], required=False, what="labels")))
        n_lab += 1
    conn.executemany("INSERT INTO scorecard_labels VALUES (?,?,?,?,?,?,?)", rows)
    return {"results": n_res, "labels": n_lab}


def wilson_interval(k: int, n: int, z: float = 1.959964) -> tuple[float | None, float | None]:
    """95 % Wilson score interval for a proportion k/n; (None, None) when n == 0."""
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def _lead_times(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Per rule: hours from each fault label's start to the first FAULT window overlapping it (detection delay)."""
    q = """
    SELECT r.rule_id, l.equipment_id, l.start_ts, MIN(r.window_start) AS first_fault
    FROM scorecard_labels l
    JOIN scorecard_results r
      ON r.equipment_id = l.equipment_id AND l.start_ts < r.window_end AND l.end_ts > r.window_start
     AND r.status = 'FAULT' AND (l.rule_id IS NULL OR l.rule_id = r.rule_id)
    WHERE l.label = 'fault'
    GROUP BY r.rule_id, l.equipment_id, l.start_ts
    """
    out: dict[str, list[float]] = {}
    for rule, _eq, start, first in conn.execute(q):
        out.setdefault(rule, []).append(max(0.0, _hours(start, first)))
    stats = {}
    for rule, vals in out.items():
        vals.sort()
        mid = len(vals) // 2
        median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        stats[rule] = {"detected_labels": len(vals), "lead_time_h_median": median, "lead_time_h_max": vals[-1]}
    return stats


def score(results: Iterable[dict], labels: Iterable[dict], cfg: Config | None = None, *,
          prior: dict[str, Any] | None = None, prior_weight: float = 20.0) -> dict[str, Any]:
    """Score rule results against labels. Returns {"rules": [...], "review_queue": [...], "counts": {...}}.

    ``prior``: a previous scorecard (e.g. on LBNL data). Its per-rule precision becomes a Beta prior worth
    ``prior_weight`` pseudo-verdicts: posterior precision = (TP + w * p0) / (TP + FP + w).
    """
    cfg = cfg or Config()
    conn = sqlite3.connect(":memory:")
    counts = _load(conn, results, labels, cfg)
    sql = SQL_PATH.read_text(encoding="utf-8")
    cur = conn.execute(sql)
    cols = [c[0] for c in cur.description]
    prior_by_rule = {r["rule_id"]: r for r in (prior or {}).get("rules", [])}
    leads = _lead_times(conn)
    rules = []
    for values in cur.fetchall():
        row = dict(zip(cols, values))
        tp, fp, fn, tn = row["tp"], row["fp"], row["fn"], row["tn"]
        lo, hi = wilson_interval(tp, tp + fp)
        p0 = prior_by_rule.get(row["rule_id"], {}).get("precision")
        posterior = None
        if p0 is not None and prior_weight > 0:
            posterior = (tp + prior_weight * p0) / (tp + fp + prior_weight)
        elif tp + fp:
            posterior = tp / (tp + fp)
        row.update({
            "precision": _ratio(tp, tp + fp),
            "precision_ci95": [lo, hi],
            "recall": _ratio(tp, tp + fn),
            "fpr": _ratio(fp, fp + tn),
            "false_positive_share": _ratio(fp, tp + fp),
            "prior_precision": p0,
            "p_true_fault": posterior,  # probability the next FAULT from this rule is real
            **leads.get(row["rule_id"], {"detected_labels": 0, "lead_time_h_median": None, "lead_time_h_max": None}),
        })
        rules.append(row)
    p_by_rule = {r["rule_id"]: r["p_true_fault"] for r in rules}
    queue = [
        {"equipment_id": e, "rule_id": r, "window_start": s, "window_end": w, "p_true_fault": p_by_rule.get(r)}
        for e, r, s, w in conn.execute("""
            SELECT r.equipment_id, r.rule_id, r.window_start, r.window_end
            FROM scorecard_results r
            WHERE r.status = 'FAULT' AND NOT EXISTS (
              SELECT 1 FROM scorecard_labels l
              WHERE l.equipment_id = r.equipment_id AND l.start_ts < r.window_end AND l.end_ts > r.window_start
                AND (l.rule_id IS NULL OR l.rule_id = r.rule_id))
            ORDER BY r.window_start, r.equipment_id, r.rule_id""")
    ]
    conn.close()
    return {"counts": counts, "prior_weight": prior_weight if prior else None, "rules": rules,
            "review_queue": queue}


def to_markdown(card: dict[str, Any]) -> str:
    def f(v, pct=True):
        if v is None:
            return "—"
        return f"{100 * v:.1f} %" if pct else f"{v:.1f}"
    header = ("| Rule | TP | FP | FN | TN | Not assessed | Unlabeled | Precision (95 % CI) | Recall | FPR |"
              " P(true fault) | Median lead h |")
    lines = [header, "|---|" + "---|" * 11]
    for r in card["rules"]:
        lo, hi = r["precision_ci95"]
        ci = f"{f(r['precision'])} ({f(lo)}–{f(hi)})" if r["precision"] is not None else "—"
        lines.append(f"| {r['rule_id']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | {r['not_assessed']} |"
                     f" {r['unlabeled']} | {ci} | {f(r['recall'])} | {f(r['fpr'])} | {f(r['p_true_fault'])} |"
                     f" {f(r['lead_time_h_median'], pct=False)} |")
    lines.append("")
    lines.append(f"Unlabeled FAULT windows waiting for a verdict: {len(card['review_queue'])}")
    return "\n".join(lines) + "\n"
