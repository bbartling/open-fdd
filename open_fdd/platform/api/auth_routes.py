"""Auth endpoints for Phase 1 login + refresh."""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request, Response, status

from open_fdd.platform.api.auth import (
    auth_user_config_status,
    create_access_token,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_user_password,
)
from open_fdd.platform.config import get_platform_settings

router = APIRouter(prefix="/auth", tags=["auth"])
_REFRESH_COOKIE = "ofdd_refresh_token"
# Do not let browsers or intermediaries cache responses that contain access tokens.
_CACHE_CONTROL_AUTH = "no-store, no-cache, must-revalidate, private"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


def _cookie_secure(request: Request) -> bool:
    return request.url.scheme == "https"


def _set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    settings = get_platform_settings()
    max_age = int(getattr(settings, "refresh_token_days", 7) or 7) * 24 * 60 * 60
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
        max_age=max_age,
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response):
    app_user_auth_enabled, app_user_auth_error = auth_user_config_status()
    if app_user_auth_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_CONFIG_ERROR", "message": app_user_auth_error},
        )
    if not app_user_auth_enabled:
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
    _set_refresh_cookie(response, refresh_token, request)
    response.headers["Cache-Control"] = _CACHE_CONTROL_AUTH
    return LoginResponse(access_token=access_token, expires_in=expires_in)


@router.post("/refresh", response_model=RefreshResponse)
def refresh(request: Request, response: Response):
    refresh_cookie = request.cookies.get(_REFRESH_COOKIE)
    if not refresh_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or expired refresh token"},
        )
    rotated = rotate_refresh_token(refresh_cookie)
    if not rotated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or expired refresh token"},
        )
    sub, new_refresh_token = rotated
    _set_refresh_cookie(response, new_refresh_token, request)
    access_token, expires_in = create_access_token(sub)
    response.headers["Cache-Control"] = _CACHE_CONTROL_AUTH
    return RefreshResponse(access_token=access_token, expires_in=expires_in)


@router.post("/logout")
def logout(request: Request, response: Response):
    refresh_cookie = request.cookies.get(_REFRESH_COOKIE)
    revoke_refresh_token(refresh_cookie)
    _clear_refresh_cookie(response, request)
    response.headers["Cache-Control"] = _CACHE_CONTROL_AUTH
    return {"ok": True}
