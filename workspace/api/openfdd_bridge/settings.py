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
    flag = os.environ.get("OFDD_CORS_ALLOW_PRIVATE_LAN", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    # Default: when listening on all interfaces, allow private LAN browser origins.
    return bridge_host() in {"0.0.0.0", "::"}


def cors_origins() -> list[str]:
    origins = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ]
    if cors_allow_private_lan():
        extra = os.environ.get("OFDD_CORS_LAN_ORIGINS", "").strip()
        if extra:
            origins.extend(o.strip() for o in extra.split(",") if o.strip())
        # Allow LAN dashboard origin when bound on 0.0.0.0 (vite dev from another host).
        host = bridge_host()
        port = bridge_port()
        if host in {"0.0.0.0", "::"}:
            origins.append(f"http://127.0.0.1:{port}")
            try:
                import socket

                lan_ip = socket.gethostbyname(socket.gethostname())
                if lan_ip and not lan_ip.startswith("127."):
                    origins.append(f"http://{lan_ip}:{port}")
                    origins.append(f"http://{lan_ip}:5173")
            except OSError:
                pass
    return origins
