"""Automatic BRICK site bootstrap — operators never hand-type site ids."""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model_service import ModelService
    from .ttl_service import TtlService


def default_site_id() -> str:
    env = os.environ.get("OPENFDD_DEFAULT_SITE_ID", "").strip()
    if env:
        return env[:64]
    host = socket.gethostname().split(".")[0].lower()
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in host).strip("-_")
    return (safe or "local")[:64]


def default_site_name() -> str:
    env = os.environ.get("OPENFDD_DEFAULT_SITE_NAME", "").strip()
    if env:
        return env[:128]
    host = socket.gethostname()
    return (host or "Local site")[:128]


def ensure_default_site(model: ModelService, ttl: TtlService | None = None) -> str:
    """Ensure model.json has at least one site; return its id."""
    sid = default_site_id()
    name = default_site_name()
    with model.transaction() as doc:
        sites = doc.setdefault("sites", [])
        for site in sites:
            if isinstance(site, dict):
                existing = str(site.get("id") or "").strip()
                if existing:
                    return existing
        sites.insert(0, {"id": sid, "name": name})
    if ttl is not None:
        ttl.sync()
    return sid
