"""Probe sibling stack services for dashboard status strip."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Literal

from .commission_client import (
    commission_base_url,
    commission_health,
    commission_poll_status,
    commission_status,
)
from .paths import bacnet_poll_csv, workspace_dir

Status = Literal["green", "yellow", "red", "gray"]


def _probe_url(url: str, timeout: float = 2.0) -> tuple[bool, str, int | None]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return True, "ok", resp.status
    except urllib.error.HTTPError as exc:
        return False, str(exc.reason), exc.code
    except urllib.error.URLError as exc:
        return False, str(exc.reason), None
    except Exception as exc:
        return False, str(exc), None


def _status(ok: bool, configured: bool, detail: str = "") -> Status:
    if not configured:
        return "gray"
    if ok:
        return "green"
    lower = detail.lower()
    if any(x in lower for x in ("timeout", "timed out", "connection refused", "actively refused")):
        return "red"
    return "yellow"


def _parse_poll_at(at: str) -> float | None:
    raw = (at or "").strip()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except (TypeError, ValueError):
        return None


def _ollama_configured() -> bool:
    """Show in the status strip unless explicitly disabled."""
    flag = os.environ.get("OFDD_OLLAMA_ENABLED", "").strip().lower()
    return flag not in {"0", "false", "no"}


def _ollama_service() -> dict[str, Any]:
    from . import ollama_client

    configured = _ollama_configured()
    if not configured:
        return {
            "id": "ollama",
            "label": "Ollama",
            "status": "gray",
            "configured": False,
            "detail": "not enabled (set OFDD_OLLAMA_ENABLED=1 or OFDD_OLLAMA_BASE_URL)",
        }

    try:
        health_timeout = float(os.environ.get("OFDD_OLLAMA_HEALTH_TIMEOUT_S", "8"))
    except ValueError:
        health_timeout = 8.0
    health = ollama_client.health(timeout=health_timeout)
    ok = health.get("ok") is True
    model = str(health.get("configured_model") or "").strip()
    tier = str(health.get("configured_ram_tier") or "").strip()
    gpu = os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu").strip() or "cpu"
    if ok:
        detail = ", ".join(x for x in [model, f"{tier}, {gpu}" if tier else gpu] if x)
    else:
        detail = str(health.get("error") or "unreachable")[:200]
    return {
        "id": "ollama",
        "label": "Ollama",
        "status": _status(ok, True, detail),
        "configured": True,
        "detail": detail,
        "url": health.get("base_url"),
    }


def _bacnet_poll_service() -> dict[str, Any]:
    """Poll loop runs inside the commission agent — use its /api/bacnet/poll/status."""
    points = workspace_dir() / "bacnet" / "commissioning" / "points.csv"
    poll_configured = points.is_file()
    poll_status: Status = "gray"
    poll_detail = "points.csv not commissioned"

    if not poll_configured:
        return {
            "id": "bacnet_poll",
            "label": "BACnet poll",
            "status": poll_status,
            "configured": False,
            "detail": poll_detail,
        }

    code, payload = commission_poll_status()
    if code != 200 or not isinstance(payload, dict):
        comm_code, comm_payload = commission_health()
        if comm_code != 200:
            poll_status = "red"
            poll_detail = "commission agent down — poll loop not running"
        else:
            poll_status = "yellow"
            poll_detail = "poll status unavailable from commission agent"
        return {
            "id": "bacnet_poll",
            "label": "BACnet poll",
            "status": poll_status,
            "configured": True,
            "detail": poll_detail,
        }

    enabled = int(payload.get("enabled_points") or 0)
    interval_s = float(payload.get("interval_s") or 60.0)
    samples = int(payload.get("samples") or 0)
    error = str(payload.get("error") or "").strip()
    age_s = _parse_poll_at(str(payload.get("at") or ""))

    if enabled == 0:
        poll_status = "gray"
        poll_detail = "points.csv present; no rows enabled for polling"
    elif error:
        poll_status = "red"
        poll_detail = error
    elif age_s is not None:
        stale_after = max(300.0, interval_s * 2.5)
        if age_s <= stale_after:
            poll_status = "green"
            poll_detail = f"{enabled} point(s) · last poll {int(age_s)}s ago ({samples} samples)"
        else:
            poll_status = "yellow"
            poll_detail = f"last poll stale ({int(age_s // 60)}m ago)"
    else:
        poll_csv = bacnet_poll_csv()
        if poll_csv.is_file():
            csv_age = time.time() - poll_csv.stat().st_mtime
            if csv_age < 300:
                poll_status = "green"
                poll_detail = f"poll CSV updated {int(csv_age)}s ago"
            else:
                poll_status = "yellow"
                poll_detail = f"poll CSV stale ({int(csv_age // 60)}m)"
        else:
            poll_status = "yellow"
            poll_detail = f"{enabled} point(s) enabled; waiting for first poll cycle"

    return {
        "id": "bacnet_poll",
        "label": "BACnet poll",
        "status": poll_status,
        "configured": True,
        "detail": poll_detail,
    }


def stack_health(*, verbose: bool = False) -> dict[str, Any]:
    services: list[dict[str, Any]] = []

    # Bridge (self)
    services.append(
        {
            "id": "bridge",
            "label": "Bridge API",
            "status": "green",
            "configured": True,
            "detail": "ok",
            "url": f"http://{os.environ.get('OFDD_BRIDGE_HOST', '0.0.0.0')}:{os.environ.get('OFDD_BRIDGE_PORT', '8765')}",
        }
    )

    # BACnet commission agent (discover / write / poll loop)
    comm_url = commission_base_url()
    code, payload = commission_health()
    comm_ok = code == 200 and isinstance(payload, dict) and payload.get("ok")
    services.append(
        {
            "id": "bacnet_commission",
            "label": "BACnet commission",
            "status": _status(comm_ok, True, str(payload.get("error", "") if isinstance(payload, dict) else "")),
            "configured": True,
            "detail": "ok" if comm_ok else (payload if isinstance(payload, dict) else str(payload)),
            "url": comm_url,
        }
    )

    services.append(_bacnet_poll_service())

    # Optional MCP RAG sidecar
    mcp_base = os.environ.get("OFDD_MCP_REST_BASE", "http://127.0.0.1:8090").rstrip("/")
    mcp_enabled = os.environ.get("OFDD_MCP_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    if mcp_enabled:
        mcp_ok, mcp_detail, _ = _probe_url(f"{mcp_base}/health")
        services.append(
            {
                "id": "mcp_rag",
                "label": "MCP RAG",
                "status": _status(mcp_ok, True, mcp_detail),
                "configured": True,
                "detail": mcp_detail,
                "url": mcp_base,
            }
        )
    else:
        services.append(
            {
                "id": "mcp_rag",
                "label": "MCP RAG",
                "status": "gray",
                "configured": False,
                "detail": "not enabled (set OFDD_MCP_ENABLED=1)",
            }
        )

    services.append(_ollama_service())

    # Commission agent BACnet bind summary
    st_code, st_payload = commission_status()
    bacnet_bind = None
    if st_code == 200 and isinstance(st_payload, dict):
        bacnet_bind = st_payload.get("bacnet_bind")

    overall: Status = "green"
    for svc in services:
        if svc["status"] == "red":
            overall = "red"
            break
        if svc["status"] == "yellow" and overall == "green":
            overall = "yellow"

    out: dict[str, Any] = {
        "ok": overall in {"green", "yellow"},
        "overall": overall,
        "services": services,
    }
    if verbose:
        out["bacnet_bind"] = bacnet_bind
        return out
    for svc in services:
        svc.pop("url", None)
        if isinstance(svc.get("detail"), dict):
            svc["detail"] = "unavailable"
    return out
