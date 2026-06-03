"""Bridge bind, CORS, and LAN defaults."""

from __future__ import annotations

import os


def bridge_host() -> str:
    raw = os.environ.get("OFDD_BRIDGE_HOST", "0.0.0.0").strip()
    return raw or "0.0.0.0"


def bridge_port() -> int:
    raw = os.environ.get("OFDD_BRIDGE_PORT", "8765").strip()
    try:
        return int(raw)
    except ValueError:
        return 8765


def cors_allow_private_lan() -> bool:
    """Only when explicitly opted in — never implied by 0.0.0.0 bind."""
    flag = os.environ.get("OFDD_CORS_ALLOW_PRIVATE_LAN", "").strip().lower()
    return flag in {"1", "true", "yes"}


def cors_origins() -> list[str]:
    """Same-origin + local Vite dev; explicit OFDD_CORS_ORIGINS allowlist."""
    origins = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ]
    extra = os.environ.get("OFDD_CORS_ORIGINS", "").strip()
    if extra:
        origins.extend(o.strip() for o in extra.split(",") if o.strip())
    if cors_allow_private_lan():
        lan_extra = os.environ.get("OFDD_CORS_LAN_ORIGINS", "").strip()
        if lan_extra:
            origins.extend(o.strip() for o in lan_extra.split(",") if o.strip())
        port = bridge_port()
        try:
            import socket

            lan_ip = socket.gethostbyname(socket.gethostname())
            if lan_ip and not lan_ip.startswith("127."):
                origins.append(f"http://{lan_ip}:{port}")
                origins.append(f"http://{lan_ip}:5173")
        except OSError:
            pass
    seen: set[str] = set()
    out: list[str] = []
    for origin in origins:
        if origin and origin not in seen:
            seen.add(origin)
            out.append(origin)
    return out


def cors_allow_methods() -> list[str]:
    return ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def cors_allow_headers() -> list[str]:
    return ["Authorization", "Content-Type", "Accept"]
