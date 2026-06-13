"""Derive site_id from Edge URL + display name (operators never type site_id)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from portfolio.central.edge_registry import list_edges_public


def normalize_base_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "http").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    return f"{scheme}://{netloc}"


def derive_site_id(*, base_url: str, name: str = "") -> str:
    """Stable slug for a new Edge — prefer first word of display name."""
    label = (name or "").strip()
    if label:
        first = re.sub(r"[^a-z0-9]", "", label.split()[0].lower())
        if len(first) >= 2:
            return first[:64]
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        if slug:
            return slug[:64]
    host = urlparse(normalize_base_url(base_url)).hostname or "edge"
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
    return (slug or "edge")[:64]


def resolve_site_id(*, base_url: str, name: str = "") -> str:
    """Match existing registry by URL, else derive a new site_id."""
    norm = normalize_base_url(base_url)
    if not norm:
        raise ValueError("Edge URL required")
    for edge in list_edges_public():
        if normalize_base_url(str(edge.get("base_url") or "")) == norm:
            return str(edge["site_id"])
    return derive_site_id(base_url=norm, name=name)
