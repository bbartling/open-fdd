"""LAN-only Bearer auth with operator / integrator / agent roles."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Literal

Role = Literal["operator", "integrator", "agent"]

_SECRET = os.environ.get("OFDD_AUTH_SECRET", "").strip()

ROLES: tuple[Role, ...] = ("operator", "integrator", "agent")

_DEV_USER = {"sub": "dev", "role": "operator", "exp": 0}

_BEARER_TYP = "bearer"
_BEARER_VER = 1
_WS_TICKET_TYP = "ws"

# Replay protection is in-process only — safe for single-worker uvicorn; multi-worker
# deployments need shared ticket state (Redis/SQLite). See workspace/deploy/SECURITY.md.
_used_ws_tickets: dict[str, float] = {}


_DEFAULT_TOKEN_TTL_SEC = 8 * 3600  # 8h — safer default for OT operator dashboards
_MAX_TOKEN_TTL_SEC = 7 * 86400
_DEV_MAX_TOKEN_TTL_SEC = 365 * 86400


def _parse_token_ttl() -> int:
    raw = os.environ.get("OFDD_AUTH_TTL_SEC", "").strip()
    default = _DEFAULT_TOKEN_TTL_SEC
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    value = max(1, value)
    from .security import is_production_env

    allow_long = os.environ.get("OFDD_AUTH_TTL_ALLOW_LONG", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if allow_long and is_production_env():
        import logging

        logging.getLogger(__name__).warning(
            "OFDD_AUTH_TTL_ALLOW_LONG is ignored when OFDD_ENV=production — capping at %ss",
            _MAX_TOKEN_TTL_SEC,
        )
        allow_long = False
    cap = _DEV_MAX_TOKEN_TTL_SEC if allow_long else _MAX_TOKEN_TTL_SEC
    clamped = min(value, cap)
    if value > cap:
        import logging

        logging.getLogger(__name__).warning(
            "OFDD_AUTH_TTL_SEC=%s exceeds cap (%ss); clamped to %ss. "
            "Set OFDD_AUTH_TTL_ALLOW_LONG=1 only for local development.",
            value,
            cap,
            clamped,
        )
    return clamped


def token_ttl_seconds() -> int:
    return _TOKEN_TTL_SEC


_TOKEN_TTL_SEC = _parse_token_ttl()


def _password_hash_keys(role: Role) -> tuple[str, str]:
    if role == "operator":
        return "OFDD_OPERATOR_PASSWORD_HASH", "OFDD_OPERATOR_PASSWORD"
    if role == "integrator":
        return "OFDD_INTEGRATOR_PASSWORD_HASH", "OFDD_INTEGRATOR_PASSWORD"
    return "OFDD_AGENT_PASSWORD_HASH", "OFDD_AGENT_PASSWORD"


def _verify_password(password: str, stored: str) -> bool:
    """Compare plaintext or bcrypt hash ($2a$ / $2b$)."""
    if stored.startswith("$2a$") or stored.startswith("$2b$") or stored.startswith("$2y$"):
        try:
            import bcrypt
        except ImportError:
            return False
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(password, stored)


def _load_users() -> dict[str, tuple[str, Role]]:
    """username -> (password or bcrypt hash, role). Legacy OFDD_WEB_* maps to operator."""
    users: dict[str, tuple[str, Role]] = {}

    def _add(
        role: Role,
        user_key: str,
        pass_key: str,
        *,
        legacy_user: str = "",
        legacy_pass: str = "",
    ) -> None:
        user = os.environ.get(user_key, "").strip() or legacy_user.strip()
        hash_key, plain_key = _password_hash_keys(role)
        stored = os.environ.get(hash_key, "").strip()
        if not stored:
            stored = os.environ.get(pass_key, "").strip() or legacy_pass.strip()
        if user and stored:
            users[user] = (stored, role)

    _add(
        "operator",
        "OFDD_OPERATOR_USER",
        "OFDD_OPERATOR_PASSWORD",
        legacy_user=os.environ.get("OFDD_WEB_USER", ""),
        legacy_pass=os.environ.get("OFDD_WEB_PASSWORD", ""),
    )
    _add("integrator", "OFDD_INTEGRATOR_USER", "OFDD_INTEGRATOR_PASSWORD")
    _add("agent", "OFDD_AGENT_USER", "OFDD_AGENT_PASSWORD")
    return users


def credentials_configured() -> bool:
    return bool(_SECRET and _load_users())


def auth_enabled() -> bool:
    """True when the deployment accepts API traffic (configured auth or explicit dev bypass)."""
    from .security import auth_dev_bypass_enabled

    return credentials_configured() or auth_dev_bypass_enabled()


def user_roles() -> list[str]:
    if not credentials_configured():
        return []
    return sorted({role for _, role in _load_users().values()})


_DUMMY_PASSWORD = "invalid-credential-placeholder"


def check_credentials(username: str, password: str) -> Role | None:
    if not credentials_configured():
        from .security import auth_dev_bypass_enabled

        if auth_dev_bypass_enabled():
            return "operator"
        return None
    users = _load_users()
    key = username.strip()
    entry = users.get(key) or users.get(key.lower())
    if entry:
        expected_password, role = entry
    else:
        expected_password = _DUMMY_PASSWORD
        role = None
    if not _verify_password(password, expected_password):
        return None
    return role


def issue_token(username: str, role: Role) -> str:
    if not credentials_configured():
        raise RuntimeError("cannot issue token without OFDD_AUTH_SECRET and user passwords")
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "typ": _BEARER_TYP,
        "ver": _BEARER_VER,
        "iat": now,
        "exp": now + _TOKEN_TTL_SEC,
    }
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{body}.{sig_b64}"


def verify_token(token: str | None) -> dict[str, Any] | None:
    from .security import auth_dev_bypass_enabled

    if not credentials_configured():
        if auth_dev_bypass_enabled() and (not token or token == "open"):
            return dict(_DEV_USER)
        return None
    if not token or "." not in token:
        return None
    body, sig_b64 = token.split(".", 1)
    expected = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    try:
        got = base64.urlsafe_b64decode(sig_b64 + "==")
    except Exception:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except (json.JSONDecodeError, ValueError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    typ = payload.get("typ")
    if typ == _WS_TICKET_TYP:
        return None
    if typ is not None and typ != _BEARER_TYP:
        return None
    role = payload.get("role")
    if role not in ROLES:
        payload["role"] = "operator"
    return payload


def _prune_used_ws_tickets(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    expired = [jti for jti, exp in _used_ws_tickets.items() if exp < ts]
    for jti in expired:
        _used_ws_tickets.pop(jti, None)


def _ws_ticket_ttl_sec() -> int:
    raw = os.environ.get("OFDD_WS_TICKET_TTL_SEC", "").strip()
    default = 120
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(30, min(value, 600))


def issue_ws_ticket(username: str, role: Role) -> tuple[str, int]:
    """Short-lived WebSocket ticket (not the long-lived Bearer token)."""
    ttl = _ws_ticket_ttl_sec()
    if not credentials_configured():
        from .security import auth_dev_bypass_enabled

        if auth_dev_bypass_enabled():
            return "dev", ttl
        raise RuntimeError("cannot issue WebSocket ticket without OFDD_AUTH_SECRET")
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "typ": _WS_TICKET_TYP,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl,
    }
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{body}.{sig_b64}", ttl


def verify_ws_ticket(ticket: str | None) -> dict[str, Any] | None:
    from .security import auth_dev_bypass_enabled

    if not ticket or not ticket.strip():
        return None
    ticket = ticket.strip()
    if not credentials_configured():
        if auth_dev_bypass_enabled() and ticket == "dev":
            return dict(_DEV_USER)
        return None
    if "." not in ticket:
        return None
    body, sig_b64 = ticket.split(".", 1)
    expected = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    try:
        got = base64.urlsafe_b64decode(sig_b64 + "==")
    except Exception:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except (json.JSONDecodeError, ValueError):
        return None
    if payload.get("typ") != _WS_TICKET_TYP:
        return None
    now = int(time.time())
    if int(payload.get("exp", 0)) < now:
        return None
    jti = str(payload.get("jti") or "").strip()
    if jti:
        _prune_used_ws_tickets(now)
        if jti in _used_ws_tickets:
            return None
        _used_ws_tickets[jti] = float(payload.get("exp", now))
    role = payload.get("role")
    if role not in ROLES:
        payload["role"] = "operator"
    return payload


def role_allows(role: str | None, allowed: tuple[Role, ...]) -> bool:
    if not credentials_configured():
        from .security import auth_dev_bypass_enabled

        if auth_dev_bypass_enabled():
            return role in allowed
        return False
    return role in allowed
