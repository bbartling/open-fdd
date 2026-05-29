from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from .. import auth
from ..deps import require_roles, require_user
from ..paths import bacnet_poll_csv, data_dir, repo_root, workspace_dir
from ..stack_health import stack_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    payload: dict = {
        "ok": True,
        "service": "openfdd-bridge",
        "auth_required": auth.auth_enabled(),
        "bacnet_poll_csv_exists": bacnet_poll_csv().is_file(),
    }
    if os.environ.get("OFDD_HEALTH_VERBOSE", "").strip().lower() in {"1", "true", "yes"}:
        payload["repo_root"] = str(repo_root())
        payload["workspace_dir"] = str(workspace_dir())
        payload["data_dir"] = str(data_dir())
    return payload


@router.get("/health/stack")
def health_stack(_user: dict = Depends(require_user)) -> dict:
    return stack_health()


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
