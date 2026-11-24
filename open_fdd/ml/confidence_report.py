"""Compact triage report from a fault-confidence screen: JSON for agents, Markdown for people.

The report answers five questions in order: which faults are most likely real, which false-positive patterns repeat,
which rules deserve a threshold or applicability review, which equipment is least healthy, and what a person should
check next. It is advisory; it never proposes tuner values.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from open_fdd.ml.confidence import LABELS, ConfidenceConfig

REPORT_VERSION = 1


def _ts(x: Any) -> str | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    return pd.Timestamp(x).strftime("%Y-%m-%dT%H:%MZ")


def _episode(r: pd.Series) -> dict[str, Any]:
    out = {
        "episode_id": r["episode_id"], "equipment_id": r["equipment_id"], "rule_id": r["rule_id"],
        "start": _ts(r["start"]), "end": _ts(r["end"]), "duration_h": round(float(r["duration_h"]), 2),
        "p_real": r["p_real"], "p_false_positive": r["p_false_positive"], "p_tuning": r["p_tuning"],
        "label": r["label"], "reason": r["reason"],
    }
    if r.get("subject"):
        out["subject"] = r["subject"]
    return out


def _fp_pattern(reason: str) -> str:
    text = reason.lower()
    if "data quality is poor" in text:
        return "poor input data (stale, gaps or clipping)"
    if "proven running" in text:
        return "equipment not running"
    if "short, intermittent" in text:
        return "short intermittent blips"
    return "other"


def build_report(result: dict[str, pd.DataFrame], *, top: int = 10, config: ConfidenceConfig | None = None,
                 source: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or ConfidenceConfig()
    ep, eq, rules = result["episodes"], result["equipment"], result["rules"]
    counts = ep["label"].value_counts().to_dict() if not ep.empty else {}
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "advisory": "Heuristic evidence scores, not calibrated probabilities. Nothing was tuned or changed.",
        "source": source or {},
        "window": {"start": _ts(ep["start"].min()) if not ep.empty else None,
                   "end": _ts(ep["end"].max()) if not ep.empty else None},
        "totals": {
            "episodes": len(ep),
            "equipment_with_faults": int((eq["episodes"] > 0).sum()) if not eq.empty else 0,
            "equipment_evaluated": len(eq),
            "rules_evaluated": len(rules),
            "labels": {k: int(counts.get(k, 0)) for k in LABELS},
            "history_assessed_episodes": int(ep["history_assessed"].sum()) if "history_assessed" in ep.columns else 0,
        },
        "likely_real": [], "false_positive_patterns": [], "rules_to_review": [], "equipment_ranking": [], "next_checks": [],
    }
    if not ep.empty:
        real = ep[ep["label"] == "likely_real"].sort_values(["p_real", "duration_h"], ascending=False)
        equip_real = real[~real["data_quality_rule"].astype(bool)]
        report["likely_real"] = [_episode(r) for _, r in equip_real.head(top).iterrows()]
        data_real = real[real["data_quality_rule"].astype(bool)]
        if not data_real.empty:
            report["confirmed_data_issues"] = [_episode(r) for _, r in data_real.head(top).iterrows()]
        fp = ep[ep["label"] == "likely_false_positive"].copy()
        if not fp.empty:
            fp["pattern"] = fp["reason"].map(_fp_pattern)
            grp = fp.groupby(["rule_id", "pattern"]).agg(episodes=("episode_id", "size"), equipment=("equipment_id", "nunique"),
                                                         hours=("duration_h", "sum")).reset_index()
            grp = grp.sort_values(["episodes", "hours"], ascending=False).head(top)
            report["false_positive_patterns"] = [
                {"rule_id": r.rule_id, "pattern": r.pattern, "episodes": int(r.episodes), "equipment": int(r.equipment),
                 "hours": round(float(r.hours), 1)} for r in grp.itertuples()]
    rv = rules[rules["suggestion"].isin(["review threshold or applicability",
                                         "data problem across equipment (check trending, polling or sensors)"])]
    report["rules_to_review"] = [
        {"rule_id": r.rule_id, "suggestion": r.suggestion, "fires_on_share": float(r.fires_on_share),
         "equipment_evaluated": int(r.equipment_evaluated), "episodes": int(r.episodes),
         "mean_p_tuning": float(r.mean_p_tuning)} for r in rv.head(top).itertuples()]
    bad = eq[eq["episodes"] > 0].head(top)
    report["equipment_ranking"] = [
        {"equipment_id": r.equipment_id, "health": r.health, "rules_likely_real": int(r.rules_likely_real),
         "data_issues": int(r.data_issues), "episodes": int(r.episodes), "expected_real": float(r.expected_real)}
        for r in bad.itertuples()]
    report["next_checks"] = next_checks(report)
    report["config"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()}
    return report


def next_checks(report: dict[str, Any]) -> list[str]:
    checks: list[str] = []
    for e in report["equipment_ranking"]:
        if e["health"] == "equipment issue likely":
            checks.append(f"Inspect {e['equipment_id']}: {e['rules_likely_real']} independent rules show likely-real faults.")
    for e in report.get("likely_real", [])[:3]:
        checks.append(f"Confirm {e['rule_id']} on {e['equipment_id']} ({e['start']} to {e['end']}): {e['reason']}.")
    if report.get("confirmed_data_issues"):
        n = len({e["equipment_id"] for e in report["confirmed_data_issues"]})
        checks.append(f"Fix sensor or trend data on {n} equipment before trusting their other fault results.")
    for p in report["false_positive_patterns"][:3]:
        checks.append(f"{p['rule_id']}: {p['episodes']} episodes look like {p['pattern']}; check that before acting on them.")
    for r in report["rules_to_review"][:3]:
        checks.append(f"{r['rule_id']}: {r['suggestion']} (fires on {r['fires_on_share']:.0%} of "
                      f"{r['equipment_evaluated']} equipment). Review with the engineer; no change was made.")
    if not checks:
        checks.append("No faults need attention in this window.")
    return checks[:10]


def to_markdown(report: dict[str, Any]) -> str:
    t = report["totals"]
    lab = t["labels"]
    lines = [
        "# Fault triage",
        "",
        (f"{t['episodes']} fault episodes on {t['equipment_with_faults']} of {t['equipment_evaluated']} equipment "
         f"({report['window']['start']} to {report['window']['end']}): {lab['likely_real']} likely real, "
         f"{lab['likely_false_positive']} likely false positive, {lab['tuning_suggested']} rule review suggested, "
         f"{lab['uncertain']} uncertain."),
        "",
        "## Check next",
        "",
        *[f"{i}. {c}" for i, c in enumerate(report["next_checks"], 1)],
    ]

    def table(title: str, rows: list[dict[str, Any]], cols: list[str]) -> None:
        if not rows:
            return
        lines.extend(["", f"## {title}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)])
        for r in rows:
            lines.append("| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in cols) + " |")

    table("Likely real faults", report["likely_real"], ["equipment_id", "rule_id", "start", "duration_h", "p_real", "reason"])
    table("Confirmed data issues", report.get("confirmed_data_issues", []), ["equipment_id", "rule_id", "start", "p_real"])
    table("False-positive patterns", report["false_positive_patterns"], ["rule_id", "pattern", "episodes", "equipment", "hours"])
    table("Rules to review", report["rules_to_review"], ["rule_id", "suggestion", "fires_on_share", "equipment_evaluated"])
    table("Equipment health", report["equipment_ranking"], ["equipment_id", "health", "rules_likely_real", "data_issues", "episodes"])
    lines.extend(["", f"_{report['advisory']}_", ""])
    return "\n".join(lines)
