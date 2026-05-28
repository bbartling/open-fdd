"""Single-user Bearer tokens for OT LAN dashboards (no Cognito)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

_SECRET = os.environ.get("OFDD_AUTH_SECRET", "").strip()
_USER = os.environ.get("OFDD_WEB_USER", "").strip()
_PASSWORD = os.environ.get("OFDD_WEB_PASSWORD", "").strip()
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


def auth_enabled() -> bool:
    return bool(_SECRET and _USER and _PASSWORD)


def check_credentials(username: str, password: str) -> bool:
    if not auth_enabled():
        return True
    return username == _USER and hmac.compare_digest(password, _PASSWORD)


def issue_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + _TOKEN_TTL_SEC}
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
        return {"sub": "open", "exp": 0}
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
    return payload
