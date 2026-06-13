"""Edge registry CRUD + connection test (local config volume, secrets masked)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from portfolio.central.paths import config_dir, credentials_path, sites_path
from portfolio.collector.collector import SiteConfig, load_sites_config
from portfolio.collector.edge_client import EdgeClient


_BLOCKED_SCHEMES = {"file", "ftp", "gopher"}


def _validate_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https")
    if parsed.scheme in _BLOCKED_SCHEMES:
        raise ValueError("base_url scheme not allowed")
    if not parsed.netloc:
        raise ValueError("base_url must include host")
    return url.rstrip("/")


def _load_credentials() -> dict[str, Any]:
    path = credentials_path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _save_credentials(data: dict[str, Any]) -> None:
    credentials_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


@dataclass
class EdgeRecordPublic:
    site_id: str
    name: str
    base_url: str
    auth_type: str
    username: str
    has_password: bool
    has_token: bool
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_edges_public() -> list[dict[str, Any]]:
    creds = _load_credentials()
    out: list[dict[str, Any]] = []
    for cfg in load_sites_config(sites_path()):
        c = creds.get(cfg.site_id) if isinstance(creds.get(cfg.site_id), dict) else {}
        auth_type = str(c.get("auth_type") or ("bearer" if c.get("token") else "password"))
        out.append(
            EdgeRecordPublic(
                site_id=cfg.site_id,
                name=cfg.name,
                base_url=cfg.base_url,
                auth_type=auth_type,
                username=cfg.username,
                has_password=bool(c.get("password") or cfg.password),
                has_token=bool(c.get("token")),
            ).to_dict()
        )
    return out


def _write_sites(sites: list[dict[str, Any]]) -> None:
    path = config_dir() / "sites.json"
    path.write_text(json.dumps({"sites": sites}, indent=2), encoding="utf-8")


def _all_site_dicts() -> list[dict[str, Any]]:
    path = sites_path()
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    sites = raw.get("sites") if isinstance(raw, dict) else raw
    return list(sites) if isinstance(sites, list) else []


def add_or_update_edge(
    *,
    site_id: str,
    name: str,
    base_url: str,
    auth_type: str = "password",
    username: str = "agent",
    password: str = "",
    token: str = "",
) -> dict[str, Any]:
    site_id = site_id.strip()
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", site_id):
        raise ValueError("site_id must be lowercase alphanumeric with ._-")
    base_url = _validate_base_url(base_url)
    sites = _all_site_dicts()
    row = {
        "site_id": site_id,
        "name": name.strip() or site_id,
        "base_url": base_url,
        "username": username.strip() or "agent",
    }
    updated = False
    for i, s in enumerate(sites):
        if isinstance(s, dict) and s.get("site_id") == site_id:
            sites[i] = {**s, **row}
            updated = True
            break
    if not updated:
        sites.append(row)
    _write_sites(sites)

    creds = _load_credentials()
    entry: dict[str, Any] = {"auth_type": auth_type}
    if auth_type == "bearer" and token:
        entry["token"] = token
    elif auth_type == "password" and password:
        entry["password"] = password
    elif auth_type == "none":
        entry["auth_type"] = "none"
    if entry.get("password") or entry.get("token") or auth_type == "none":
        creds[site_id] = entry
        _save_credentials(creds)
    return list_edges_public()


def delete_edge(site_id: str) -> None:
    sites = [s for s in _all_site_dicts() if isinstance(s, dict) and s.get("site_id") != site_id]
    _write_sites(sites)
    creds = _load_credentials()
    creds.pop(site_id, None)
    _save_credentials(creds)


def resolve_site_config(site_id: str) -> SiteConfig:
    creds = _load_credentials()
    for cfg in load_sites_config(sites_path()):
        if cfg.site_id != site_id:
            continue
        c = creds.get(site_id) if isinstance(creds.get(site_id), dict) else {}
        if c.get("password"):
            return SiteConfig(
                site_id=cfg.site_id,
                name=cfg.name,
                base_url=cfg.base_url,
                username=cfg.username,
                password=str(c["password"]),
            )
        if c.get("token"):
            return SiteConfig(
                site_id=cfg.site_id,
                name=cfg.name,
                base_url=cfg.base_url,
                username=cfg.username,
                password="",
            )
        return cfg
    raise KeyError(f"unknown site_id {site_id!r}")


def resolve_token(site: SiteConfig) -> str:
    creds = _load_credentials()
    c = creds.get(site.site_id) if isinstance(creds.get(site.site_id), dict) else {}
    if c.get("token"):
        return str(c["token"])
    if c.get("auth_type") == "none":
        return ""
    password = str(c.get("password") or site.password or "")
    if not password:
        # Re-resolve env-backed passwords (same as portfolio_collect.py)
        for cfg in load_sites_config(sites_path()):
            if cfg.site_id == site.site_id:
                password = cfg.password
                break
    if password:
        return EdgeClient(site.base_url).login(username=site.username, password=password)
    raise RuntimeError(
        f"{site.site_id}: missing credentials — save Edge in RCx Central UI or set "
        "ACME_INTEGRATOR_PASSWORD / OFDD_AGENT_PASSWORD for the API process"
    )


def test_edge_connection(
    *,
    site_id: str | None = None,
    base_url: str | None = None,
    auth_type: str = "password",
    username: str = "agent",
    password: str = "",
    token: str = "",
) -> dict[str, Any]:
    if site_id:
        site = resolve_site_config(site_id)
        client = EdgeClient(site.base_url)
        tok = resolve_token(site)
    else:
        if not base_url:
            raise ValueError("base_url required when site_id omitted")
        base_url = _validate_base_url(base_url)
        client = EdgeClient(base_url)
        if auth_type == "bearer" and token:
            tok = token
        elif auth_type == "none":
            tok = ""
        else:
            tok = client.login(username=username, password=password)

    result: dict[str, Any] = {"ok": False, "base_url": client.base_url}
    try:
        health = client.get_health(token=tok)
        result["health"] = health
        result["edge_version"] = health.get("openfdd_version") or health.get("version")
        stack = client.api_get("/health/stack", token=tok)
        result["stack"] = {"image_tag": stack.get("image_tag")}
        model = client.api_get("/api/model/health", token=tok)
        result["model_health"] = model
        faults = client.api_get("/api/faults/status", token=tok)
        result["traffic"] = faults.get("traffic")
        result["fault_count"] = faults.get("alert_count")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)[:500]
    return result
