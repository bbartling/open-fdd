"""SSRF URL policy for isolated canary qualification (Astra C-PY).

Never probe cloud metadata or real third-party targets. Forbidden destinations
are evaluated offline; live proof uses an isolated canary HTTP server that
counts hits for approved vs forbidden URLs.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

# Hostnames / prefixes that must never be requested by product fetchers.
FORBIDDEN_HOST_SUFFIXES = (
    "metadata.google.internal",
    "metadata.azure.com",
)
FORBIDDEN_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "169.254.169.254",
    "metadata.azure.com",
}
LINK_LOCAL_PREFIXES = ("169.254.", "fe80:")


def classify_url(url: str) -> dict[str, Any]:
    """Return policy classification for a candidate fetch URL."""
    raw = (url or "").strip()
    if not raw:
        return {"ok": False, "reason": "empty", "class": "invalid"}
    try:
        parts = urlsplit(raw)
    except ValueError:
        return {"ok": False, "reason": "unparseable", "class": "invalid"}
    if parts.scheme not in {"http", "https"}:
        return {"ok": False, "reason": f"scheme={parts.scheme or 'missing'}", "class": "invalid"}
    host = (parts.hostname or "").lower()
    if not host:
        return {"ok": False, "reason": "missing_host", "class": "invalid"}
    if host in FORBIDDEN_HOSTS or any(host.endswith(s) for s in FORBIDDEN_HOST_SUFFIXES):
        return {"ok": False, "reason": "cloud_metadata", "class": "forbidden"}
    if host.startswith(LINK_LOCAL_PREFIXES) or host == "0.0.0.0":
        return {"ok": False, "reason": "link_local", "class": "forbidden"}
    # Loopback is only allowed for isolated canary fixtures.
    if host in {"127.0.0.1", "localhost", "::1"}:
        return {"ok": True, "reason": "loopback_canary_only", "class": "canary"}
    return {"ok": True, "reason": "external_candidate", "class": "external"}


def forbidden_urls() -> list[str]:
    return [
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
        "http://metadata/computeMetadata/v1/",
    ]
