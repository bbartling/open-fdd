"""Deployment security helpers (auth bind mode, CORS, diagnostics)."""

from __future__ import annotations

import logging
import os

from .settings import bridge_host

_log = logging.getLogger(__name__)

_LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PUBLIC_BIND_HOSTS = frozenset({"0.0.0.0", "::"})


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def bridge_bind_is_localhost_only() -> bool:
    return bridge_host() in _LOCAL_BIND_HOSTS


def bridge_bind_is_public() -> bool:
    return bridge_host() in _PUBLIC_BIND_HOSTS


def insecure_lan_dev_allowed() -> bool:
    """Explicit scary opt-in for unauthenticated API on non-loopback binds."""
    return _env_flag("OFDD_INSECURE_LAN_DEV") or _env_flag("OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV")


def auth_strict_configured() -> bool:
    from . import auth

    return auth.credentials_configured()


def auth_dev_bypass_enabled() -> bool:
    """Explicit dev-only open mode — never implied by missing env vars."""
    if not _env_flag("OFDD_AUTH_DISABLED"):
        return False
    if insecure_lan_dev_allowed():
        return True
    return bridge_bind_is_localhost_only()


def clients_must_authenticate() -> bool:
    """True when API clients need a valid Bearer token (or login)."""
    if auth_strict_configured():
        return True
    return not auth_dev_bypass_enabled()


def debug_tracebacks_enabled() -> bool:
    return _env_flag("OFDD_DEBUG_TRACEBACKS")


def debug_diagnostics_enabled() -> bool:
    return _env_flag("OFDD_DEBUG_DIAGNOSTICS")


def public_dashboard_ws_allowed() -> bool:
    """Allow unauthenticated /ws/dashboard (redacted snapshot only)."""
    return _env_flag("OFDD_PUBLIC_DASHBOARD_WS")


def bacnet_writes_enabled() -> bool:
    return _env_flag("OFDD_ENABLE_BACNET_WRITE")


def startup_auth_error_message() -> str:
    host = bridge_host()
    return (
        f"Open-FDD bridge cannot start: bind={host} exposes the Operator API without "
        f"authentication.\n"
        "Fix one of:\n"
        "  • Configure auth: OFDD_AUTH_SECRET plus OFDD_OPERATOR_USER/PASSWORD and "
        "OFDD_INTEGRATOR_USER/PASSWORD (see workspace/auth.env.local)\n"
        "  • Loopback dev only: OFDD_BRIDGE_HOST=127.0.0.1 with OFDD_AUTH_DISABLED=1\n"
        "  • Lab/LAN demo only (insecure): OFDD_AUTH_DISABLED=1 and OFDD_INSECURE_LAN_DEV=1 "
        "(or OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV=1)"
    )


def validate_startup_auth() -> None:
    """Fail closed when a LAN-facing bridge has no auth configured."""
    if auth_strict_configured():
        return
    if auth_dev_bypass_enabled():
        _log.warning(
            "OFDD_AUTH_DISABLED is active (dev bypass). bind=%s — not for production OT edges.",
            bridge_host(),
        )
        return
    msg = startup_auth_error_message()
    if bridge_bind_is_public():
        raise RuntimeError(msg)
    if _env_flag("OFDD_AUTH_STRICT_STARTUP"):
        raise RuntimeError(msg)
    _log.warning(msg)
