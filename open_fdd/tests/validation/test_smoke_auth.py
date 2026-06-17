"""Tests for smoke harness JWT auth helpers."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import pytest

from scripts.smoke_paired_fdd_auth import AuthStats, SmokeAuthSession, decode_jwt_exp


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


def test_decode_jwt_exp():
    exp = int(time.time()) + 3600
    assert decode_jwt_exp(_jwt({"exp": exp})) == float(exp)


def test_decode_jwt_exp_invalid():
    assert decode_jwt_exp("not-a-jwt") is None


def test_smoke_auth_session_recovers_from_401():
    stats = AuthStats()
    session = SmokeAuthSession(base="http://127.0.0.1:8765", label="bench", stats=stats, stats_lock=__import__("threading").Lock())

    def fake_fetch(method, url, *, token=None, body=None, timeout=180.0):
        if "/api/auth/login" in url:
            return 200, {"token": _jwt({"exp": int(time.time()) + 7200})}
        if token == "old":
            return 401, {"detail": "expired"}
        return 200, {"ok": True}

    with patch("scripts.smoke_paired_fdd_auth.raw_fetch", side_effect=fake_fetch):
        session._token = "old"
        session._exp = time.time() + 9999
        st, body = session.fetch("POST", "/api/rules/batch", body={"lookback_hours": 1})
    assert st == 200
    assert body == {"ok": True}
    assert stats.recovered_count == 1
    assert stats.http_401_count == 1


def test_smoke_auth_session_unrecoverable_401():
    stats = AuthStats()
    session = SmokeAuthSession(base="http://127.0.0.1:8765", label="acme", stats=stats, stats_lock=__import__("threading").Lock())

    def fake_fetch(method, url, *, token=None, body=None, timeout=180.0):
        if "/api/auth/login" in url:
            return 401, {"detail": "bad creds"}
        return 401, {"detail": "expired"}

    with patch("scripts.smoke_paired_fdd_auth.raw_fetch", side_effect=fake_fetch):
        session._token = "old"
        session._exp = time.time() + 9999
        st, _body = session.fetch("POST", "/api/rules/batch")
    assert st == 401
    assert stats.auth_failure is True
