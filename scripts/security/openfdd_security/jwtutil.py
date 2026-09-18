"""Minimal HS256 JWT helpers for isolated expiry/signature tests.

Uses only stdlib. Tokens are for disposable harness keys — never Railway secrets.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def encode_jwt(
    payload: dict[str, Any],
    secret: bytes,
    *,
    header: dict[str, Any] | None = None,
    signature: bytes | None = None,
) -> str:
    hdr = header or {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(hdr, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    msg = f"{h}.{p}".encode()
    if signature is None:
        if hdr.get("alg") == "none":
            sig = ""
        else:
            sig = _b64url(hmac.new(secret, msg, hashlib.sha256).digest())
    else:
        sig = _b64url(signature)
    if hdr.get("alg") == "none":
        return f"{h}.{p}."
    return f"{h}.{p}.{sig}"


def make_valid_token(
    secret: bytes,
    *,
    sub: str = "harness-user",
    role: str = "operator",
    ttl_s: int = 600,
    tenant_ids: list[str] | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + ttl_s,
        "tenant_ids": tenant_ids or [],
    }
    return encode_jwt(payload, secret)


def make_expired_token(
    secret: bytes,
    *,
    sub: str = "harness-user",
    role: str = "operator",
    tenant_ids: list[str] | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now - 3600,
        "exp": now - 120,
        "tenant_ids": tenant_ids or [],
    }
    return encode_jwt(payload, secret)


def make_alg_none_token(
    *,
    sub: str = "harness-user",
    role: str = "admin",
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + 600,
    }
    return encode_jwt(payload, b"", header={"alg": "none", "typ": "JWT"})


def make_tampered_token(secret: bytes) -> str:
    tok = make_valid_token(secret, role="admin")
    parts = tok.split(".")
    # Flip last char of signature
    sig = parts[2]
    flipped = ("A" if sig[-1] != "A" else "B") + sig[1:] if sig else "AAAA"
    return f"{parts[0]}.{parts[1]}.{flipped}"
