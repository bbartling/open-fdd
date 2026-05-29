from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, SecretStr

from .. import auth
from ..audit import write_audit
from ..deps import require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: SecretStr


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict:
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
        "auth_required": auth.auth_enabled(),
    }


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    return {
        "username": user.get("sub"),
        "role": user.get("role"),
        "auth_required": auth.auth_enabled(),
    }


@router.get("/status")
def status() -> dict:
    return {
        "auth_required": auth.auth_enabled(),
        "roles": auth.user_roles(),
    }
