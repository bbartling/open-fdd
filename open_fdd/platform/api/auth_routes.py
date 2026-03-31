"""Auth endpoints for Phase 1 login + refresh."""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status

from open_fdd.platform.api.auth import (
    create_access_token,
    issue_refresh_token,
    verify_refresh_token,
    verify_user_password,
)
from open_fdd.platform.config import get_platform_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=8, max_length=512)


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    settings = get_platform_settings()
    if not getattr(settings, "app_user", None) or not getattr(
        settings, "app_user_hash", None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_NOT_CONFIGURED",
                "message": "App user is not configured. Run bootstrap with --user and --password.",
            },
        )
    if not verify_user_password(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid username or password"},
        )
    access_token, expires_in = create_access_token(body.username)
    refresh_token = issue_refresh_token(body.username)
    return LoginResponse(
        access_token=access_token, refresh_token=refresh_token, expires_in=expires_in
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(body: RefreshRequest):
    sub = verify_refresh_token(body.refresh_token)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or expired refresh token"},
        )
    access_token, expires_in = create_access_token(sub)
    return RefreshResponse(access_token=access_token, expires_in=expires_in)
