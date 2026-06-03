from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, SecretStr

from .. import auth
from ..audit import write_audit
from ..deps import public_auth_status, require_user
from ..security import auth_dev_bypass_enabled, auth_strict_configured, clients_must_authenticate

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: SecretStr


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict:
    if not auth_strict_configured():
        if auth_dev_bypass_enabled():
            user = {"sub": body.username or "dev", "role": "operator"}
            request.state.user = user
            return {
                "token": "open",
                "username": user["sub"],
                "role": "operator",
                **public_auth_status(),
            }
        raise HTTPException(
            status_code=503,
            detail="authentication not configured — set OFDD_AUTH_SECRET and role passwords",
        )
    role = auth.check_credentials(body.username, body.password.get_secret_value())
    if role is None:
        write_audit(
            event_type="auth.login.failure",
            action="login",
            outcome="failure",
            severity="warning",
            request=request,
            user={"sub": body.username, "role": "unknown"},
            resource_type="session",
            detail={"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = auth.issue_token(body.username, role)
    user = {"sub": body.username, "role": role}
    request.state.user = user
    write_audit(
        event_type="auth.login.success",
        action="login",
        outcome="success",
        request=request,
        user=user,
        resource_type="session",
        detail={"role": role},
    )
    return {
        "token": token,
        "username": body.username,
        "role": role,
        **public_auth_status(),
    }


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    return {
        "username": user.get("sub"),
        "role": user.get("role"),
        **public_auth_status(),
    }


@router.get("/status")
def status() -> dict:
    return {
        "ok": True,
        **public_auth_status(),
        "roles": auth.user_roles(),
    }
