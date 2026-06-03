from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from . import auth
from .security import auth_dev_bypass_enabled, auth_strict_configured, clients_must_authenticate


def require_user(request: Request) -> dict:
    if auth_strict_configured():
        header = request.headers.get("authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        payload = auth.verify_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        request.state.user = payload
        return payload
    if auth_dev_bypass_enabled():
        user = dict(auth._DEV_USER)  # noqa: SLF001 — dev-only operator role
        request.state.user = user
        return user
    raise HTTPException(
        status_code=503,
        detail="authentication not configured — set OFDD_AUTH_SECRET and role passwords",
    )


def require_roles(*allowed: auth.Role):
    def _dep(user: dict = Depends(require_user)) -> dict:
        if not auth.role_allows(user.get("role"), allowed):
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep


def public_auth_status() -> dict[str, bool]:
    return {
        "auth_required": clients_must_authenticate(),
        "auth_configured": auth_strict_configured(),
        "auth_dev_bypass": auth_dev_bypass_enabled(),
    }
