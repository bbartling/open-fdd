"""OpenAI ChatGPT / Codex device-code login (same contract as OpenClaw's extensions/openai device flow).

Used by the desktop UI so operators on headless hosts can complete browser OAuth without the
OpenClaw CLI. After a successful exchange the bridge writes ``auth.json`` for the host ``codex``
CLI and does **not** return access or refresh tokens to the browser.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import requests

from open_fdd.gateway import local_codex_cli

OPENAI_AUTH_BASE_URL = "https://auth.openai.com"
OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_DEVICE_CALLBACK_URL = f"{OPENAI_AUTH_BASE_URL}/deviceauth/callback"
OPENAI_CODEX_DEVICE_CODE_TIMEOUT_S = 15 * 60
OPENAI_CODEX_DEVICE_CODE_DEFAULT_INTERVAL_MS = 5000
OPENAI_CODEX_DEVICE_CODE_MIN_INTERVAL_MS = 1000


def _trim_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _interval_ms_from_body(body: dict[str, Any]) -> int:
    raw = body.get("interval")
    if isinstance(raw, (int, float)) and raw > 0:
        return max(OPENAI_CODEX_DEVICE_CODE_MIN_INTERVAL_MS, int(raw * 1000))
    if isinstance(raw, str) and raw.strip().isdigit():
        sec = int(raw.strip(), 10)
        return max(OPENAI_CODEX_DEVICE_CODE_MIN_INTERVAL_MS, sec * 1000) if sec > 0 else OPENAI_CODEX_DEVICE_CODE_DEFAULT_INTERVAL_MS
    return OPENAI_CODEX_DEVICE_CODE_DEFAULT_INTERVAL_MS


def _expires_ms_from_token_payload(body: dict[str, Any], access_token: str) -> int:
    raw = body.get("expires_in")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(time.time() * 1000) + int(raw * 1000)
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(time.time() * 1000) + int(raw.strip(), 10) * 1000
    # JWT exp fallback (seconds)
    parts = access_token.split(".")
    if len(parts) == 3:
        try:
            import base64

            pad = "=" * ((4 - len(parts[1]) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8"))
            exp = payload.get("exp")
            if isinstance(exp, (int, float)) and exp > 0:
                return int(exp * 1000)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    return int(time.time() * 1000) + 3600_000


@dataclass
class _Session:
    device_auth_id: str
    user_code: str
    interval_ms: int
    created: float = field(default_factory=lambda: time.time())
    phase: Literal["pending", "exchanging", "complete", "error"] = "pending"
    error: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    expires_at_ms: int | None = None
    persisted_to_disk: bool = False


_lock = threading.Lock()
_sessions: dict[str, _Session] = {}


def _emit_complete_response(session_id: str) -> dict[str, Any]:
    """Public JSON for a finished session (no secrets); persists tokens to disk once per session."""
    claim_persist = False
    with _lock:
        sess = _sessions.get(session_id)
        if not sess or sess.phase != "complete" or not sess.access_token or not sess.refresh_token:
            return {"status": "error", "message": "Unknown or expired session. Start sign-in again."}
        access = sess.access_token
        refresh = sess.refresh_token
        id_tok = sess.id_token
        exp = sess.expires_at_ms
        if not sess.persisted_to_disk:
            sess.persisted_to_disk = True
            claim_persist = True

    persist: dict[str, Any] = {"ok": True}
    if claim_persist:
        persist = local_codex_cli.persist_chatgpt_auth_from_device_tokens(access, refresh, id_token=id_tok)
        if not persist.get("ok"):
            with _lock:
                s2 = _sessions.get(session_id)
                if s2:
                    s2.persisted_to_disk = False

    persisted_ok = bool(persist.get("ok"))
    msg = (
        "Signed in. Credentials were saved for Codex on this bridge host."
        if persisted_ok
        else "Signed in. Failed to persist Codex credentials on this bridge host."
    )
    return {
        "status": "complete",
        "message": msg,
        "expires_at_ms": exp,
        "codex_auth_persisted": persisted_ok,
        "codex_auth_persist_error": persist.get("error") if not persisted_ok else None,
    }


def _gc_sessions() -> None:
    cutoff = time.time() - OPENAI_CODEX_DEVICE_CODE_TIMEOUT_S - 120
    with _lock:
        dead = [sid for sid, s in _sessions.items() if s.created < cutoff]
        for sid in dead:
            _sessions.pop(sid, None)


def start_device_login() -> dict[str, Any]:
    """Request a device user code from OpenAI (Codex client)."""
    _gc_sessions()
    url = f"{OPENAI_AUTH_BASE_URL}/api/accounts/deviceauth/usercode"
    r = requests.post(
        url,
        json={"client_id": OPENAI_CODEX_CLIENT_ID},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    text = r.text
    if r.status_code == 404:
        raise RuntimeError(
            "OpenAI Codex device login is not available from this network response (404). "
            "Use `openclaw models auth login --provider openai-codex` on a machine with OpenClaw installed.",
        )
    if not r.ok:
        body = _parse_json_object(text) or {}
        err = _trim_str(body.get("error")) or text[:500]
        raise RuntimeError(f"OpenAI device code request failed: HTTP {r.status_code} {err}")

    body = _parse_json_object(text) or {}
    device_auth_id = _trim_str(body.get("device_auth_id"))
    user_code = _trim_str(body.get("user_code")) or _trim_str(body.get("usercode"))
    if not device_auth_id or not user_code:
        raise RuntimeError("OpenAI device code response missing device_auth_id or user_code.")

    sid = secrets.token_urlsafe(24)
    interval_ms = _interval_ms_from_body(body)
    with _lock:
        _sessions[sid] = _Session(device_auth_id=device_auth_id, user_code=user_code, interval_ms=interval_ms)

    verification_url = f"{OPENAI_AUTH_BASE_URL}/codex/device"
    return {
        "session_id": sid,
        "user_code": user_code,
        "verification_url": verification_url,
        "interval_ms": interval_ms,
        "expires_in_seconds": OPENAI_CODEX_DEVICE_CODE_TIMEOUT_S,
    }


def poll_device_login(session_id: str) -> dict[str, Any]:
    """Single poll step toward authorization + token exchange."""
    _gc_sessions()
    with _lock:
        sess = _sessions.get(session_id)
    if sess is None:
        return {"status": "error", "message": "Unknown or expired session. Start sign-in again."}

    if sess.phase == "complete" and sess.access_token and sess.refresh_token:
        return _emit_complete_response(session_id)
    if sess.phase == "error":
        return {"status": "error", "message": sess.error or "Device login failed."}

    if sess.phase == "exchanging":
        return {"status": "pending", "message": "Exchanging authorization code…"}

    with _lock:
        sess = _sessions.get(session_id)
        if sess is None:
            return {"status": "error", "message": "Unknown or expired session. Start sign-in again."}
        if sess.phase == "complete" and sess.access_token and sess.refresh_token:
            return _emit_complete_response(session_id)
        if sess.phase == "error":
            return {"status": "error", "message": sess.error or "Device login failed."}
        if sess.phase == "exchanging":
            return {"status": "pending", "message": "Exchanging authorization code…"}
        if sess.phase != "pending":
            return {"status": "pending", "message": "Authorization still pending…"}
        sess.phase = "exchanging"
        device_auth_id = sess.device_auth_id
        user_code = sess.user_code
        created_at = sess.created

    token_url = f"{OPENAI_AUTH_BASE_URL}/api/accounts/deviceauth/token"
    r = requests.post(
        token_url,
        json={"device_auth_id": device_auth_id, "user_code": user_code},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    text = r.text

    if r.status_code in (403, 404):
        if time.time() - created_at > OPENAI_CODEX_DEVICE_CODE_TIMEOUT_S:
            with _lock:
                s2 = _sessions.get(session_id)
                if s2:
                    s2.phase = "error"
                    s2.error = "Timed out waiting for browser authorization (15 minutes)."
            return {"status": "error", "message": "Timed out waiting for browser authorization (15 minutes)."}
        with _lock:
            s2 = _sessions.get(session_id)
            if s2 and s2.phase == "exchanging":
                s2.phase = "pending"
        return {"status": "pending", "message": "Waiting for you to finish sign-in in the browser…"}

    if not r.ok:
        with _lock:
            s2 = _sessions.get(session_id)
            if s2:
                s2.phase = "error"
                s2.error = f"Device token step failed: HTTP {r.status_code} {text[:500]}"
        return {"status": "error", "message": _sessions.get(session_id, sess).error or "Device authorization failed."}

    body = _parse_json_object(text) or {}
    auth_code = _trim_str(body.get("authorization_code"))
    code_verifier = _trim_str(body.get("code_verifier"))
    if not auth_code or not code_verifier:
        with _lock:
            s2 = _sessions.get(session_id)
            if s2:
                s2.phase = "error"
                s2.error = "OpenAI response missing authorization_code or code_verifier."
        return {"status": "error", "message": "Invalid authorization response from OpenAI."}

    oauth_url = f"{OPENAI_AUTH_BASE_URL}/oauth/token"
    r2 = requests.post(
        oauth_url,
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": OPENAI_CODEX_DEVICE_CALLBACK_URL,
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    text2 = r2.text
    if not r2.ok:
        with _lock:
            s3 = _sessions.get(session_id)
            if s3:
                s3.phase = "error"
                s3.error = f"Token exchange failed: HTTP {r2.status_code} {text2[:500]}"
        return {"status": "error", "message": _sessions.get(session_id, sess).error or "Token exchange failed."}

    oauth_body = _parse_json_object(text2) or {}
    access = _trim_str(oauth_body.get("access_token"))
    refresh = _trim_str(oauth_body.get("refresh_token"))
    id_tok = _trim_str(oauth_body.get("id_token"))
    if not access or not refresh:
        with _lock:
            s3 = _sessions.get(session_id)
            if s3:
                s3.phase = "error"
                s3.error = "Token exchange succeeded but tokens were missing."
        return {"status": "error", "message": "Token exchange returned no tokens."}

    expires_at_ms = _expires_ms_from_token_payload(oauth_body, access)
    with _lock:
        s3 = _sessions.get(session_id)
        if s3:
            s3.phase = "complete"
            s3.access_token = access
            s3.refresh_token = refresh
            s3.id_token = id_tok
            s3.expires_at_ms = expires_at_ms

    return _emit_complete_response(session_id)
