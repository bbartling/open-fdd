from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import McpConfig
from .errors import McpError
from .sites import SiteRecord, SiteRegistry


class BridgeClient:
    def __init__(self, config: McpConfig, registry: SiteRegistry) -> None:
        self.config = config
        self.registry = registry
        self._tokens: dict[str, str] = {}

    def _login(self, site: SiteRecord) -> str | None:
        if site.token:
            return site.token
        cached = self._tokens.get(site.site_id)
        if cached:
            return cached
        if not site.username or not site.password:
            return None
        if not site.base_url:
            raise McpError(f"site {site.site_id} has no base_url")
        body = json.dumps({"username": site.username, "password": site.password}).encode()
        req = Request(
            f"{site.base_url}/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise McpError(f"login failed for {site.site_id}: HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise McpError(f"login failed for {site.site_id}: {exc}") from exc
        token = str(payload.get("token") or "")
        if token:
            self._tokens[site.site_id] = token
        return token or None

    def _request(
        self,
        site: SiteRecord,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        auth_required: bool = True,
    ) -> dict[str, Any]:
        if not site.base_url:
            raise McpError(f"site {site.site_id} has no base_url")
        url = f"{site.base_url}{path}"
        if params:
            q = {k: v for k, v in params.items() if v is not None}
            if q:
                url = f"{url}?{urlencode(q)}"
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth_required:
            token = self._login(site)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        req = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:800]
            raise McpError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise McpError(f"{method} {path} failed: {exc}") from exc

    def get(self, site_id: str | None, path: str, *, params: dict[str, Any] | None = None, auth_required: bool = True) -> dict[str, Any]:
        site = self.registry.get(site_id)
        return self._request(site, "GET", path, params=params, auth_required=auth_required)

    def post(
        self,
        site_id: str | None,
        path: str,
        body: dict[str, Any],
        *,
        auth_required: bool = True,
    ) -> dict[str, Any]:
        site = self.registry.get(site_id)
        return self._request(site, "POST", path, body=body, auth_required=auth_required)

    def cap_window(self, window_minutes: int) -> int:
        return min(max(5, int(window_minutes)), self.config.max_window_minutes)
