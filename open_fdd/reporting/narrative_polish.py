"""Turn rule facts into report English before Typst is written.

Rule engines keep structured outcomes. This module is the only place that
builds the sensor, anomaly, and executive paragraphs an operator reads.
"""

from __future__ import annotations

from typing import Any


def _join_names(labels: list[str]) -> str:
    names = list(dict.fromkeys(label for label in labels if label))
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _lead(labels: list[str]) -> str:
    text = _join_names(labels)
    if not text:
        return ""
    lowered = text.lower()
    return lowered[0].upper() + lowered[1:]


def _labels(rows: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for row in rows:
        for label in row.get("labels") or []:
            found.append(str(label))
    return found


def polish_sensor_paragraph(checks: list[dict[str, Any]]) -> str:
    """One paragraph. Failed checks only, grouped by the kind of sensor problem."""
    if not checks:
        return "Sensor checks passed. No stuck sensors, out-of-range readings, or stale data."
    if all(row.get("outcome") == "skipped" for row in checks):
        return "Sensor checks were skipped because no mapped sensors were available to review."
    fails = [row for row in checks if row.get("outcome") == "fail"]
    if not fails:
        return "Sensor checks passed. No stuck sensors, out-of-range readings, or stale data."

    by_rule: dict[str, list[dict[str, Any]]] = {}
    for row in fails:
        by_rule.setdefault(str(row.get("rule_id") or ""), []).append(row)

    sentences: list[str] = []
    for row in by_rule.get("SV-RANGE") or []:
        for label in row.get("labels") or []:
            low = row.get("low")
            high = row.get("high")
            if low is not None and high is not None:
                sentences.append(
                    f"{_lead([str(label)])} read outside its physical range (low {low}, high {high})."
                )
            else:
                sentences.append(f"{_lead([str(label)])} read outside its physical range.")

    stuck = _labels(by_rule.get("SV-FLATLINE") or [])
    if stuck:
        sentences.append(f"{_lead(stuck)} stayed stuck flat.")
    stale = _labels(by_rule.get("SV-STALE") or [])
    if stale:
        sentences.append(f"{_lead(stale)} stopped updating.")

    spike = set(_labels(by_rule.get("SV-SPIKE") or []))
    rate = set(_labels(by_rule.get("SV-RATE") or []))
    both = [label for label in _labels(by_rule.get("SV-SPIKE") or []) if label in rate]
    if both:
        sentences.append(f"{_lead(both)} jumped suddenly and changed faster than expected.")
    only_spike = [label for label in spike if label not in rate]
    if only_spike:
        sentences.append(f"{_lead(only_spike)} jumped suddenly.")
    only_rate = [label for label in rate if label not in spike]
    if only_rate:
        sentences.append(f"{_lead(only_rate)} changed faster than expected.")

    known = {"SV-RANGE", "SV-FLATLINE", "SV-STALE", "SV-SPIKE", "SV-RATE"}
    for rule_id, rows in by_rule.items():
        if rule_id in known:
            continue
        names = _join_names(_labels(rows))
        if names:
            sentences.append(f"{_lead(_labels(rows))} failed a sensor check.")
    if not sentences:
        return "Sensor checks found problems on the mapped sensors."
    return " ".join(sentences)


def polish_anomaly_paragraph(rows: list[dict[str, Any]]) -> str:
    """Short paragraph. All-normal trends collapse to one sentence."""
    if not rows:
        return "Anomaly screening was skipped because the mapped points do not vary enough."
    if len(rows) == 1 and rows[0].get("outcome") == "skipped" and not rows[0].get("labels"):
        text = str(rows[0].get("text") or "")
        if "fan-on" in text:
            return "Anomaly screening was skipped because there was not enough fan-on data."
        return "Anomaly screening was skipped because the mapped points do not vary enough."

    normal = _labels([row for row in rows if row.get("outcome") == "looks_normal"])
    needs = [row for row in rows if row.get("outcome") == "needs_a_look"]
    skipped = _labels([row for row in rows if row.get("outcome") == "skipped"])
    sentences: list[str] = []
    if normal and not needs and not skipped:
        return f"{_lead(normal)} look normal."
    if normal:
        sentences.append(f"{_lead(normal)} look normal.")
    for row in needs:
        label = (_labels([row]) or ["A trend"])[0]
        detail = str(row.get("detail") or "").strip()
        if detail:
            sentences.append(f"{label} needs a look. {detail}")
        else:
            sentences.append(f"{label} needs a look.")
    if skipped:
        sentences.append(f"{_lead(skipped)} did not have enough fan-on data to screen.")
    return " ".join(sentences)


def polish_executive_summary(
    *,
    label: str,
    month_phrase: str,
    sample_count: int,
    span_h: str,
    sensor_paragraph: str,
    anomaly_paragraph: str,
    anomaly_note: str,
    faults: list[dict[str, Any]],
    web_source: str | None,
    fan_on_percent: str | None,
) -> str:
    """Opening paragraph for an operator. Facts only, in sentence form."""
    parts = [
        f"{label} in {month_phrase} ({sample_count} samples, {span_h} h).",
        f"Sensor checks: {sensor_paragraph}",
        f"Anomaly screening: {anomaly_paragraph}",
        anomaly_note,
    ]
    if faults:
        bits = []
        for row in faults:
            title = str(row.get("title") or row.get("rule_id") or "Finding")
            hours = row.get("fault_hours")
            bits.append(f"{title} for {hours} h")
        parts.append("Confirmed operating findings: " + "; ".join(bits) + ".")
    else:
        parts.append("No confirmed operating faults in this month.")
    if web_source:
        parts.append(f"Web outdoor air temperature was included from {web_source}.")
    if fan_on_percent is not None:
        parts.append(f"The fan was on for {fan_on_percent} percent of the samples.")
    return " ".join(parts)
