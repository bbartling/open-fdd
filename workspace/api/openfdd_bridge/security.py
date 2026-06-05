"""Deployment security helpers (auth bind mode, CORS, diagnostics)."""

from __future__ import annotations

import ipaddress
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
    """True when the API is reachable off-loopback (wildcard, LAN IP, or hostname)."""
    host = bridge_host().strip().lower()
    if host in _LOCAL_BIND_HOSTS:
        return False
    if host in _PUBLIC_BIND_HOSTS:
        return True
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


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


_AUTH_SECRET_MIN_LEN = 32


def validate_auth_secret_strength() -> None:
    """Reject weak secrets on LAN/edge binds; warn on localhost dev."""
    from . import auth

    secret = os.environ.get("OFDD_AUTH_SECRET", "").strip()
    if not secret or not auth.credentials_configured():
        return
    if len(secret) >= _AUTH_SECRET_MIN_LEN:
        return
    msg = (
        f"OFDD_AUTH_SECRET is shorter than {_AUTH_SECRET_MIN_LEN} characters — "
        "use a long random secret for LAN/edge deployments."
    )
    if bridge_bind_is_public() or not bridge_bind_is_localhost_only():
        raise RuntimeError(msg)
    _log.warning(msg)


def inprocess_playground_allowed() -> bool:
    if not _env_flag("OFDD_PLAYGROUND_INPROCESS"):
        return False
    if bridge_bind_is_localhost_only():
        return True
    return insecure_lan_dev_allowed()


def ws_allow_query_ticket() -> bool:
    return _env_flag("OFDD_WS_ALLOW_QUERY_TICKET")


def bacnet_write_allow_any() -> bool:
    return _env_flag("OFDD_BACNET_WRITE_ALLOW_ANY")


def operator_can_bacnet_discover() -> bool:
    return _env_flag("OFDD_OPERATOR_CAN_BACNET_DISCOVER")


def agent_can_bacnet_mutate() -> bool:
    return _env_flag("OFDD_AGENT_CAN_BACNET_MUTATE")


def bacnet_discovery_mutations_enabled() -> bool:
    return _env_flag("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS")


def operator_can_edit_model() -> bool:
    return _env_flag("OFDD_OPERATOR_CAN_EDIT_MODEL")


def agent_public_insight_allowed() -> bool:
    return _env_flag("OFDD_AGENT_PUBLIC_INSIGHT") or _env_flag("OFDD_AGENT_PUBLIC_DEMO")


def audit_log_prompts_enabled() -> bool:
    return _env_flag("OFDD_AUDIT_LOG_PROMPTS")


def validate_startup_auth() -> None:
    """Fail closed when a LAN-facing bridge has no auth configured."""
    validate_auth_secret_strength()
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
