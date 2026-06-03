"""Read-only one-line building summary for the home dashboard.

SECURITY / PRODUCT (do not remove these comments):
- The home page must NOT expose interactive LLM chat, free-text POST bodies, or
  conversation history. That belongs on the ``/agent`` tab only.
- Do not re-add HomeOllamaChat-style inputs; production OT surfaces should not
  train operators to paste credentials or BACnet details into a browser chat box.
- This module returns a single cached sentence on a fixed refresh interval.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .building_status import collect_status
from . import ollama_client
from .zone_temp_analytics import compact_for_llm, get_zone_temp_snapshot

_CACHE: dict[str, Any] = {
    "generated_at": 0.0,
    "sentence": "",
    "source": "none",
    "error": "",
    "next_refresh_at": 0.0,
}

DEFAULT_INTERVAL_S = 900  # 15 minutes
MAX_SENTENCE_LEN = 320
INSIGHT_CHAT_TIMEOUT_S = 45.0


def refresh_interval_s() -> int:
    try:
        return max(60, int(os.environ.get("OFDD_BUILDING_INSIGHT_INTERVAL_S", str(DEFAULT_INTERVAL_S))))
    except ValueError:
        return DEFAULT_INTERVAL_S


def _fallback_sentence(status: dict[str, Any]) -> str:
    alerts = [a for a in (status.get("alerts") or []) if isinstance(a, dict)]
    traffic = status.get("traffic") or status.get("status") or "ok"
    fdd_n = int(status.get("fdd_alert_count") or 0)
    if not alerts:
        return "Building check engine: no active faults — model and stack look nominal."
    titles = [str(a.get("title") or "").strip() for a in alerts[:4] if str(a.get("title") or "").strip()]
    headline = titles[0] if titles else "Active alerts present"
    extra = f" (+{len(alerts) - 1} more)" if len(alerts) > 1 else ""
    fdd_bit = f", {fdd_n} from FDD rules" if fdd_n else ""
    return f"Status {traffic}: {headline}{extra}{fdd_bit}."


def _compact_context(status: dict[str, Any], zone_snapshot: dict[str, Any] | None = None) -> str:
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
        for svc in stack.get("services") or []:
            if isinstance(svc, dict):
                services.append(
                    {
                        "id": svc.get("id"),
                        "status": svc.get("status"),
                        "detail": (str(svc.get("detail") or ""))[:80],
                    }
                )
    health = status.get("model_health") if isinstance(status.get("model_health"), dict) else {}
    payload = {
        "building_status": status.get("status"),
        "traffic": status.get("traffic"),
        "fdd_alert_count": status.get("fdd_alert_count"),
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
        payload["zone_temps"] = json.loads(compact_for_llm(zone_snapshot))
    return json.dumps(payload, separators=(",", ":"))[:4500]


def _ollama_sentence(context: str) -> tuple[str, str]:
    system = (
        "You summarize a BACnet/FDD building edge host for operators. "
        "Reply with exactly ONE sentence, at most 35 words, plain English. "
        "Mention active fault codes or HVAC health when present. "
        "When zone_temps is in the JSON, include one brief clause on overnight vs daytime "
        "zone temperature or slow-recovery zones if data is present. "
        "No markdown, no bullet lists, no questions, no recommendations to change passwords."
    )
    user = f"Snapshot JSON:\n{context}\n\nOne-sentence summary:"
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


def get_building_insight(*, force: bool = False) -> dict[str, Any]:
    """Return cached one-liner; refresh at most every ``OFDD_BUILDING_INSIGHT_INTERVAL_S``."""
    now = time.time()
    interval = refresh_interval_s()
    if (
        not force
        and _CACHE.get("sentence")
        and now < float(_CACHE.get("next_refresh_at") or 0)
    ):
        zone_snapshot = get_zone_temp_snapshot(force=False)
        return {
            "ok": True,
            "sentence": _CACHE["sentence"],
            "zone_sentence": str(zone_snapshot.get("summary_sentence") or ""),
            "zone_temps": {
                "topology_mode": zone_snapshot.get("topology_mode"),
                "zone_sensor_count": zone_snapshot.get("zone_sensor_count"),
                "struggling_zones": zone_snapshot.get("struggling_zones") or [],
                "generated_at": zone_snapshot.get("generated_at"),
                "next_refresh_at": zone_snapshot.get("next_refresh_at"),
                "refresh_interval_s": zone_snapshot.get("refresh_interval_s"),
                "cached": zone_snapshot.get("cached"),
            },
            "source": _CACHE.get("source"),
            "generated_at": _CACHE.get("generated_at"),
            "next_refresh_at": _CACHE.get("next_refresh_at"),
            "refresh_interval_s": interval,
            "cached": True,
            "error": _CACHE.get("error") or "",
        }

    status = collect_status()
    zone_snapshot = get_zone_temp_snapshot(force=force)
    zone_sentence = str(zone_snapshot.get("summary_sentence") or "").strip()
    sentence = ""
    source = "deterministic"
    error = ""

    health = ollama_client.health(timeout=8.0)
    if health.get("ok") and ollama_client.should_use_ollama():
        context = _compact_context(status, zone_snapshot)
        sentence, err = _ollama_sentence(context)
        if sentence:
            source = "ollama"
        else:
            error = err
            sentence = _fallback_sentence(status)
            source = "deterministic"
    else:
        if not health.get("ok"):
            error = str(health.get("error") or "ollama unreachable")[:200]
        sentence = _fallback_sentence(status)

    _CACHE.update(
        {
            "generated_at": now,
            "sentence": sentence,
            "source": source,
            "error": error,
            "next_refresh_at": now + interval,
        }
    )
    return {
        "ok": True,
        "sentence": sentence,
        "zone_sentence": zone_sentence,
        "zone_temps": {
            "topology_mode": zone_snapshot.get("topology_mode"),
            "zone_sensor_count": zone_snapshot.get("zone_sensor_count"),
            "struggling_zones": zone_snapshot.get("struggling_zones") or [],
            "generated_at": zone_snapshot.get("generated_at"),
            "next_refresh_at": zone_snapshot.get("next_refresh_at"),
            "refresh_interval_s": zone_snapshot.get("refresh_interval_s"),
            "cached": zone_snapshot.get("cached"),
        },
        "source": source,
        "generated_at": now,
        "next_refresh_at": now + interval,
        "refresh_interval_s": interval,
        "cached": False,
        "error": error,
        "ollama_ok": health.get("ok") is True,
    }
