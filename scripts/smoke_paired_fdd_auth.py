"""Auth session for paired FDD smoke harness — login, JWT expiry, 401 retry."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def decode_jwt_exp(token: str) -> float | None:
    """Decode JWT ``exp`` claim without signature verification."""
    try:
        parts = str(token).split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(raw.decode("utf-8"))
        exp = data.get("exp")
        return float(exp) if exp is not None else None
    except (ValueError, TypeError, json.JSONDecodeError, OSError):
        return None


def load_auth_credentials() -> tuple[str, str]:
    auth_env = Path(os.environ.get("OPENFDD_AUTH_ENV", REPO / "workspace" / "auth.env.local"))
    if auth_env.is_file():
        for line in auth_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    user = os.environ.get("OFDD_INTEGRATOR_USER", os.environ.get("OFDD_OPERATOR_USER", "integrator"))
    password = os.environ.get("OFDD_INTEGRATOR_PASSWORD", os.environ.get("OFDD_OPERATOR_PASSWORD", ""))
    return user, password


def raw_fetch(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 180.0,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:500]}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


@dataclass
class AuthStats:
    refresh_count: int = 0
    http_401_count: int = 0
    recovered_count: int = 0
    unrecovered_count: int = 0
    first_401_at: str | None = None
    first_unrecoverable_at: str | None = None
    auth_failure: bool = False
    events: list[str] = field(default_factory=list)

    def record_event(self, message: str, *, max_events: int = 20) -> None:
        self.events.append(message)
        if len(self.events) > max_events:
            self.events = self.events[-max_events:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "auth_refresh_count": self.refresh_count,
            "auth_401_count": self.http_401_count,
            "auth_first_401_at": self.first_401_at,
            "auth_recovered_count": self.recovered_count,
            "auth_unrecovered_count": self.unrecovered_count,
            "first_unrecoverable_auth_failure_at": self.first_unrecoverable_at,
            "auth_failure": self.auth_failure,
            "auth_events": list(self.events),
        }


class SmokeAuthSession:
    """Per-site authenticated HTTP session with proactive and reactive token refresh."""

    def __init__(
        self,
        *,
        base: str,
        label: str,
        stats: AuthStats,
        stats_lock: threading.Lock,
        refresh_skew_s: float = 120.0,
    ) -> None:
        self.base = base.rstrip("/")
        self.label = label
        self.stats = stats
        self.stats_lock = stats_lock
        self.refresh_skew_s = refresh_skew_s
        self._token: str | None = None
        self._exp: float | None = None
        self._login_lock = threading.Lock()

    def login(self, *, reason: str = "initial") -> None:
        user, password = load_auth_credentials()
        st, body = raw_fetch(
            "POST",
            f"{self.base}/api/auth/login",
            body={"username": user, "password": password},
        )
        if st != 200 or not isinstance(body, dict) or not body.get("token"):
            with self.stats_lock:
                self.stats.auth_failure = True
                self.stats.unrecovered_count += 1
                if not self.stats.first_unrecoverable_at:
                    self.stats.first_unrecoverable_at = _utc()
                self.stats.record_event(f"[{self.label}] login failed HTTP {st} ({reason})")
            raise RuntimeError(f"{self.label} login failed HTTP {st}")
        self._token = str(body["token"])
        self._exp = decode_jwt_exp(self._token)
        with self.stats_lock:
            self.stats.refresh_count += 1
            self.stats.record_event(f"[{self.label}] auth refresh ({reason})")

    def _needs_refresh(self) -> bool:
        if not self._token:
            return True
        if self._exp is None:
            return False
        return time.time() >= (self._exp - self.refresh_skew_s)

    def ensure_token(self, *, reason: str = "proactive") -> None:
        if self._needs_refresh():
            with self._login_lock:
                if self._needs_refresh():
                    self.login(reason=reason)

    def fetch(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        timeout: float = 180.0,
    ) -> tuple[int, Any]:
        if self.stats.auth_failure:
            return 401, {"detail": "auth session failed"}
        self.ensure_token()
        url = path if path.startswith("http") else f"{self.base}{path if path.startswith('/') else '/' + path}"
        st, res = raw_fetch(method, url, token=self._token, body=body, timeout=timeout)
        if st != 401:
            return st, res

        with self.stats_lock:
            self.stats.http_401_count += 1
            if not self.stats.first_401_at:
                self.stats.first_401_at = _utc()
        try:
            with self._login_lock:
                self.login(reason="401_retry")
                st2, res2 = raw_fetch(method, url, token=self._token, body=body, timeout=timeout)
        except RuntimeError:
            with self.stats_lock:
                self.stats.unrecovered_count += 1
                self.stats.auth_failure = True
                if not self.stats.first_unrecoverable_at:
                    self.stats.first_unrecoverable_at = _utc()
                self.stats.record_event(f"[{self.label}] unrecoverable 401 on {method} {path}")
            return 401, {"detail": "auth retry failed"}

        if st2 == 401:
            with self.stats_lock:
                self.stats.unrecovered_count += 1
                self.stats.auth_failure = True
                if not self.stats.first_unrecoverable_at:
                    self.stats.first_unrecoverable_at = _utc()
                self.stats.record_event(f"[{self.label}] unrecoverable 401 after retry on {method} {path}")
            return st2, res2

        with self.stats_lock:
            self.stats.recovered_count += 1
            self.stats.record_event(f"[{self.label}] auth_refresh_event recovered {method} {path}")
        return st2, res2
