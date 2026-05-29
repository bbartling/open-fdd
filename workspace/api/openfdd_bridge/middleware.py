"""Request audit middleware and global error logging."""

from __future__ import annotations

import uuid
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .audit import write_audit, write_error

_AUDIT_PREFIXES = (
    "/api/bacnet/write",
    "/api/bacnet/discover",
    "/api/bacnet/whois",
    "/api/bacnet/point-discovery",
    "/api/bacnet/supervisory-check",
    "/ingest/",
)


def _should_audit(path: str, method: str) -> bool:
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return any(path.startswith(p) for p in _AUDIT_PREFIXES)
    return False


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        path = request.url.path
        if _should_audit(path, request.method):
            user = getattr(request.state, "user", None)
            outcome = "success" if response.status_code < 400 else "failure"
            severity = "info" if outcome == "success" else "warning"
            event_type = "api.access"
            if path.startswith("/api/bacnet/write"):
                event_type = "bacnet.command"
            elif path.startswith("/api/bacnet"):
                event_type = "bacnet.discover"
            write_audit(
                event_type=event_type,
                action=f"{request.method} {path}",
                outcome=outcome,
                severity=severity,
                request=request,
                user=user,
                resource_type="http",
                resource_id=path,
                detail={"status_code": response.status_code},
                request_id=request_id,
            )
        return response


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    user = getattr(request.state, "user", None)
    write_error(
        message="unhandled exception",
        exc=exc,
        request=request,
        user=user,
        context={"request_id": getattr(request.state, "request_id", None)},
    )
    write_audit(
        event_type="error.unhandled",
        action="exception",
        outcome="failure",
        severity="error",
        request=request,
        user=user,
        detail={"exception_type": type(exc).__name__, "message": str(exc)[:500]},
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
