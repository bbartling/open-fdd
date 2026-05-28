from __future__ import annotations

from fastapi import APIRouter

from .. import auth
from ..paths import bacnet_poll_csv, data_dir, repo_root, workspace_dir

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "openfdd-bridge",
        "repo_root": str(repo_root()),
        "workspace_dir": str(workspace_dir()),
        "data_dir": str(data_dir()),
        "auth_required": auth.auth_enabled(),
        "bacnet_poll_csv_exists": bacnet_poll_csv().is_file(),
    }
