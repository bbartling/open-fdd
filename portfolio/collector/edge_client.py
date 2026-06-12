"""HTTP client for OpenFDD Edge Operator Bridge (stdlib only, read-only)."""

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
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=headers,
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
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
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


class EdgeClient:
    """Read-only Edge REST client for OpenFDD RCx Central."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def login(self, *, username: str, password: str) -> str:
        return login(self.base_url, username=username, password=password)

    def api_get(self, path: str, *, token: str = "") -> dict[str, Any]:
        return api_get(self.base_url, token, path)

    def api_post(self, path: str, body: dict[str, Any], *, token: str = "") -> dict[str, Any]:
        return api_post(self.base_url, token, path, body)

    def get_health(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/health", token=token)

    def get_version(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/health/stack", token=token)

    def get_model_health(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/health", token=token)

    def get_model_tree(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/tree", token=token)

    def get_model_queries(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/sparql/predefined", token=token)

    def run_model_query(self, query: str, *, token: str = "") -> dict[str, Any]:
        return self.api_post("/api/model/sparql", {"query": query}, token=token)

    def get_faults_status(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/faults/status", token=token)

    def get_analytics_overview(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/analytics/overview", token=token)

    def get_analytics_faults(self, hours: int = 24, *, token: str = "") -> dict[str, Any]:
        return self.api_get(f"/api/analytics/faults?hours={hours}", token=token)

    def get_bacnet_poll_status(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/bacnet/poll/status", token=token)

    def get_fdd_rules(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/rules/saved", token=token)

    def get_fdd_query_presets(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/fdd-query-presets", token=token)

    def get_timeseries_series(self, site_id: str, *, token: str = "", source: str = "bacnet") -> dict[str, Any]:
        return self.api_get(f"/api/timeseries/series?site_id={site_id}&source={source}", token=token)

    def get_timeseries_readings(
        self,
        site_id: str,
        columns: list[str],
        *,
        hours: int = 24,
        token: str = "",
        include_faults: bool = True,
        source: str = "bacnet",
    ) -> dict[str, Any]:
        import urllib.parse

        col_param = urllib.parse.quote(",".join(columns), safe=",")
        inc = "true" if include_faults else "false"
        path = (
            f"/api/timeseries/readings?site_id={urllib.parse.quote(site_id)}"
            f"&columns={col_param}&hours={hours}&source={source}&include_faults={inc}"
        )
        return self.api_get(path, token=token)

    def get_portfolio_rollup(self, *, site_id: str | None = None, token: str = "") -> dict[str, Any]:
        return fetch_portfolio_rollup(self.base_url, token, site_id=site_id)
