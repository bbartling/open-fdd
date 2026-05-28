from __future__ import annotations

import os

from fastapi import APIRouter

from .. import auth
from ..paths import bacnet_poll_csv, data_dir, repo_root, workspace_dir

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
