#!/usr/bin/env python3
"""MQTTS continuity blame: edge vs internet hop vs Railway vs sparse PV.

Diagnostics only. Does not filter MQTT publishes and does not hard-code a
building id into product DataFusion. Stress/ops may pass the ACME lab building
and known fixture equipment ids when the data-model list is empty.

Window length defaults to OPENFDD_DIGEST_REPORT_HOURS, then
OPENFDD_GAP_WINDOW_HOURS, then 24 hours. Poll cadence default is the fixed
fieldbus interval (300s).

Layers
------
EDGE
    Field edge did not poll or did not hand the packet to the broker.
TRANSIT
    Edge attempted a publish and did not get a broker ack, and Railway mqtt
    ingress is quiet. That is the internet hop (or a broker that never saw
    the packet).
RAILWAY
    The broker acked the publisher, or central's mqtt monitor saw the
    message, but ingest / historian parquet is missing or gapped.
SPARSE_OK
    Edge and cloud agree the series is present and the PV did not change, or
    they agree the point was not published (heartbeat / poll success, value
    unchanged or outside the health-role subset). Full-snapshot fieldbus
    still publishes unchanged PVs every cycle; a flat trace with timestamps
    is not loss. A missing timestamp after a successful publish is never
    SPARSE_OK.
INCONCLUSIVE
    A layer probe is missing. The reason names the probe.

QoS 1 publish ack means the Railway broker accepted the packet. Ack without
central ingest is Railway (subscriber / persist), not the internet hop.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

LOSS = frozenset({"EDGE", "TRANSIT", "RAILWAY"})
BLAME_ORDER = ("EDGE", "TRANSIT", "RAILWAY", "SPARSE_OK", "INCONCLUSIVE", "OK")

AHU_TYPES = frozenset({"ahu", "cv ahu", "vav ahu", "erv"})
VAV_TYPES = frozenset({"vav"})
AHU_RAW = frozenset(
    {"ahu", "rtu", "cv ahu", "cvahu", "vav ahu", "vavahu", "unit ventilator", "uv", "erv"}
)

EDGE_PROBE = (
    "fieldbus publish ledger from the ACME edge "
    "(GET /api/mqtt/publish-ledger: publish_acks, publish_fails, "
    "publish_no_session, recent[].equipment_ids). "
    "/bacnet/poll/status is the current poll only and is not a 24h publish journal."
)
TRANSIT_PROBE = (
    "mqtt ingress timestamps covering the window. "
    "Central GET /api/mqtt/monitor keeps about 100 messages (not a 24h per-IO ledger) "
    "and GET /api/ingest/stats is a since-boot total."
)
RAILWAY_PROBE = (
    "windowed historian gap aggregate per equipment role "
    "(sample count, max_gap_secs, value_changes). "
    "POST /api/analytics/inspect downsamples the full hive; "
    "use it only when in-window median spacing stays near the poll interval."
)

NEXT_ACTION = {
    "EDGE": (
        "On the field edge: BACnet poll errors, MQTT session down "
        "(publish_no_session), or publish failures before a broker ack."
    ),
    "TRANSIT": (
        "Edge publish did not get a broker ack and Railway mqtt ingress is quiet. "
        "Check the path from the field edge to the Railway mqtt broker."
    ),
    "RAILWAY": (
        "Broker ack or central mqtt monitor shows the message, but ingest/historian "
        "does not. Check ingest_reject historian_persist, the central subscriber, "
        "and parquet flush."
    ),
    "SPARSE_OK": (
        "No loss. Unchanged PV with heartbeats, or a point the edge did not publish "
        "(health-role subset). Do not treat a flat actuator as a gap."
    ),
    "INCONCLUSIVE": "Collect the missing probe named on this row, then rerun.",
    "OK": "No gap in the evidence that is present.",
}


def window_hours_from_env() -> float:
    for key in ("OPENFDD_DIGEST_REPORT_HOURS", "OPENFDD_GAP_WINDOW_HOURS"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return 24.0


def expected_samples(window_hours: float, interval_secs: float) -> int:
    if interval_secs <= 0:
        return 0
    return max(1, int(round((window_hours * 3600.0) / interval_secs)))


def _norm_type(label: str) -> str:
    return " ".join(label.lower().replace("_", " ").replace("-", " ").split())


def select_samples(
    rows: list[dict[str, Any]],
    *,
    prefer_ids: tuple[str, ...] = ("RTU_01",),
    fixture_ids: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Pick one air handler and one VAV by equipment_type.

    Exact fixture ids are used only when type selection finds nothing and that
    id is present on the inventory. This does not SQL-filter by name pattern.
    """
    typed: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or row.get("id") or "").strip()
        if not eid:
            continue
        kind = _norm_type(str(row.get("equipment_type") or ""))
        raw = _norm_type(str(row.get("equipment_type_raw") or ""))
        typed.append({"equipment_id": eid, "equipment_type": kind or raw, "raw": raw, "kind": kind})

    def is_ahu(item: dict[str, str]) -> bool:
        return item["kind"] in AHU_TYPES or item["raw"] in AHU_RAW

    def is_vav(item: dict[str, str]) -> bool:
        return item["kind"] in VAV_TYPES or item["raw"] in VAV_TYPES or item["raw"] == "vav"

    def prefer(group: list[dict[str, str]], ids: tuple[str, ...]) -> dict[str, str] | None:
        for pid in ids:
            for item in group:
                if item["equipment_id"] == pid:
                    return item
        return group[0] if group else None

    chosen: list[dict[str, str]] = []
    ahu = prefer([item for item in typed if is_ahu(item)], prefer_ids)
    vav = prefer([item for item in typed if is_vav(item)], ())
    if ahu:
        chosen.append(ahu)
    if vav and (not ahu or vav["equipment_id"] != ahu["equipment_id"]):
        chosen.append(vav)
    if chosen:
        return chosen
    by_id = {item["equipment_id"]: item for item in typed}
    for fid in fixture_ids:
        if fid in by_id:
            chosen.append(by_id[fid])
    return chosen


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        secs = float(value)
        if secs > 10_000_000_000:
            secs /= 1000.0
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def series_stats(
    timestamps: list[datetime],
    values: list[Any],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    pairs = [(ts, val) for ts, val in zip(timestamps, values) if start <= ts <= end]
    pairs.sort(key=lambda item: item[0])
    if not pairs:
        return {"samples": 0, "max_gap_secs": None, "value_changes": 0, "median_gap_secs": None}
    gaps: list[float] = []
    changes = 0
    prev_val: Any = None
    seen_val = False
    for idx, (ts, val) in enumerate(pairs):
        if idx:
            gaps.append((ts - pairs[idx - 1][0]).total_seconds())
        if _present_value(val):
            if seen_val and val != prev_val:
                changes += 1
            prev_val = val
            seen_val = True
    return {
        "samples": len(pairs),
        "max_gap_secs": max(gaps) if gaps else None,
        "value_changes": changes,
        "median_gap_secs": statistics.median(gaps) if gaps else None,
    }


def _present_value(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, str) and val.strip().lower() in {"", "null", "none", "nan"}:
        return False
    return True


def layer_absent(source: str, missing_probe: str) -> dict[str, Any]:
    return {
        "present": False,
        "source": source,
        "missing_probe": missing_probe,
        "samples": None,
        "max_gap_secs": None,
        "value_changes": None,
        "fresh": None,
    }


def layer_from_counts(
    *,
    source: str,
    samples: int | None,
    max_gap_secs: float | None,
    value_changes: int | None = None,
    heartbeat_ok: bool | None = None,
    published: bool | None = None,
    value_unchanged: bool | None = None,
    omit_reason: str | None = None,
    publish_failed: bool | None = None,
) -> dict[str, Any]:
    return {
        "present": True,
        "source": source,
        "missing_probe": None,
        "samples": samples,
        "max_gap_secs": max_gap_secs,
        "value_changes": value_changes,
        "heartbeat_ok": heartbeat_ok,
        "published": published,
        "value_unchanged": value_unchanged,
        "omit_reason": omit_reason,
        "publish_failed": publish_failed,
        "fresh": None,
    }


def railway_layer_from_points(
    points: list[dict[str, Any]] | None,
    *,
    role: str | None,
    start: datetime,
    end: datetime,
    interval_secs: float,
) -> dict[str, Any]:
    """Trust inspect points only when spacing matches the poll, not a hive stride."""
    if not points:
        return layer_absent("historian_inspect", RAILWAY_PROBE)
    ts: list[datetime] = []
    vals: list[Any] = []
    for point in points:
        parsed = parse_ts(point.get("timestamp_utc") or point.get("timestamp"))
        if parsed is None:
            continue
        ts.append(parsed)
        if role and role != "*":
            vals.append(point.get(role))
        else:
            vals.append(parsed.isoformat())
    stats = series_stats(ts, vals, start=start, end=end)
    median = stats.get("median_gap_secs")
    samples = int(stats["samples"])
    if samples < 3 or median is None:
        return layer_absent(
            "historian_inspect",
            RAILWAY_PROBE + f" In-window inspect points={samples}.",
        )
    if median > interval_secs * 1.25:
        return layer_absent(
            "historian_inspect",
            (
                f"inspect median spacing {median:.0f}s is coarser than poll "
                f"{interval_secs:.0f}s (full-hive downsample or a real hole — "
                "indistinguishable). " + RAILWAY_PROBE
            ),
        )
    return layer_from_counts(
        source="historian_inspect",
        samples=samples,
        max_gap_secs=stats["max_gap_secs"],
        value_changes=stats["value_changes"] if role and role != "*" else None,
    )


def _coverage_bad(
    layer: dict[str, Any],
    *,
    expected: int,
    interval: float,
    slack: float,
    gap_multiple: float,
) -> bool | None:
    if not layer.get("present"):
        return None
    flags: list[bool] = []
    samples = layer.get("samples")
    gap = layer.get("max_gap_secs")
    if isinstance(samples, (int, float)) and expected > 0:
        flags.append(float(samples) < expected * (1.0 - slack))
    if isinstance(gap, (int, float)):
        flags.append(float(gap) > interval * gap_multiple)
    if layer.get("publish_failed") is True:
        flags.append(True)
    fresh = layer.get("fresh")
    if fresh is not None and samples is None and gap is None:
        flags.append(not bool(fresh))
    if not flags:
        if layer.get("heartbeat_ok") is True:
            return False
        return None
    return any(flags)


def _healthier(later: dict[str, Any], earlier: dict[str, Any], expected: int) -> bool:
    a = later.get("samples")
    b = earlier.get("samples")
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    slack = max(2.0, 0.1 * expected)
    return float(a) > float(b) + slack


def _verdict(blame: str, reason: str, extra_next: str | None = None) -> dict[str, str]:
    action = extra_next or NEXT_ACTION[blame]
    return {"blame": blame, "reason": reason, "next_action": action}


def _sparse_omit(
    edge: dict[str, Any], transit: dict[str, Any], railway: dict[str, Any]
) -> dict[str, str] | None:
    if edge.get("published") is not False or edge.get("heartbeat_ok") is not True:
        return None
    reason_ok = edge.get("value_unchanged") is True or edge.get("omit_reason") in {
        "health_roles_only",
        "unchanged_not_sent",
    }
    if not reason_ok:
        return None
    if not transit.get("present") or not railway.get("present"):
        return None
    t_samples = transit.get("samples")
    r_samples = railway.get("samples")
    if t_samples == 0 and r_samples == 0:
        why = edge.get("omit_reason") or "unchanged_not_sent"
        return _verdict(
            "SPARSE_OK",
            (
                "Poll/heartbeat succeeded and the edge did not publish this point "
                f"({why}). Transit and historian also have zero samples, so the "
                "layers agree nothing was sent. Unchanged or health-role points "
                "are not internet loss. A published point that is missing downstream "
                "is not this class."
            ),
        )
    if isinstance(t_samples, int) and t_samples > 0:
        return _verdict(
            "INCONCLUSIVE",
            "Edge says the point was not published, but mqtt ingress has samples. "
            "Id match or clocks disagree.",
            "Reconcile edge equipment id with the mqtt topic before blaming a hop.",
        )
    return None


def _sparse_flat(
    edge: dict[str, Any],
    transit: dict[str, Any],
    railway: dict[str, Any],
    *,
    expected: int,
    interval: float,
    slack: float,
    gap_multiple: float,
) -> dict[str, str] | None:
    if railway.get("value_changes") != 0:
        return None
    if _coverage_bad(railway, expected=expected, interval=interval, slack=slack, gap_multiple=gap_multiple) is not False:
        return None
    if not edge.get("present"):
        return None
    if edge.get("heartbeat_ok") is False or edge.get("publish_failed") is True:
        return None
    if edge.get("value_changes") not in (0, None) and edge.get("value_unchanged") is not True:
        return None
    if edge.get("value_changes") not in (0, None) and edge.get("value_changes") != 0:
        return None
    if transit.get("present"):
        t_bad = _coverage_bad(
            transit, expected=expected, interval=interval, slack=slack, gap_multiple=gap_multiple
        )
        if t_bad is True:
            return None
    return _verdict(
        "SPARSE_OK",
        (
            "Timestamps continue near the poll cadence and the PV does not change. "
            "Fieldbus publishes a full snapshot every cycle, including unchanged "
            "values, so a flat trace is not a missing packet. Loss requires a "
            "timestamp hole or a publish that the cloud did not keep."
        ),
    )


def classify_io(
    io: dict[str, Any],
    *,
    interval: float,
    expected: int,
    slack: float = 0.15,
    gap_multiple: float = 1.75,
) -> dict[str, str]:
    edge = io.get("edge") or {}
    transit = io.get("transit") or {}
    railway = io.get("railway") or {}
    omitted = _sparse_omit(edge, transit, railway)
    if omitted:
        return omitted
    flat = _sparse_flat(
        edge,
        transit,
        railway,
        expected=expected,
        interval=interval,
        slack=slack,
        gap_multiple=gap_multiple,
    )
    if flat:
        return flat

    kwargs = {
        "expected": expected,
        "interval": interval,
        "slack": slack,
        "gap_multiple": gap_multiple,
    }
    e_bad = _coverage_bad(edge, **kwargs)
    t_bad = _coverage_bad(transit, **kwargs)
    r_bad = _coverage_bad(railway, **kwargs)

    if e_bad is True:
        if _healthier(transit, edge, expected) or _healthier(railway, edge, expected):
            return _verdict(
                "INCONCLUSIVE",
                "Downstream sample counts exceed the edge ledger. "
                "Equipment ids or clocks do not line up, so the hop is not proven.",
            )
        return _verdict(
            "EDGE",
            "Field edge poll/publish count or gap is short, and cloud counts are not higher. "
            "The samples never left the edge (poll miss, MQTT session down, or publish fail).",
        )
    if e_bad is None and (t_bad is True or r_bad is True):
        return _verdict(
            "INCONCLUSIVE",
            "Cloud side is short but the edge ledger is missing, so this can be EDGE or a later hop. "
            + EDGE_PROBE,
        )
    if e_bad is False and t_bad is True:
        if _healthier(railway, transit, expected):
            return _verdict(
                "INCONCLUSIVE",
                "Historian has more samples than mqtt ingress. "
                "That does not match transit loss or a persist drop.",
            )
        return _verdict(
            "TRANSIT",
            "Edge publish evidence is healthy, but mqtt ingress is short by the same amount "
            "as the historian. The broker did not see those packets (internet hop or broker unreachable).",
        )
    if e_bad is False and t_bad is None and r_bad is True:
        return _verdict(
            "INCONCLUSIVE",
            "Historian is gapped and the edge looks healthy, but mqtt ingress for the window "
            "is missing, so this can be TRANSIT or RAILWAY. " + TRANSIT_PROBE,
        )
    if e_bad is False and t_bad is False and r_bad is True:
        return _verdict(
            "RAILWAY",
            "Edge and mqtt ingress both cover the window, but historian samples are short "
            "or timestamp-gapped. Railway accepted the packets and did not persist them.",
        )
    if e_bad is False and (t_bad is False or t_bad is None) and r_bad is False:
        return _verdict(
            "OK",
            "Edge and historian agree the window is filled near the poll cadence.",
        )
    missing = []
    if e_bad is None:
        missing.append("EDGE: " + (edge.get("missing_probe") or EDGE_PROBE))
    if t_bad is None:
        missing.append("TRANSIT: " + (transit.get("missing_probe") or TRANSIT_PROBE))
    if r_bad is None:
        missing.append("RAILWAY: " + (railway.get("missing_probe") or RAILWAY_PROBE))
    return _verdict(
        "INCONCLUSIVE",
        "Missing instrumentation. " + " ".join(missing),
    )


def _age_stale(age: float | None, interval: float) -> bool | None:
    if age is None:
        return None
    return age > interval * 2.0


def classify_snapshot(snapshot: dict[str, Any], *, interval: float) -> dict[str, str]:
    """Current-cycle blame from ages. Does not prove a 24h hole."""
    poll_stale = _age_stale(snapshot.get("edge_poll_age_secs"), interval)
    ack_stale = _age_stale(snapshot.get("edge_ack_age_secs"), interval)
    mqtt_stale = _age_stale(snapshot.get("mqtt_age_secs"), interval)
    ingest_stale = _age_stale(snapshot.get("ingest_age_secs"), interval)
    publish_failed = snapshot.get("publish_failed") is True
    no_session = snapshot.get("publish_no_session") is True

    if no_session or (poll_stale is False and ack_stale is True):
        return _verdict(
            "EDGE",
            "The edge is polling but the latest QoS 1 publish ack is stale or the MQTT "
            "session is down. Packets are not leaving the field edge.",
        )
    if poll_stale is True and mqtt_stale is not False:
        return _verdict(
            "EDGE",
            "Field edge poll timestamp is older than two poll intervals. "
            "Railway cannot receive a cycle the edge did not run.",
        )
    if poll_stale is None and ack_stale is None and (mqtt_stale is True or ingest_stale is True):
        return _verdict(
            "INCONCLUSIVE",
            "Cloud telemetry looks stale and the field edge was not probed. " + EDGE_PROBE,
        )
    if poll_stale is False and ack_stale is None and mqtt_stale is True:
        if publish_failed:
            return _verdict(
                "TRANSIT",
                "Edge poll is fresh and the last publish attempt failed (no broker ack) "
                "while Railway mqtt ingress is stale.",
            )
        return _verdict(
            "INCONCLUSIVE",
            "Edge poll is fresh and Railway mqtt is stale, but there is no publish-ack "
            "ledger, so a local publish failure and an internet drop are both possible. "
            + EDGE_PROBE,
        )
    if ack_stale is False and mqtt_stale is True:
        return _verdict(
            "RAILWAY",
            "The broker acked the edge publish (QoS 1) but central mqtt monitor has no "
            "fresh message. The drop is inside Railway after the broker accepted the packet.",
        )
    if mqtt_stale is False and ingest_stale is True:
        return _verdict(
            "RAILWAY",
            "Central mqtt monitor received a fresh message but last_ingest_at is stale. "
            "The subscriber saw the packet and did not accept it into the historian.",
        )
    if mqtt_stale is False and ingest_stale is False and poll_stale is not True:
        return _verdict(
            "OK",
            "Snapshot clocks are inside two poll intervals. This does not clear 24h holes.",
        )
    if poll_stale is False and mqtt_stale is None:
        return _verdict(
            "INCONCLUSIVE",
            "Edge poll is fresh but Railway mqtt monitor was not read. " + TRANSIT_PROBE,
        )
    return _verdict(
        "INCONCLUSIVE",
        "Snapshot is incomplete. " + EDGE_PROBE + " " + TRANSIT_PROBE,
    )


def edge_window_from_ledger(
    ledger: dict[str, Any] | None,
    *,
    equipment_id: str,
    start: datetime,
    end: datetime,
    expected: int,
    interval: float,
) -> dict[str, Any]:
    del expected, interval
    if not isinstance(ledger, dict) or "publish_acks" not in ledger:
        return layer_absent("fieldbus_publish_ledger", EDGE_PROBE)
    recent = ledger.get("recent")
    if not isinstance(recent, list):
        return layer_absent("fieldbus_publish_ledger", EDGE_PROBE + " recent[] missing.")
    all_times: list[datetime] = []
    equip_times: list[datetime] = []
    for mark in recent:
        if not isinstance(mark, dict) or mark.get("ok") is False:
            continue
        parsed = parse_ts(mark.get("at") or mark.get("unix_ms"))
        if parsed is None or not (start <= parsed <= end):
            continue
        all_times.append(parsed)
        ids = mark.get("equipment_ids") or []
        if equipment_id in ids:
            equip_times.append(parsed)
    if len(all_times) < 2:
        return layer_absent(
            "fieldbus_publish_ledger",
            EDGE_PROBE + " Ledger ring does not cover this window yet.",
        )
    span = (max(all_times) - min(all_times)).total_seconds()
    window_span = (end - start).total_seconds()
    if window_span > 0 and span < window_span * 0.5:
        return layer_absent(
            "fieldbus_publish_ledger",
            EDGE_PROBE
            + " Ledger ring does not cover this window yet (process recently started or old image).",
        )
    equip_times.sort()
    gaps = [
        (equip_times[i] - equip_times[i - 1]).total_seconds()
        for i in range(1, len(equip_times))
    ]
    fails = int(ledger.get("publish_fails") or 0)
    no_session = int(ledger.get("publish_no_session") or 0)
    return layer_from_counts(
        source="fieldbus_publish_ledger",
        samples=len(equip_times),
        max_gap_secs=max(gaps) if gaps else None,
        heartbeat_ok=len(equip_times) > 0,
        published=len(equip_times) > 0,
        publish_failed=fails > 0 and len(equip_times) == 0,
        value_changes=None,
        omit_reason="publish_no_session" if no_session and not equip_times else None,
    )


def transit_window_from_monitor(
    monitor: dict[str, Any] | None,
    *,
    equipment_id: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    if not isinstance(monitor, dict):
        return layer_absent("mqtt_monitor", TRANSIT_PROBE)
    messages = monitor.get("recent_messages") or monitor.get("messages") or []
    if not isinstance(messages, list):
        return layer_absent("mqtt_monitor", TRANSIT_PROBE)
    times: list[datetime] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        parsed = parse_ts(msg.get("received_at_utc") or msg.get("at"))
        if parsed is None or not (start <= parsed <= end):
            continue
        topic = str(msg.get("topic") or "")
        if "telemetry" not in topic and "telemetry" not in str(msg.get("payload_preview") or ""):
            # Still count mqtt traffic in the window at stream level when the
            # preview is truncated and cannot name equipment.
            if msg.get("truncated") is True:
                times.append(parsed)
            continue
        preview = str(msg.get("payload_preview") or "")
        if msg.get("truncated") is True or equipment_id in preview or equipment_id in topic:
            times.append(parsed)
    times.sort()
    if len(times) < 2:
        return layer_absent("mqtt_monitor", TRANSIT_PROBE)
    span = (times[-1] - times[0]).total_seconds()
    window_span = (end - start).total_seconds()
    if window_span > 0 and span < window_span * 0.5:
        return layer_absent(
            "mqtt_monitor",
            TRANSIT_PROBE + f" Monitor span is {span:.0f}s, shorter than half the window.",
        )
    gaps = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
    return layer_from_counts(
        source="mqtt_monitor",
        samples=len(times),
        max_gap_secs=max(gaps) if gaps else None,
    )


def build_rows(
    *,
    equipment: list[dict[str, str]],
    ledger: dict[str, Any] | None,
    monitor: dict[str, Any] | None,
    inspect_by_equipment: dict[str, list[dict[str, Any]]],
    start: datetime,
    end: datetime,
    interval: float,
    expected: int,
    roles_by_equipment: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roles_by_equipment = roles_by_equipment or {}
    for equip in equipment:
        eid = equip["equipment_id"]
        roles = roles_by_equipment.get(eid) or ["*"]
        points = inspect_by_equipment.get(eid) or []
        edge = edge_window_from_ledger(
            ledger,
            equipment_id=eid,
            start=start,
            end=end,
            expected=expected,
            interval=interval,
        )
        transit = transit_window_from_monitor(
            monitor, equipment_id=eid, start=start, end=end
        )
        for role in roles:
            railway = railway_layer_from_points(
                points, role=role, start=start, end=end, interval_secs=interval
            )
            io = {
                "equipment_id": eid,
                "equipment_type": equip.get("equipment_type") or "",
                "io_id": eid if role in ("", "*") else f"{eid}/{role}",
                "role": role,
                "edge": edge,
                "transit": transit,
                "railway": railway,
            }
            verdict = classify_io(io, interval=interval, expected=expected)
            rows.append({**io, **verdict})
    return rows


def count_blames(blames: list[str]) -> dict[str, int]:
    counts = {name: 0 for name in BLAME_ORDER}
    for blame in blames:
        counts[blame] = counts.get(blame, 0) + 1
    return counts


def instrumentation_complete(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for row in rows:
        if row.get("blame") == "INCONCLUSIVE":
            return False
        for key in ("edge", "transit", "railway"):
            layer = row.get(key) or {}
            if not layer.get("present"):
                return False
    return True


def render_scorecard(report: dict[str, Any]) -> str:
    counts = report.get("counts") or {}
    count_txt = " ".join(f"{name}={counts.get(name, 0)}" for name in BLAME_ORDER)
    lines = [
        (
            "MQTTS gap blame"
            f"  window={report.get('window_hours')}h"
            f"  interval={report.get('interval_secs')}s"
            f"  building={report.get('building_id')}"
            f"  edge={report.get('edge_id') or '-'}"
        ),
        f"counts  {count_txt}",
        (
            "sparse_ok  flat PV with poll-cadence timestamps, or poll/heartbeat "
            "with the point not published and both cloud layers empty. "
            "Unchanged values that were published are still expected in historian."
        ),
    ]
    snap = report.get("snapshot") or {}
    if snap:
        lines.append(
            f"snapshot  {snap.get('blame')}  {snap.get('reason')}"
        )
        lines.append(f"  next: {snap.get('next_action')}")
    lines.append("worst:")
    worst = report.get("worst") or []
    if not worst:
        lines.append("  (none)")
    for row in worst:
        edge_n = (row.get("edge") or {}).get("samples")
        transit_n = (row.get("transit") or {}).get("samples")
        rail_n = (row.get("railway") or {}).get("samples")
        lines.append(
            f"  {row.get('blame')}  {row.get('io_id')}  "
            f"edge={edge_n} transit={transit_n} railway={rail_n}  "
            f"{row.get('reason')}"
        )
        lines.append(f"    next: {row.get('next_action')}")
    lines.append(f"instrumentation_complete={str(bool(report.get('instrumentation_complete'))).lower()}")
    lines.append(f"recommended  {report.get('recommended')}")
    return "\n".join(lines) + "\n"


def assemble_report(
    *,
    rows: list[dict[str, Any]],
    snapshot: dict[str, str],
    window_hours: float,
    interval_secs: float,
    building_id: str,
    edge_id: str | None,
) -> dict[str, Any]:
    blames = [row["blame"] for row in rows] + [snapshot["blame"]]
    counts = count_blames(blames)
    worst = [row for row in rows if row["blame"] in LOSS or row["blame"] == "INCONCLUSIVE"]
    if snapshot["blame"] in LOSS or snapshot["blame"] == "INCONCLUSIVE":
        worst = [
            {
                "blame": snapshot["blame"],
                "io_id": "(snapshot)",
                "reason": snapshot["reason"],
                "next_action": snapshot["next_action"],
                "edge": {},
                "transit": {},
                "railway": {},
            }
        ] + worst
    worst = worst[:8]
    complete = instrumentation_complete(rows) and snapshot["blame"] != "INCONCLUSIVE"
    if any(b in LOSS for b in blames):
        recommended = NEXT_ACTION[next(b for b in ("EDGE", "TRANSIT", "RAILWAY") if counts.get(b))]
    elif not complete:
        recommended = (
            "Scorecard is not a clean bill of health. Close INCONCLUSIVE rows "
            "(edge publish ledger, mqtt ingress over the window, historian gaps)."
        )
    elif counts.get("SPARSE_OK"):
        recommended = NEXT_ACTION["SPARSE_OK"]
    else:
        recommended = NEXT_ACTION["OK"]
    return {
        "ok": not any(b in LOSS for b in blames),
        "window_hours": window_hours,
        "interval_secs": interval_secs,
        "building_id": building_id,
        "edge_id": edge_id,
        "counts": counts,
        "rows": rows,
        "snapshot": snapshot,
        "worst": worst,
        "instrumentation_complete": complete,
        "recommended": recommended,
    }


def exit_code(report: dict[str, Any]) -> int:
    blames = [row["blame"] for row in report.get("rows") or []]
    snap = (report.get("snapshot") or {}).get("blame")
    if snap:
        blames.append(snap)
    if any(b in LOSS for b in blames):
        return 1
    if not blames or all(b == "INCONCLUSIVE" for b in blames):
        return 2
    if not report.get("instrumentation_complete"):
        return 2
    return 0


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        code = exc.code
    except urllib.error.URLError:
        return 0, None
    if not raw:
        return code, None
    try:
        return code, json.loads(raw.decode())
    except json.JSONDecodeError:
        return code, None


def _login(base: str, username: str, password: str) -> str | None:
    code, payload = _http_json(
        f"{base}/api/auth/login",
        method="POST",
        body={"username": username, "password": password},
    )
    if code != 200 or not isinstance(payload, dict):
        return None
    token = payload.get("token") or payload.get("access_token")
    return str(token) if token else None


def _equipment_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows = payload.get("equipment") or payload.get("items") or []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _inspect_points(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    analytics = payload.get("analytics") if isinstance(payload.get("analytics"), dict) else payload
    points = analytics.get("points") if isinstance(analytics, dict) else None
    if not isinstance(points, list):
        return []
    return [point for point in points if isinstance(point, dict)]


def _roles_from_points(points: list[dict[str, Any]]) -> list[str]:
    preferred = ("sat", "zone_t", "fan_status", "oa_damper_pct", "damper_pct")
    found = []
    keys: set[str] = set()
    for point in points:
        keys.update(point.keys())
    for role in preferred:
        if role in keys:
            found.append(role)
    if not found:
        return ["*"]
    return found[:4]


def collect_live(args: argparse.Namespace) -> dict[str, Any]:
    interval = float(args.interval_secs)
    window_hours = float(args.window_hours)
    expected = expected_samples(window_hours, interval)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=window_hours)
    base = (args.api_base or "").rstrip("/")
    building = args.building_id
    edge_id = args.edge_id or None
    token = args.token or None
    if base and not token and args.username and args.password:
        token = _login(base, args.username, args.password)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    equipment_payload = None
    health = None
    monitor = None
    ingest = None
    if base and token:
        _, equipment_payload = _http_json(
            f"{base}/api/fdd/equipment?building_id={urllib.parse.quote(building)}",
            headers=headers,
            timeout=60,
        )
        token, headers, equipment_payload = _prefer_building_operator(
            base, building, token, headers, equipment_payload
        )
        _, health = _http_json(f"{base}/api/health", headers=headers)
        _, monitor = _http_json(f"{base}/api/mqtt/monitor", headers=headers)
        _, ingest = _http_json(f"{base}/api/ingest/stats", headers=headers)
        if not edge_id:
            _, edges_payload = _http_json(f"{base}/api/edges", headers=headers)
            edge_id = _pick_edge_id(edges_payload)

    ledger = _load_json_arg(args.edge_export)
    poll_status = None
    if ledger is None and args.edge_base:
        ledger, poll_status = _fetch_edge(args.edge_base.rstrip("/"), args.edge_api_key)

    rows_src = _equipment_rows(equipment_payload)
    fixture = tuple(x for x in (args.fixture_ids or "").split(",") if x)
    selected = select_samples(rows_src, fixture_ids=fixture)
    if not selected and fixture:
        selected = [
            {"equipment_id": fid, "equipment_type": "", "raw": "", "kind": ""}
            for fid in fixture
        ]

    inspect_by: dict[str, list[dict[str, Any]]] = {}
    roles_by: dict[str, list[str]] = {}
    if base and token and args.use_inspect:
        for equip in selected:
            code, payload = _http_json(
                f"{base}/api/analytics/inspect",
                method="POST",
                headers=headers,
                body={
                    "building_id": building,
                    "equipment_ids": [equip["equipment_id"]],
                    "max_points": int(args.inspect_max_points),
                },
                timeout=float(args.inspect_timeout),
            )
            points = _inspect_points(payload) if code == 200 else []
            inspect_by[equip["equipment_id"]] = points
            roles_by[equip["equipment_id"]] = _roles_from_points(points)

    rows = build_rows(
        equipment=selected,
        ledger=ledger,
        monitor=monitor if isinstance(monitor, dict) else None,
        inspect_by_equipment=inspect_by,
        start=start,
        end=end,
        interval=interval,
        expected=expected,
        roles_by_equipment=roles_by,
    )
    snapshot = classify_snapshot(
        _snapshot_evidence(
            health if isinstance(health, dict) else None,
            monitor if isinstance(monitor, dict) else None,
            ingest if isinstance(ingest, dict) else None,
            ledger,
            poll_status,
            now=end,
        ),
        interval=interval,
    )
    return assemble_report(
        rows=rows,
        snapshot=snapshot,
        window_hours=window_hours,
        interval_secs=interval,
        building_id=building,
        edge_id=edge_id,
    )


def _prefer_building_operator(
    base: str,
    building: str,
    token: str | None,
    headers: dict[str, str],
    equipment_payload: Any,
) -> tuple[str | None, dict[str, str], Any]:
    """Hub admin often cannot read the ACME tenant inventory. Retry as acme-ops."""
    if _equipment_rows(equipment_payload):
        return token, headers, equipment_payload
    if building.strip().upper() != "ACME":
        return token, headers, equipment_payload
    ops_pass = os.environ.get("OPENFDD_USER_ACME_OPS_PASSWORD") or os.environ.get(
        "OPENFDD_USER_A_OPS_PASSWORD"
    ) or ""
    ops_user = os.environ.get("OPENFDD_USER_A_OPS_USER") or "acme-ops"
    if not ops_pass:
        return token, headers, equipment_payload
    ops_token = _login(base, ops_user, ops_pass)
    if not ops_token:
        return token, headers, equipment_payload
    ops_headers = {"Authorization": f"Bearer {ops_token}"}
    _, payload = _http_json(
        f"{base}/api/fdd/equipment?building_id={urllib.parse.quote(building)}",
        headers=ops_headers,
        timeout=60,
    )
    if _equipment_rows(payload):
        return ops_token, ops_headers, payload
    return token, headers, equipment_payload


def _pick_edge_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    edges = payload.get("edges") or []
    if not isinstance(edges, list):
        return None
    preferred = None
    fallback = None
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        eid = str(edge.get("edge_id") or "")
        if not eid:
            continue
        if eid == "vim-1":
            preferred = eid
        if edge.get("has_telemetry") and fallback is None:
            fallback = eid
    return preferred or fallback


def _fetch_edge(base: str, api_key: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    ledger = None
    for path in ("/api/mqtt/publish-ledger", "/mqtt/publish-ledger"):
        code, payload = _http_json(f"{base}{path}", headers=headers)
        if code == 200 and isinstance(payload, dict) and "publish_acks" in payload:
            ledger = payload
            break
    poll = None
    for path in ("/bacnet/poll/status", "/api/bacnet/poll/status"):
        code, payload = _http_json(f"{base}{path}", headers=headers, timeout=20)
        if code == 200 and isinstance(payload, dict):
            poll = payload
            break
    return ledger, poll


def _snapshot_evidence(
    health: dict[str, Any] | None,
    monitor: dict[str, Any] | None,
    ingest: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    poll_status: dict[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    def age_of(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        return max(0.0, (now - ts).total_seconds())

    poll_age = None
    if isinstance(poll_status, dict):
        poll_age = age_of(parse_ts(poll_status.get("last_cycle_ts")))
    ack_age = None
    publish_failed = None
    no_session = None
    if isinstance(ledger, dict) and "publish_acks" in ledger:
        ack_age = age_of(parse_ts(ledger.get("last_ack_at") or ledger.get("last_ack_unix_ms")))
        publish_failed = int(ledger.get("publish_fails") or 0) > 0 and int(ledger.get("publish_acks") or 0) == 0
        no_session = int(ledger.get("publish_no_session") or 0) > 0 and int(ledger.get("publish_acks") or 0) == 0
    mqtt_age = None
    if isinstance(monitor, dict):
        newest: datetime | None = None
        for msg in monitor.get("recent_messages") or []:
            if not isinstance(msg, dict):
                continue
            parsed = parse_ts(msg.get("received_at_utc"))
            if parsed is not None and (newest is None or parsed > newest):
                newest = parsed
        mqtt_age = age_of(newest)
    ingest_age = None
    if isinstance(health, dict):
        ingest_age = age_of(parse_ts(health.get("last_ingest_at")))
    _ = ingest
    return {
        "edge_poll_age_secs": poll_age,
        "edge_ack_age_secs": ack_age,
        "mqtt_age_secs": mqtt_age,
        "ingest_age_secs": ingest_age,
        "publish_failed": publish_failed,
        "publish_no_session": no_session,
    }


def _load_json_arg(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


def report_from_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    interval = float(payload.get("interval_secs") or 300)
    window_hours = float(payload.get("window_hours") or 24)
    expected = int(payload.get("expected_samples") or expected_samples(window_hours, interval))
    rows_out = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        verdict = classify_io(row, interval=interval, expected=expected)
        rows_out.append({**row, **verdict})
    snap_in = payload.get("snapshot_evidence") or {}
    if payload.get("snapshot") and payload["snapshot"].get("blame"):
        snapshot = {
            "blame": payload["snapshot"]["blame"],
            "reason": payload["snapshot"].get("reason") or "",
            "next_action": payload["snapshot"].get("next_action") or NEXT_ACTION[payload["snapshot"]["blame"]],
        }
    else:
        snapshot = classify_snapshot(snap_in, interval=interval)
    return assemble_report(
        rows=rows_out,
        snapshot=snapshot,
        window_hours=window_hours,
        interval_secs=interval,
        building_id=str(payload.get("building_id") or ""),
        edge_id=payload.get("edge_id"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MQTTS gap blame scorecard")
    parser.add_argument("--evidence", help="Normalized evidence JSON (no network)")
    parser.add_argument("--api-base", default=os.environ.get("OPENFDD_API_BASE") or os.environ.get("RAILWAY_BASE") or "")
    parser.add_argument("--building-id", default=os.environ.get("OPENFDD_GAP_BUILDING") or os.environ.get("OPENFDD_AFDD_BUILDING_ID") or "ACME")
    parser.add_argument("--edge-id", default=os.environ.get("EXPECTED_EDGE_ID") or "")
    parser.add_argument("--edge-base", default=os.environ.get("OPENFDD_EDGE_BASE") or os.environ.get("FIELDBUS_BASE") or "")
    parser.add_argument("--edge-api-key", default=os.environ.get("OPENFDD_FIELDBUS_API_KEY") or "")
    parser.add_argument("--edge-export", default=os.environ.get("OPENFDD_EDGE_EXPORT") or "")
    parser.add_argument("--username", default=os.environ.get("OPENFDD_GAP_USER") or "admin")
    parser.add_argument("--password", default=os.environ.get("OPENFDD_ADMIN_PASSWORD") or "")
    parser.add_argument("--token", default=os.environ.get("OPENFDD_ADMIN_TOKEN") or "")
    parser.add_argument("--window-hours", type=float, default=window_hours_from_env())
    parser.add_argument("--interval-secs", type=float, default=float(os.environ.get("OPENFDD_GAP_INTERVAL_SECS") or 300))
    parser.add_argument("--fixture-ids", default=os.environ.get("OPENFDD_GAP_FIXTURE_IDS") or "RTU_01")
    parser.add_argument(
        "--use-inspect",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("OPENFDD_GAP_USE_INSPECT", "1") != "0",
    )
    parser.add_argument("--inspect-max-points", type=int, default=int(os.environ.get("OPENFDD_GAP_INSPECT_MAX_POINTS") or 2000))
    parser.add_argument("--inspect-timeout", type=float, default=float(os.environ.get("OPENFDD_GAP_INSPECT_TIMEOUT") or 45))
    parser.add_argument("--json-out", default=os.environ.get("OPENFDD_GAP_JSON") or "")
    args = parser.parse_args(argv)

    if args.evidence:
        with open(args.evidence, encoding="utf-8") as handle:
            report = report_from_evidence(json.load(handle))
    elif not args.api_base and not args.edge_export:
        report = assemble_report(
            rows=[],
            snapshot=_verdict(
                "INCONCLUSIVE",
                "Set OPENFDD_API_BASE (Railway central/web) and, on the OptiPlex, "
                "OPENFDD_EDGE_BASE for the fieldbus ledger. " + EDGE_PROBE,
            ),
            window_hours=args.window_hours,
            interval_secs=args.interval_secs,
            building_id=args.building_id,
            edge_id=args.edge_id or None,
        )
    else:
        report = collect_live(args)

    text = render_scorecard(report)
    sys.stdout.write(text)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
            handle.write("\n")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
