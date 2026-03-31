"""Optional auth middleware + token helpers.

Supports:
- machine token: OFDD_API_KEY (legacy integrations)
- user login: short-lived JWT access tokens (Phase 1 auth)
"""

import datetime as dt
import hashlib
import logging
import secrets
from threading import Lock
from typing import Callable

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from open_fdd.platform.config import get_platform_settings

logger = logging.getLogger(__name__)

_PATHS_NO_AUTH = frozenset(("/", "/health", "/docs", "/redoc", "/openapi.json"))
_ph = PasswordHasher()
_refresh_store: dict[str, dict[str, dt.datetime | str]] = {}
_refresh_lock = Lock()


def _path_exempt(path: str) -> bool:
    if path in _PATHS_NO_AUTH:
        return True
    if path == "/app" or path.startswith("/app/"):
        return True
    if path.startswith("/auth/"):
        return True
    return False


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:].strip()


def _jwt_secret() -> str:
    settings = get_platform_settings()
    secret = getattr(settings, "jwt_secret", None) or getattr(settings, "api_key", None)
    if secret:
        return str(secret)
    return "openfdd-dev-secret-change-me"


def _token_subject(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
        if payload.get("typ") != "access":
            return None
        return str(payload.get("sub", ""))
    except Exception:
        return None


def validate_access_token(token: str | None) -> bool:
    return bool(token and _token_subject(token))


def verify_user_password(username: str, password: str) -> bool:
    settings = get_platform_settings()
    app_user = (getattr(settings, "app_user", None) or "").strip()
    app_hash = (getattr(settings, "app_user_hash", None) or "").strip()
    if not app_user or not app_hash:
        return False
    if username.strip() != app_user:
        return False
    try:
        return _ph.verify(app_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_access_token(username: str) -> tuple[str, int]:
    settings = get_platform_settings()
    ttl_min = int(getattr(settings, "access_token_minutes", 60) or 60)
    now = dt.datetime.now(dt.timezone.utc)
    exp = now + dt.timedelta(minutes=ttl_min)
    payload = {
        "sub": username,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256"), ttl_min * 60


def issue_refresh_token(username: str) -> str:
    settings = get_platform_settings()
    ttl_days = int(getattr(settings, "refresh_token_days", 7) or 7)
    token = secrets.token_urlsafe(48)
    now = dt.datetime.now(dt.timezone.utc)
    with _refresh_lock:
        _refresh_store[token] = {
            "sub": username,
            "exp": now + dt.timedelta(days=ttl_days),
        }
    return token


def verify_refresh_token(refresh_token: str) -> str | None:
    now = dt.datetime.now(dt.timezone.utc)
    with _refresh_lock:
        entry = _refresh_store.get(refresh_token)
        # best-effort cleanup while we're here
        stale = [k for k, v in _refresh_store.items() if now >= v["exp"]]
        for k in stale:
            _refresh_store.pop(k, None)
    if not entry:
        return None
    if now >= entry["exp"]:
        return None
    return str(entry["sub"])


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    When OFDD_API_KEY is set, require Authorization: Bearer <key> on all requests
    except /, /health, /docs, /redoc, /openapi.json, and /app (and /app/*).
    Returns 401/403 with uniform error schema when auth fails.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if _path_exempt(request.url.path):
            return await call_next(request)
        settings = get_platform_settings()
        # Trust requests that Caddy already authenticated (Basic auth); Caddy sets X-Caddy-Auth when auth succeeded.
        caddy_secret = getattr(settings, "caddy_internal_secret", None)
        x_caddy = request.headers.get("X-Caddy-Auth") or request.headers.get(
            "x-caddy-auth"
        )
        if caddy_secret and x_caddy == caddy_secret:
            return await call_next(request)
        api_key = getattr(settings, "api_key", None)
        app_user = getattr(settings, "app_user", None)
        app_hash = getattr(settings, "app_user_hash", None)
        auth_required = bool(api_key or (app_user and app_hash))
        if not auth_required:
            return await call_next(request)
        token = _bearer_token(request)
        if not token:
            logger.info(
                "auth 401 path=%s caddy_secret_set=%s x_caddy_auth=%s",
                request.url.path,
                bool(caddy_secret),
                "present" if x_caddy else "missing",
            )
            return Response(
                content='{"error":{"code":"UNAUTHORIZED","message":"Missing or invalid Authorization header","details":null}}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="application/json",
            )
        # Machine auth path (legacy integrations) still accepted.
        if api_key and secrets.compare_digest(token, str(api_key)):
            return await call_next(request)
        # User access-token path.
        if validate_access_token(token):
            return await call_next(request)
        # Avoid leaking whether this was close to a valid token.
        token_fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "auth 403 path=%s token_sha12=%s",
            request.url.path,
            token_fingerprint,
        )
        return Response(
            content='{"error":{"code":"FORBIDDEN","message":"Invalid auth token","details":null}}',
            status_code=status.HTTP_403_FORBIDDEN,
            media_type="application/json",
        )
