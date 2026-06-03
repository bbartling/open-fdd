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


def auth_strict_configured() -> bool:
    from . import auth

    return auth.credentials_configured()


def auth_dev_bypass_enabled() -> bool:
    """Explicit dev-only open mode — never implied by missing env vars."""
    if not _env_flag("OFDD_AUTH_DISABLED"):
        return False
    if _env_flag("OFDD_INSECURE_LAN_DEV"):
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


def bacnet_writes_enabled() -> bool:
    return _env_flag("OFDD_ENABLE_BACNET_WRITE")


def validate_startup_auth() -> None:
    """Warn or fail when a LAN-facing bridge has no auth configured."""
    if auth_strict_configured():
        return
    if auth_dev_bypass_enabled():
        _log.warning(
            "OFDD_AUTH_DISABLED is active (dev bypass). Bind=%s — do not use on production OT edges.",
            bridge_host(),
        )
        return
    msg = (
        f"Open-FDD bridge has no authentication configured (set OFDD_AUTH_SECRET and "
        f"OFDD_*_USER/PASSWORD). bind={bridge_host()} requires auth or explicit "
        f"OFDD_AUTH_DISABLED=1 with localhost-only bind (or OFDD_INSECURE_LAN_DEV=1 for lab)."
    )
    if _env_flag("OFDD_AUTH_STRICT_STARTUP"):
        raise RuntimeError(msg)
    if bridge_bind_is_public():
        _log.error(msg)
    else:
        _log.warning(msg)
