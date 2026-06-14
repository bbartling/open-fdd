"""HTTP security headers for the operator SPA.

Caddy (reverse proxy) must NOT set overlapping headers — bridge middleware owns
Referrer-Policy, X-Frame-Options, CSP, COOP, CORP, and Permissions-Policy.
Caddy TLS mode may add Strict-Transport-Security only.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Plotly + Vite SPA: hashed JS/CSS under /assets.
# style-src 'unsafe-inline' is required today — Vite/React/Plotly inject inline styles at runtime.
# Removing 'unsafe-inline' breaks trend charts and layout (verified 2026-06); migrate to nonce/hash CSP later.
_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'"
)

# COEP omitted — require-corp breaks third-party/static embeds; add only after asset audit.
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": _CSP,
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _cache_control_for_path(path: str) -> str | None:
    """Sensitive API/auth/data responses must not be cached by browsers or proxies."""
    if path.startswith("/api/"):
        return "no-store"
    if path in {"/health/stack", "/health/revisions"}:
        return "no-store"
    if path.startswith("/openfdd-agent/") and path not in {
        "/openfdd-agent/building-insight",
        "/openfdd-agent/operational-brief",
        "/openfdd-agent/zone-temps",
        "/openfdd-agent/device-poll-health",
        "/openfdd-agent/ollama/health",
    }:
        return "no-store"
    return None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> object:
        response: Response = await call_next(request)
        scheme = str(getattr(request.url, "scheme", "") or "").lower()
        for key, value in _SECURITY_HEADERS.items():
            if scheme != "https" and key in {
                "Cross-Origin-Opener-Policy",
                "Cross-Origin-Resource-Policy",
            }:
                continue
            response.headers[key] = value
        cache_control = _cache_control_for_path(request.url.path)
        if cache_control and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = cache_control
        # Avoid stacking uvicorn/Caddy Server banners on the wire.
        if "server" in response.headers:
            del response.headers["server"]
        return response
