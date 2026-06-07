"""Docker image tags / build IDs for operator troubleshooting."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from . import __version__ as bridge_version
from .commission_client import commission_base_url, commission_health


def _env_rev() -> dict[str, str]:
    return {
        "image_tag": os.environ.get("OPENFDD_IMAGE_TAG", "local").strip() or "local",
        "git_sha": os.environ.get("OPENFDD_BUILD_GIT_SHA", "").strip() or "unknown",
        "built_at": os.environ.get("OPENFDD_BUILD_TIME", "").strip(),
    }


def _local_image_id(image: str) -> str:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            ref = out.stdout.strip()
            return ref.split(":")[-1][:12] if ":" in ref else ref[:12]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def stack_revisions(*, include_image_ids: bool = False) -> dict[str, Any]:
    """Known Open-FDD compose services and their image revision metadata."""
    tag = _env_rev()["image_tag"]
    git_sha = _env_rev()["git_sha"]
    built_at = _env_rev()["built_at"]

    services: list[dict[str, Any]] = [
        {
            "id": "bridge",
            "label": "Bridge API",
            "image": f"openfdd-bridge:{tag}",
            "api_version": bridge_version,
            "image_tag": tag,
            "git_sha": git_sha,
            "built_at": built_at,
        },
        {
            "id": "commission",
            "label": "BACnet commission",
            "image": f"openfdd-commission:{tag}",
            "image_tag": tag,
            "git_sha": git_sha,
            "built_at": built_at,
            "url": commission_base_url(),
        },
        {
            "id": "mcp_rag",
            "label": "MCP RAG",
            "image": f"openfdd-mcp-rag:{tag}",
            "image_tag": tag,
            "git_sha": git_sha,
            "built_at": built_at,
        },
    ]

    code, payload = commission_health(timeout=2.0)
    if code == 200 and isinstance(payload, dict):
        for svc in services:
            if svc["id"] == "commission":
                svc["health_ok"] = bool(payload.get("ok"))
                break

    if include_image_ids:
        for svc in services:
            img = str(svc.get("image") or "")
            if img:
                svc["image_id"] = _local_image_id(img)

    return {
        "ok": True,
        "image_tag": tag,
        "git_sha": git_sha,
        "built_at": built_at,
        "services": services,
    }
