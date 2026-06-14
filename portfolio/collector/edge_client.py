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


def api_get_text(base_url: str, token: str, path: str, *, timeout: int = 180) -> str:
    headers: dict[str, str] = {"Accept": "text/turtle"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc


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


def api_post_bytes(
    base_url: str,
    token: str,
    path: str,
    body: dict[str, Any],
    *,
    timeout: int = 600,
) -> tuple[bytes, str]:
    """POST JSON body; return raw response bytes and Content-Disposition filename."""
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
            content = resp.read()
            disp = resp.headers.get("Content-Disposition") or ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
    fname = "openfdd-rcx.docx"
    if "filename=" in disp:
        fname = disp.split("filename=", 1)[-1].strip().strip('"')
    return content, fname


def api_patch(
    base_url: str,
    token: str,
    path: str,
    body: dict[str, Any],
    *,
    timeout: int = 120,
) -> dict[str, Any]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method="PATCH",
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
    timeout: int = 8,
) -> dict[str, Any]:
    path = "/api/building/portfolio-rollup"
    if site_id:
        path = f"{path}?site_id={urllib.parse.quote(site_id)}"
    return api_get(base_url, token, path, timeout=timeout)


class EdgeClient:
    """Read-only Edge REST client for OpenFDD RCx Central."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def login(self, *, username: str, password: str) -> str:
        return login(self.base_url, username=username, password=password)

    def api_get(self, path: str, *, token: str = "", timeout: int = 120) -> dict[str, Any]:
        return api_get(self.base_url, token, path, timeout=timeout)

    def try_api_get(self, path: str, *, token: str = "") -> dict[str, Any] | None:
        """Read-only GET; returns None on HTTP 404 (older Edge builds without route)."""
        try:
            return self.api_get(path, token=token)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def api_post(self, path: str, body: dict[str, Any], *, token: str = "") -> dict[str, Any]:
        return api_post(self.base_url, token, path, body)

    def api_patch(self, path: str, body: dict[str, Any], *, token: str = "") -> dict[str, Any]:
        return api_patch(self.base_url, token, path, body)

    def get_health(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/health", token=token)

    def get_version(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/health/stack", token=token)

    def get_model_health(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/health", token=token)

    def get_model_tree(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/tree", token=token)

    def get_model_ttl(self, *, token: str = "", save: bool = False) -> str:
        flag = "true" if save else "false"
        return api_get_text(self.base_url, token, f"/api/model/ttl?save={flag}")

    def get_model_queries(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/sparql/predefined", token=token)

    def run_model_query(self, query: str, *, token: str = "") -> dict[str, Any]:
        return self.api_post("/api/model/sparql", {"query": query}, token=token)

    def get_faults_status(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/faults/status", token=token)

    def get_analytics_overview(self, *, token: str = "") -> dict[str, Any]:
        return self.try_api_get("/api/analytics/overview", token=token) or {}

    def get_analytics_faults(self, hours: int = 24, *, token: str = "") -> dict[str, Any]:
        return self.try_api_get(f"/api/analytics/faults?hours={hours}", token=token) or {}

    def get_bacnet_poll_status(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/bacnet/poll/status", token=token)

    def get_fdd_rules(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/rules/saved", token=token)

    def get_fdd_query_presets(self, *, token: str = "") -> dict[str, Any]:
        return self.api_get("/api/model/fdd-query-presets", token=token)

    def get_fdd_query_preset(self, preset_id: str, *, token: str = "") -> dict[str, Any]:
        import urllib.parse

        pid = urllib.parse.quote(preset_id, safe="")
        return self.api_get(f"/api/model/fdd-query-presets/{pid}", token=token)

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

    def get_portfolio_rollup(
        self,
        *,
        site_id: str | None = None,
        token: str = "",
        timeout: int = 8,
    ) -> dict[str, Any]:
        return fetch_portfolio_rollup(self.base_url, token, site_id=site_id, timeout=timeout)

    def get_rcx_workspace(
        self,
        site_id: str,
        *,
        hours: int = 24,
        start: str | None = None,
        end: str | None = None,
        show_fault_overlays: bool = True,
        token: str = "",
    ) -> dict[str, Any]:
        params: list[str] = [
            f"site_id={urllib.parse.quote(site_id)}",
            f"hours={hours}",
            f"show_fault_overlays={'true' if show_fault_overlays else 'false'}",
        ]
        if start:
            params.append(f"start={urllib.parse.quote(start)}")
        if end:
            params.append(f"end={urllib.parse.quote(end)}")
        return self.api_get(f"/api/reports/rcx/workspace?{'&'.join(params)}", token=token)

    def get_rcx_points(self, site_id: str, *, limit: int = 500, token: str = "") -> dict[str, Any]:
        return self.api_get(
            f"/api/reports/rcx/points?site_id={urllib.parse.quote(site_id)}&limit={limit}",
            token=token,
        )

    def get_rcx_point_tree(self, site_id: str, *, limit: int = 500, token: str = "") -> dict[str, Any]:
        return self.api_get(
            f"/api/reports/rcx/point-tree?site_id={urllib.parse.quote(site_id)}&limit={limit}",
            token=token,
        )

    def post_rcx_preview(self, body: dict[str, Any], *, token: str = "") -> dict[str, Any]:
        return self.api_post("/api/reports/rcx/preview", body, token=token)

    def post_rcx_generate(self, body: dict[str, Any], *, token: str = "") -> tuple[bytes, str]:
        return api_post_bytes(self.base_url, token, "/api/reports/rcx/generate", body)

    def list_rcx_reports(self, *, limit: int = 100, token: str = "") -> dict[str, Any]:
        return self.api_get(f"/api/reports/rcx/list?limit={limit}", token=token)
