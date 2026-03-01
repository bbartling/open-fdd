"""Optional Bearer token auth when OFDD_API_KEY is set."""

from typing import Callable

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from open_fdd.platform.config import get_platform_settings

_PATHS_NO_AUTH = frozenset(("/", "/health", "/docs", "/redoc", "/openapi.json"))


def _path_exempt(path: str) -> bool:
    if path in _PATHS_NO_AUTH:
        return True
    if path == "/app" or path.startswith("/app/"):
        return True
    return False


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:].strip()


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
        api_key = getattr(settings, "api_key", None)
        if not api_key:
            return await call_next(request)
        token = _bearer_token(request)
        if not token:
            return Response(
                content='{"error":{"code":"UNAUTHORIZED","message":"Missing or invalid Authorization header","details":null}}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="application/json",
            )
        if token != api_key:
            return Response(
                content='{"error":{"code":"FORBIDDEN","message":"Invalid API key","details":null}}',
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json",
            )
        return await call_next(request)
