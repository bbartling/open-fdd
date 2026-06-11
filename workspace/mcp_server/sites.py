from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import McpError

_SECRET_KEYS = frozenset(
    {
        "password",
        "token",
        "api_key",
        "secret",
        "auth_token",
        "integrator_password",
    }
)


@dataclass
class SiteRecord:
    site_id: str
    name: str = ""
    building_id: str = ""
    base_url: str = ""
    username: str = ""
    password: str = ""
    token: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SiteRecord:
        sid = str(raw.get("site_id") or raw.get("id") or "").strip()
        if not sid:
            raise McpError("site registry entry missing site_id")
        tags = raw.get("tags") or []
        known = {
            "site_id",
            "id",
            "name",
            "building_id",
            "base_url",
            "username",
            "password",
            "token",
            "tags",
        }
        extra = {k: v for k, v in raw.items() if k not in known}
        return cls(
            site_id=sid,
            name=str(raw.get("name") or sid),
            building_id=str(raw.get("building_id") or ""),
            base_url=str(raw.get("base_url") or "").rstrip("/"),
            username=str(raw.get("username") or ""),
            password=str(raw.get("password") or ""),
            token=str(raw.get("token") or ""),
            tags=[str(t) for t in tags] if isinstance(tags, list) else [],
            extra=extra,
        )

    def redacted(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "site_id": self.site_id,
            "name": self.name,
            "building_id": self.building_id,
            "base_url": self.base_url,
            "username": self.username,
            "tags": self.tags,
        }
        if self.password:
            out["password"] = "***"
        if self.token:
            out["token"] = "***"
        for k, v in self.extra.items():
            if k.lower() in _SECRET_KEYS:
                out[k] = "***"
            else:
                out[k] = v
        return out


class SiteRegistry:
    def __init__(self, path: Path, *, edge_base_url: str = "", default_site_id: str | None = None) -> None:
        self.path = path
        self.edge_base_url = edge_base_url.rstrip("/")
        self.default_site_id = default_site_id
        self._sites: dict[str, SiteRecord] = {}
        self._load()

    def _load(self) -> None:
        if self.path.is_file():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload.get("sites") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise McpError(f"invalid sites registry: {self.path}")
            for row in rows:
                if isinstance(row, dict):
                    site = SiteRecord.from_dict(row)
                    if not site.base_url and self.edge_base_url:
                        site.base_url = self.edge_base_url
                    self._sites[site.site_id] = site
        elif self.edge_base_url:
            sid = self.default_site_id or "local"
            self._sites[sid] = SiteRecord(site_id=sid, name="local edge", base_url=self.edge_base_url)

    def list_sites(self) -> list[SiteRecord]:
        return list(self._sites.values())

    def get(self, site_id: str | None) -> SiteRecord:
        sid = (site_id or self.default_site_id or "").strip()
        if not sid:
            if len(self._sites) == 1:
                return next(iter(self._sites.values()))
            if self._sites:
                raise McpError("site_id required — multiple sites in registry")
            raise McpError("no sites configured")
        site = self._sites.get(sid)
        if not site:
            raise McpError(f"unknown site_id: {sid}")
        return site

    def redacted_payload(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sites": [s.redacted() for s in self.list_sites()],
            "default_site_id": self.default_site_id,
        }
