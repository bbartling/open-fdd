"""Read-only building summary for the home dashboard.

SECURITY / PRODUCT (do not remove these comments):
- The home page must NOT expose interactive LLM chat, free-text POST bodies, or
  conversation history. That belongs on the ``/agent`` tab only.
- Do not re-add HomeOllamaChat-style inputs; production OT surfaces should not
  train operators to paste credentials or BACnet details into a browser chat box.
- This module returns a cached briefing on a fixed refresh interval.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .building_status import collect_status
from . import ollama_client
from .device_poll_health import get_device_poll_snapshot, slim_devices_for_llm
from .operational_analytics import analytics_lookback_days, analytics_methodology, methodology_prompt_blurb
from .zone_temp_analytics import get_zone_temp_snapshot, slim_zone_for_llm

_CACHE: dict[str, Any] = {
    "generated_at": 0.0,
    "sentence": "",
    "source": "none",
    "error": "",
    "next_refresh_at": 0.0,
    "payload": {},
}

DEFAULT_INTERVAL_S = 900  # 15 minutes
MAX_SENTENCE_LEN = 480
INSIGHT_CHAT_TIMEOUT_S = 45.0


def refresh_interval_s() -> int:
    try:
        return max(60, int(os.environ.get("OFDD_BUILDING_INSIGHT_INTERVAL_S", str(DEFAULT_INTERVAL_S))))
    except ValueError:
        return DEFAULT_INTERVAL_S


def fault_sentences_from_alerts(alerts: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    """One plain-English line per active fault for the dashboard and LLM context."""
    lines: list[str] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        code = str(alert.get("code") or "").strip()
        title = str(alert.get("title") or "").strip()
        if not title:
            continue
        sev = str(alert.get("severity") or "info")
        detail = str(alert.get("detail") or "").strip()
        prefix = f"{code}: " if code else ""
        line = f"{prefix}{title}"
        if detail:
            line += f" — {detail[:160]}"
        line += f" ({sev})."
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _fallback_sentence(status: dict[str, Any], zone_snapshot: dict[str, Any], device_snapshot: dict[str, Any]) -> str:
    parts: list[str] = []
    zone_line = str(zone_snapshot.get("summary_sentence") or "").strip()
    if zone_line:
        parts.append(zone_line)
    dev_line = str(device_snapshot.get("summary_sentence") or "").strip()
    if dev_line:
        parts.append(dev_line)
    alerts = [a for a in (status.get("alerts") or []) if isinstance(a, dict)]
    if not alerts:
        parts.append("Building check engine: no active faults — model and stack look nominal.")
    else:
        traffic = status.get("traffic") or status.get("status") or "ok"
        parts.append(f"Check engine status {traffic} with {len(alerts)} active alert(s).")
    return " ".join(parts)[:MAX_SENTENCE_LEN]


def _compact_context(
    status: dict[str, Any],
    zone_snapshot: dict[str, Any] | None = None,
    device_snapshot: dict[str, Any] | None = None,
) -> str:
    """Minimal JSON for the LLM — no auth, no BACnet bind strings, no operator notes."""
    alerts = []
    for a in (status.get("alerts") or [])[:12]:
        if not isinstance(a, dict):
            continue
        alerts.append(
            {
                "severity": a.get("severity"),
                "title": (str(a.get("title") or ""))[:120],
                "code": (str(a.get("code") or ""))[:32],
                "source": a.get("source"),
            }
        )
    stack = status.get("stack") or {}
    services = []
    if isinstance(stack, dict):
        for svc in (stack.get("services") or [])[:8]:
            if isinstance(svc, dict):
                services.append(
                    {
                        "id": svc.get("id"),
                        "status": svc.get("status"),
                        "detail": (str(svc.get("detail") or ""))[:80],
                    }
                )
    health = status.get("model_health") if isinstance(status.get("model_health"), dict) else {}
    fault_codes = []
    for a in alerts:
        code = str(a.get("code") or "").strip()
        if code:
            fault_codes.append(code)

    payload: dict[str, Any] = {
        "methodology": analytics_methodology(),
        "methodology_blurb": methodology_prompt_blurb(),
        "building_status": status.get("status"),
        "traffic": status.get("traffic"),
        "fdd_alert_count": status.get("fdd_alert_count"),
        "active_fault_codes": fault_codes[:16],
        "fault_sentences": fault_sentences_from_alerts(status.get("alerts") or []),
        "alerts": alerts,
        "model": {
            "configured": status.get("model_configured"),
            "score": health.get("score"),
            "status": health.get("status"),
            "counts": health.get("counts"),
        },
        "stack_services": services,
    }
    if zone_snapshot:
        payload["zone_temps"] = slim_zone_for_llm(
            zone_snapshot,
            max_zones=8,
            max_systems=3,
            max_zones_per_system=6,
            max_struggling=4,
        )
        payload["worst_zones"] = zone_snapshot.get("worst_zones") or []
    if device_snapshot:
        payload["device_poll_health"] = slim_devices_for_llm(device_snapshot)
    return json.dumps(payload, separators=(",", ":"))


def _ollama_sentence(context: str) -> tuple[str, str]:
    days = analytics_lookback_days()
    system = (
        "You summarize a BACnet/FDD building edge host for operators. "
        f"All zone temperature and recovery metrics use the last {days} days of feather poll data "
        "(see methodology in the JSON). Recovery °F/min is averaged only during supply-fan-on periods. "
        "Device poll health uses the same window: all points stale/FDD = offline device; one bad point = sensor issue. "
        "Reply with 2–4 short sentences of plain English (no markdown): "
        "(1) zone overnight vs occupied averages and typical recovery rate, naming worst zones if any; "
        "(2) how many devices are healthy vs offline/flaky; "
        "(3) briefly reference active fault codes from fault_sentences. "
        "Do not invent equipment IDs or passwords."
    )
    user = f"Snapshot JSON:\n{context}\n\nOperator briefing:"
    result = ollama_client.chat(
        user,
        system=system,
        history=[],
        timeout=INSIGHT_CHAT_TIMEOUT_S,
    )
    if not result.get("ok"):
        return "", str(result.get("error") or "ollama failed")
    text = str(result.get("reply") or "").strip().replace("\n", " ")
    if len(text) > MAX_SENTENCE_LEN:
        text = text[: MAX_SENTENCE_LEN - 1].rstrip() + "…"
    return text or "", ""


def _response_payload(
    *,
    sentence: str,
    source: str,
    error: str,
    now: float,
    interval: int,
    cached: bool,
    status: dict[str, Any],
    zone_snapshot: dict[str, Any],
    device_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "sentence": sentence,
        "zone_sentence": str(zone_snapshot.get("summary_sentence") or ""),
        "device_sentence": str(device_snapshot.get("summary_sentence") or ""),
        "methodology": analytics_methodology(),
        "lookback_days": analytics_lookback_days(),
        "fault_sentences": fault_sentences_from_alerts(status.get("alerts") or []),
        "worst_zones": zone_snapshot.get("worst_zones") or [],
        "zone_temps": {
            "topology_mode": zone_snapshot.get("topology_mode"),
            "zone_sensor_count": zone_snapshot.get("zone_sensor_count"),
            "struggling_zones": zone_snapshot.get("struggling_zones") or [],
            "lookback_days": zone_snapshot.get("lookback_days"),
            "generated_at": zone_snapshot.get("generated_at"),
            "next_refresh_at": zone_snapshot.get("next_refresh_at"),
            "refresh_interval_s": zone_snapshot.get("refresh_interval_s"),
            "cached": zone_snapshot.get("cached"),
        },
        "device_poll_health": {
            "healthy_count": device_snapshot.get("healthy_count"),
            "offline_equipment": device_snapshot.get("offline_equipment") or [],
            "flaky_equipment": device_snapshot.get("flaky_equipment") or [],
            "degraded_equipment": device_snapshot.get("degraded_equipment") or [],
            "lookback_days": device_snapshot.get("lookback_days"),
            "generated_at": device_snapshot.get("generated_at"),
            "cached": device_snapshot.get("cached"),
        },
        "source": source,
        "generated_at": now,
        "next_refresh_at": now + interval,
        "refresh_interval_s": interval,
        "cached": cached,
        "error": error,
        "ollama_ok": None,
    }


def get_building_insight(*, force: bool = False) -> dict[str, Any]:
    """Return cached briefing; refresh at most every ``OFDD_BUILDING_INSIGHT_INTERVAL_S``."""
    now = time.time()
    interval = refresh_interval_s()
    if (
        not force
        and _CACHE.get("sentence")
        and now < float(_CACHE.get("next_refresh_at") or 0)
        and isinstance(_CACHE.get("payload"), dict)
    ):
        out = dict(_CACHE["payload"])
        out["cached"] = True
        return out

    status = collect_status()
    zone_snapshot = get_zone_temp_snapshot(force=force)
    device_snapshot = get_device_poll_snapshot(force=force)
    fault_lines = fault_sentences_from_alerts(status.get("alerts") or [])

    sentence = ""
    source = "deterministic"
    error = ""

    health = ollama_client.health(timeout=8.0)
    ollama_ok = health.get("ok") is True
    if ollama_ok and ollama_client.should_use_ollama():
        context = _compact_context(status, zone_snapshot, device_snapshot)
        sentence, err = _ollama_sentence(context)
        if sentence:
            source = "ollama"
        else:
            error = err
            sentence = _fallback_sentence(status, zone_snapshot, device_snapshot)
            source = "deterministic"
    else:
        if not ollama_ok:
            error = str(health.get("error") or "ollama unreachable")[:200]
        sentence = _fallback_sentence(status, zone_snapshot, device_snapshot)

    payload = _response_payload(
        sentence=sentence,
        source=source,
        error=error,
        now=now,
        interval=interval,
        cached=False,
        status=status,
        zone_snapshot=zone_snapshot,
        device_snapshot=device_snapshot,
    )
    payload["ollama_ok"] = ollama_ok
    payload["fault_sentences"] = fault_lines

    _CACHE.update(
        {
            "generated_at": now,
            "sentence": sentence,
            "source": source,
            "error": error,
            "next_refresh_at": now + interval,
            "payload": payload,
        }
    )
    return payload


def get_operational_brief(*, force: bool = False) -> dict[str, Any]:
    """Full structured analytics for API/dashboard (no extra Ollama call)."""
    status = collect_status()
    zone_snapshot = get_zone_temp_snapshot(force=force)
    device_snapshot = get_device_poll_snapshot(force=force)
    return {
        "ok": True,
        "methodology": analytics_methodology(),
        "lookback_days": analytics_lookback_days(),
        "building_status": {
            "status": status.get("status"),
            "traffic": status.get("traffic"),
            "alert_count": len(status.get("alerts") or []),
        },
        "zone_temps": zone_snapshot,
        "device_poll_health": device_snapshot,
        "fault_sentences": fault_sentences_from_alerts(status.get("alerts") or []),
        "data_pipeline": [
            "BACnet poll → feather_store/",
            "data_loader.load_frame_for_run()",
            "zone_temp_analytics.compute_zone_metrics()",
            "device_poll_health.compute_device_poll_health()",
            "building_insight.get_building_insight() / get_operational_brief()",
        ],
    }
