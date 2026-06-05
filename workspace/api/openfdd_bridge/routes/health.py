from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from .. import auth
from .. import __version__ as bridge_version
from ..building_status import dashboard_snapshot
from ..deps import require_roles, require_user
from ..security import (
    clients_must_authenticate,
    debug_diagnostics_enabled,
    public_dashboard_ws_allowed,
    ws_allow_query_ticket,
)
from ..stack_health import stack_health

router = APIRouter(tags=["health"])

_DEFAULT_WS_INTERVAL = 5.0


def _ws_interval_sec() -> float:
    raw = os.environ.get("OFDD_DASHBOARD_WS_INTERVAL_SEC", "").strip()
    if not raw:
        return _DEFAULT_WS_INTERVAL
    try:
        val = float(raw)
        return val if val > 0 else _DEFAULT_WS_INTERVAL
    except ValueError:
        return _DEFAULT_WS_INTERVAL


@router.get("/health")
def health() -> dict:
    """Minimal liveness probe for Docker/Caddy (no paths, poll samples, or stack detail)."""
    return {
        "ok": True,
        "service": "openfdd-bridge",
        "version": bridge_version,
        "auth_required": clients_must_authenticate(),
    }


@router.get("/health/stack")
def health_stack(user: dict = Depends(require_user)) -> dict:
    """Authenticated stack probes for the dashboard status strip."""
    verbose = debug_diagnostics_enabled() and auth.role_allows(
        user.get("role"),
        ("integrator", "agent"),
    )
    return stack_health(verbose=verbose)


@router.get("/health/revisions")
def health_revisions(user: dict = Depends(require_user)) -> dict:
    """Docker image tags and build SHAs for troubleshooting."""
    from ..container_revisions import stack_revisions

    include_ids = debug_diagnostics_enabled() and auth.role_allows(
        user.get("role"),
        ("integrator", "agent"),
    )
    return stack_revisions(include_image_ids=include_ids)


def _ws_ticket_from_websocket(websocket: WebSocket) -> str | None:
    proto = (websocket.headers.get("sec-websocket-protocol") or "").strip()
    if proto:
        parts = [p.strip() for p in proto.split(",")]
        if len(parts) >= 2 and parts[0] in {"ofdd.ws", "ofdd-ticket"}:
            return parts[1].strip() or None
        for part in parts:
            if part.startswith("ofdd.ws."):
                return part[8:].strip() or None
    if ws_allow_query_ticket():
        q = websocket.query_params.get("ticket")
        if q and q.strip():
            return q.strip()
    return None


def _ws_session(websocket: WebSocket) -> tuple[bool, bool]:
    """Return (allowed, redacted_snapshot)."""
    ticket = _ws_ticket_from_websocket(websocket)
    if ticket:
        if auth.verify_ws_ticket(ticket) is not None:
            return True, False
    if public_dashboard_ws_allowed():
        return True, True
    return False, False


@router.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket) -> None:
    """Push stack health + check-engine status; requires a short-lived ticket by default."""
    allowed, redacted = _ws_session(websocket)
    if not allowed:
        await websocket.close(code=1008, reason="unauthorized")
        return
    subprotocol: str | None = None
    proto_header = (websocket.headers.get("sec-websocket-protocol") or "").strip()
    if proto_header:
        offered = [p.strip() for p in proto_header.split(",") if p.strip()]
        if "ofdd.ws" in offered:
            subprotocol = "ofdd.ws"
        elif "ofdd-ticket" in offered:
            subprotocol = "ofdd-ticket"
    await websocket.accept(subprotocol=subprotocol)
    try:
        while True:
            await websocket.send_json(dashboard_snapshot(redacted=redacted))
            await asyncio.sleep(_ws_interval_sec())
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close()


@router.get("/api/audit/summary")
def audit_summary(user: dict = Depends(require_roles("integrator"))) -> dict:
    from ..audit import audit_log_path, error_log_path

    audit_path = audit_log_path()
    error_path = error_log_path()
    payload: dict = {
        "ok": True,
        "audit_log_configured": audit_path.is_file(),
        "audit_bytes": audit_path.stat().st_size if audit_path.is_file() else 0,
        "error_log_configured": error_path.is_file(),
        "error_bytes": error_path.stat().st_size if error_path.is_file() else 0,
    }
    if debug_diagnostics_enabled() and user.get("role") in {"integrator", "agent"}:
        payload["audit_log"] = str(audit_path)
        payload["error_log"] = str(error_path)
    return payload
