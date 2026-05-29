"""Structured audit and error logs (JSON Lines) for OT security / forensics."""

from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import workspace_dir

_SEVERITIES = frozenset({"debug", "info", "notice", "warning", "error", "critical"})


def _logs_dir() -> Path:
    root = workspace_dir() / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def audit_log_path() -> Path:
    override = os.environ.get("OFDD_AUDIT_LOG_PATH", "").strip()
    if override:
        p = Path(override)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return _logs_dir() / "audit.jsonl"


def error_log_path() -> Path:
    override = os.environ.get("OFDD_ERROR_LOG_PATH", "").strip()
    if override:
        p = Path(override)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return _logs_dir() / "error.jsonl"


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, separators=(",", ":"), default=str)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _base_record(
    *,
    event_type: str,
    severity: str,
    outcome: str,
    action: str,
    service: str = "openfdd-bridge",
) -> dict[str, Any]:
    sev = severity if severity in _SEVERITIES else "info"
    return {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "severity": sev,
        "outcome": outcome,
        "service": service,
        "host": _hostname(),
        "action": action,
    }


def client_from_request(request: Any | None) -> dict[str, str]:
    if request is None:
        return {"ip": "", "user_agent": ""}
    ip = ""
    if getattr(request, "client", None):
        ip = request.client.host or ""
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        ip = forwarded.split(",")[0].strip() or ip
    return {
        "ip": ip,
        "user_agent": (request.headers.get("user-agent") or "")[:512],
    }


def actor_from_user(user: dict[str, Any] | None) -> dict[str, str]:
    if not user:
        return {"username": "anonymous", "role": "none"}
    return {
        "username": str(user.get("sub") or "unknown"),
        "role": str(user.get("role") or "unknown"),
    }


def http_from_request(request: Any | None, *, status: int | None = None) -> dict[str, Any]:
    if request is None:
        return {}
    out: dict[str, Any] = {
        "method": request.method,
        "path": str(getattr(request.url, "path", "")),
    }
    if status is not None:
        out["status"] = status
    return out


def write_audit(
    *,
    event_type: str,
    action: str,
    outcome: str,
    severity: str = "info",
    request: Any | None = None,
    user: dict[str, Any] | None = None,
    resource_type: str = "",
    resource_id: str = "",
    detail: dict[str, Any] | None = None,
    service: str = "openfdd-bridge",
    request_id: str | None = None,
) -> dict[str, Any]:
    record = _base_record(
        event_type=event_type,
        severity=severity,
        outcome=outcome,
        action=action,
        service=service,
    )
    if request_id:
        record["request_id"] = request_id
    record["actor"] = actor_from_user(user)
    record["client"] = client_from_request(request)
    if request is not None:
        record["http"] = http_from_request(request)
    if resource_type:
        record["resource"] = {"type": resource_type, "id": resource_id or None}
    if detail:
        record["detail"] = _sanitize_detail(detail)
    _append_jsonl(audit_log_path(), record)
    return record


def write_error(
    *,
    message: str,
    exc: BaseException | None = None,
    request: Any | None = None,
    user: dict[str, Any] | None = None,
    service: str = "openfdd-bridge",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = _base_record(
        event_type="error.application",
        severity="error",
        outcome="failure",
        action="exception",
        service=service,
    )
    record["message"] = message[:2000]
    record["actor"] = actor_from_user(user)
    record["client"] = client_from_request(request)
    if request is not None:
        record["http"] = http_from_request(request)
    if exc is not None:
        record["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:2000],
        }
    if context:
        record["context"] = _sanitize_detail(context)
    _append_jsonl(error_log_path(), record)
    return record


def _sanitize_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Drop secrets from forensic detail payloads."""
    blocked = {
        "password",
        "token",
        "secret",
        "authorization",
        "OFDD_AUTH_SECRET",
        "private_key",
    }
    out: dict[str, Any] = {}
    for key, val in detail.items():
        lower = key.lower()
        if any(b in lower for b in blocked):
            continue
        if isinstance(val, dict):
            out[key] = _sanitize_detail(val)
        else:
            out[key] = val
    return out


def tail_jsonl(path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    if not path.is_file() or limit <= 0:
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
