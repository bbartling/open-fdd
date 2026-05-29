from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from . import auth


def require_user(request: Request) -> dict:
    if not auth.auth_enabled():
        user = {"sub": "open", "role": "integrator"}
        request.state.user = user
        return user
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    payload = auth.verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    request.state.user = payload
    return payload


def require_roles(*allowed: auth.Role):
    def _dep(user: dict = Depends(require_user)) -> dict:
        if not auth.role_allows(user.get("role"), allowed):
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep
