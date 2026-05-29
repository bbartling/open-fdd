"""LAN-only Bearer auth with operator / integrator / agent roles."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Literal

Role = Literal["operator", "integrator", "agent"]

_SECRET = os.environ.get("OFDD_AUTH_SECRET", "").strip()

ROLES: tuple[Role, ...] = ("operator", "integrator", "agent")


def _parse_token_ttl() -> int:
    raw = os.environ.get("OFDD_AUTH_TTL_SEC", "").strip()
    default = 7 * 86400
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, 365 * 86400))


_TOKEN_TTL_SEC = _parse_token_ttl()


def _load_users() -> dict[str, tuple[str, Role]]:
    """username -> (password, role). Legacy OFDD_WEB_* maps to operator."""
    users: dict[str, tuple[str, Role]] = {}

    def _add(role: Role, user_key: str, pass_key: str, legacy_user: str = "", legacy_pass: str = "") -> None:
        user = os.environ.get(user_key, "").strip() or legacy_user.strip()
        password = os.environ.get(pass_key, "").strip() or legacy_pass.strip()
        if user and password:
            users[user] = (password, role)

    _add(
        "operator",
        "OFDD_OPERATOR_USER",
        "OFDD_OPERATOR_PASSWORD",
        os.environ.get("OFDD_WEB_USER", ""),
        os.environ.get("OFDD_WEB_PASSWORD", ""),
    )
    _add("integrator", "OFDD_INTEGRATOR_USER", "OFDD_INTEGRATOR_PASSWORD")
    _add("agent", "OFDD_AGENT_USER", "OFDD_AGENT_PASSWORD")
    return users


def auth_enabled() -> bool:
    return bool(_SECRET and _load_users())


def user_roles() -> list[str]:
    if not auth_enabled():
        return []
    return sorted({role for _, role in _load_users().values()})


def check_credentials(username: str, password: str) -> Role | None:
    if not auth_enabled():
        return "operator"
    entry = _load_users().get(username.strip())
    if not entry:
        return None
    expected_password, role = entry
    if not hmac.compare_digest(password, expected_password):
        return None
    return role


def issue_token(username: str, role: Role) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + _TOKEN_TTL_SEC}
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{body}.{sig_b64}"


def verify_token(token: str | None) -> dict[str, Any] | None:
    if not auth_enabled():
        return {"sub": "open", "role": "integrator", "exp": 0}
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
    role = payload.get("role")
    if role not in ROLES:
        payload["role"] = "operator"
    return payload


def role_allows(role: str | None, allowed: tuple[Role, ...]) -> bool:
    if not auth_enabled():
        return True
    return role in allowed
