from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..building_status import dashboard_snapshot
from ..deps import public_auth_status, require_roles, require_user
from ..paths import bacnet_poll_csv, data_dir, repo_root, workspace_dir
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
    poll_path = bacnet_poll_csv()
    poll_bytes = poll_path.stat().st_size if poll_path.is_file() else 0
    payload: dict = {
        "ok": True,
        "service": "openfdd-bridge",
        **public_auth_status(),
        "bacnet_poll_csv_exists": poll_path.is_file(),
        "bacnet_poll_csv_bytes": poll_bytes,
    }
    try:
        from ..commission_client import commission_poll_status_quick

        code, poll_payload = commission_poll_status_quick()
        if code == 200 and isinstance(poll_payload, dict):
            payload["bacnet_poll"] = {
                "ok": bool(poll_payload.get("ok")),
                "samples": poll_payload.get("samples"),
                "at": poll_payload.get("at"),
            }
    except Exception:
        pass
    if os.environ.get("OFDD_HEALTH_VERBOSE", "").strip().lower() in {"1", "true", "yes"}:
        payload["repo_root"] = str(repo_root())
        payload["workspace_dir"] = str(workspace_dir())
        payload["data_dir"] = str(data_dir())
    return payload


@router.get("/health/stack")
def health_stack(_user: dict = Depends(require_user)) -> dict:
    return stack_health()


@router.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket) -> None:
    """Push stack health + check-engine status for live dashboard refresh."""
    from .. import auth
    from ..security import auth_dev_bypass_enabled, auth_strict_configured

    token = websocket.query_params.get("token") or ""
    if not token:
        header = websocket.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if auth_strict_configured():
        if auth.verify_token(token) is None:
            await websocket.close(code=4401)
            return
    elif not auth_dev_bypass_enabled():
        await websocket.close(code=4503)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(dashboard_snapshot())
            await asyncio.sleep(_ws_interval_sec())
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close()


@router.get("/api/audit/summary")
def audit_summary(_user: dict = Depends(require_roles("integrator"))) -> dict:
    from ..audit import audit_log_path, error_log_path

    audit_path = audit_log_path()
    error_path = error_log_path()
    return {
        "ok": True,
        "audit_log": str(audit_path),
        "audit_bytes": audit_path.stat().st_size if audit_path.is_file() else 0,
        "error_log": str(error_path),
        "error_bytes": error_path.stat().st_size if error_path.is_file() else 0,
    }
