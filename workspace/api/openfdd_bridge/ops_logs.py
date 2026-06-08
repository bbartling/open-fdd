"""Operational log tail — bridge error/audit JSONL + optional Docker Compose services."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .audit import audit_log_path, error_log_path, tail_jsonl

_ALLOWED_SERVICES = frozenset({"bridge", "commission", "mcp-rag", "ollama", "caddy"})
_ERROR_PAT = re.compile(
    r"(error|exception|traceback|failed|fatal|panic|crit)",
    re.IGNORECASE,
)


def _compose_dir() -> Path | None:
    raw = os.environ.get("OFDD_OPS_DOCKER_COMPOSE_DIR", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_dir() else None
    for candidate in (
        Path("/host/open-fdd"),
        Path.home() / "open-fdd",
    ):
        if (candidate / "docker-compose.yml").is_file():
            return candidate
    return None


def _docker_available() -> bool:
    if os.environ.get("OFDD_OPS_DOCKER_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _tail_compose_logs(*, service: str, tail: int) -> dict[str, Any]:
    compose_dir = _compose_dir()
    if compose_dir is None:
        return {"available": False, "reason": "compose dir not found (set OFDD_OPS_DOCKER_COMPOSE_DIR)"}
    if not _docker_available():
        return {"available": False, "reason": "docker CLI unavailable in bridge container"}
    svc = service if service in _ALLOWED_SERVICES else "bridge"
    cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_dir / "docker-compose.yml"),
        "logs",
        "--no-color",
        "--tail",
        str(max(10, min(tail, 500))),
        svc,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(compose_dir),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc)[:200]}
    lines = (proc.stdout or "").splitlines()
    error_lines = [ln for ln in lines if _ERROR_PAT.search(ln)]
    return {
        "available": True,
        "service": svc,
        "exit_code": proc.returncode,
        "line_count": len(lines),
        "error_line_count": len(error_lines),
        "lines": lines[-tail:],
        "error_lines": error_lines[:40],
        "compose_dir": str(compose_dir),
    }


def collect_ops_logs(
    *,
    tail: int = 80,
    service: str = "bridge",
    include_audit: bool = True,
    include_errors: bool = True,
    include_docker: bool = True,
) -> dict[str, Any]:
    """Aggregate log tails for remote agent triage (Tailscale API, no SSH)."""
    tail = max(10, min(int(tail), 500))
    out: dict[str, Any] = {"ok": True, "tail": tail}

    if include_errors:
        err_rows = tail_jsonl(error_log_path(), limit=tail)
        out["bridge_errors"] = {
            "path": str(error_log_path()),
            "count": len(err_rows),
            "events": err_rows,
            "severity_error_count": sum(
                1 for e in err_rows if str(e.get("severity") or "").lower() in {"error", "critical"}
            ),
        }

    if include_audit:
        audit_rows = tail_jsonl(audit_log_path(), limit=min(tail, 200))
        agent_events = [
            e
            for e in audit_rows
            if str(e.get("event_type") or "") in {"agent.tool", "api.error"}
            or str(e.get("outcome") or "") == "failure"
        ]
        out["bridge_audit"] = {
            "path": str(audit_log_path()),
            "count": len(audit_rows),
            "agent_or_failure_count": len(agent_events),
            "recent": agent_events[:30],
        }

    if include_docker:
        out["docker_compose"] = _tail_compose_logs(service=service, tail=tail)

    err_n = int((out.get("bridge_errors") or {}).get("severity_error_count") or 0)
    docker_err = int((out.get("docker_compose") or {}).get("error_line_count") or 0)
    out["summary"] = {
        "has_bridge_errors": err_n > 0,
        "bridge_error_count": err_n,
        "docker_error_lines": docker_err,
        "healthy": err_n == 0 and docker_err == 0,
    }
    return out
