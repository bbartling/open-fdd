from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginBody) -> dict:
    if not auth.check_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = auth.issue_token(body.username)
    return {
        "token": token,
        "username": body.username,
        "auth_required": auth.auth_enabled(),
    }


@router.get("/status")
def status() -> dict:
    return {"auth_required": auth.auth_enabled()}
