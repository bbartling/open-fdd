"""Minimal HTTP client for edge Operator Bridge (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def login(base_url: str, *, username: str, password: str, timeout: int = 30) -> str:
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    token = str(body.get("token") or "").strip()
    if not token:
        raise RuntimeError("login returned no token")
    return token


def api_get(base_url: str, token: str, path: str, *, timeout: int = 120) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return raw


def api_post(
    base_url: str,
    token: str,
    path: str,
    body: dict[str, Any],
    *,
    timeout: int = 600,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return raw


def fetch_portfolio_rollup(
    base_url: str,
    token: str,
    *,
    site_id: str | None = None,
) -> dict[str, Any]:
    path = "/api/building/portfolio-rollup"
    if site_id:
        path = f"{path}?site_id={urllib.parse.quote(site_id)}"
    return api_get(base_url, token, path)
