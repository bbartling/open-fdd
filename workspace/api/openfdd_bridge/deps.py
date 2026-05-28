from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from . import auth


def require_user(request: Request) -> dict:
    if not auth.auth_enabled():
        return {"sub": "open"}
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    payload = auth.verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return payload
