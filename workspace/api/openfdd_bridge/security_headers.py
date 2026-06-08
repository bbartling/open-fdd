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
# TODO: remove style-src 'unsafe-inline' after migrating inline styles to hashed CSS
# modules or nonce-based CSP (Vite/React style injection currently requires unsafe-inline).
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> object:
        response: Response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers[key] = value
        # Avoid stacking uvicorn/Caddy Server banners on the wire.
        if "server" in response.headers:
            del response.headers["server"]
        return response
