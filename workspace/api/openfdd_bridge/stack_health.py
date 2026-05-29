"""Probe sibling stack services for dashboard status strip."""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Any, Literal

from .commission_client import commission_base_url, commission_health, commission_status
from .paths import bacnet_poll_csv, workspace_dir

Status = Literal["green", "yellow", "red", "gray"]


def _probe_url(url: str, timeout: float = 2.0) -> tuple[bool, str, int | None]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    if detail in {"timeout", "timed out", "Connection refused"}:
        return "red"
    return "red"


def stack_health() -> dict[str, Any]:
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

    # BACnet commission agent (discover / write proxy target)
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

    # BACnet poll driver — gray if not configured, yellow if CSV stale, green if recent
    points = workspace_dir() / "bacnet" / "commissioning" / "points.csv"
    poll_csv = bacnet_poll_csv()
    poll_configured = points.is_file()
    poll_status: Status = "gray"
    poll_detail = "points.csv not commissioned"
    if poll_configured:
        if poll_csv.is_file():
            age_s = __import__("time").time() - poll_csv.stat().st_mtime
            if age_s < 300:
                poll_status = "green"
                poll_detail = f"poll CSV updated {int(age_s)}s ago"
            elif age_s < 3600:
                poll_status = "yellow"
                poll_detail = f"poll CSV stale ({int(age_s // 60)}m)"
            else:
                poll_status = "yellow"
                poll_detail = "poll CSV exists but stale — is openfdd-bacnet-poll running?"
        else:
            poll_status = "yellow"
            poll_detail = "points.csv present; poll driver not producing CSV yet"
    services.append(
        {
            "id": "bacnet_poll",
            "label": "BACnet poll",
            "status": poll_status,
            "configured": poll_configured,
            "detail": poll_detail,
        }
    )

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

    return {
        "ok": overall in {"green", "yellow"},
        "overall": overall,
        "services": services,
        "bacnet_bind": bacnet_bind,
    }
