"""Console entrypoints for the desktop bridge (lazy heavy imports).

Installing ``open-fdd`` without ``[desktop]`` should not fail at import time when
console scripts are registered; failures happen only when you run the gateway.
"""

from __future__ import annotations

import logging
import os
import urllib.parse

_log = logging.getLogger(__name__)


def _valid_tcp_port(value: object) -> int | None:
    try:
        p = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if 1 <= p <= 65535:
        return p
    return None


def resolve_gateway_bind(default_host: str = "127.0.0.1", default_port: int = 8765) -> tuple[str, int]:
    """Resolve host/port from OFDD_BRIDGE_URL / OFDD_DESKTOP_BRIDGE_BASE or OFDD_BRIDGE_* env."""
    host, port = default_host, default_port
    url = (os.environ.get("OFDD_BRIDGE_URL") or os.environ.get("OFDD_DESKTOP_BRIDGE_BASE") or "").strip()
    url_applied = False
    if url:
        try:
            parsed = urllib.parse.urlparse(url)
        except ValueError:
            _log.warning("Ignoring malformed OFDD_BRIDGE_URL/OFDD_DESKTOP_BRIDGE_BASE: %r", url)
        else:
            if parsed.hostname:
                host = parsed.hostname
            try:
                parsed_port = parsed.port
            except ValueError:
                _log.warning("Ignoring out-of-range port in bridge URL: %r", url)
                parsed_port = None
            if parsed_port is not None:
                vp = _valid_tcp_port(parsed_port)
                if vp is not None:
                    port = vp
                    url_applied = True
                else:
                    _log.warning(
                        "Ignoring invalid port in OFDD_BRIDGE_URL/OFDD_DESKTOP_BRIDGE_BASE: %r",
                        parsed_port,
                    )
            elif parsed.hostname:
                url_applied = True

    if url_applied:
        return host, port

    env_host = (os.environ.get("OFDD_BRIDGE_HOST") or "").strip()
    if env_host:
        host = env_host
    env_port_raw = (os.environ.get("OFDD_BRIDGE_PORT") or "").strip()
    if env_port_raw:
        vp = _valid_tcp_port(env_port_raw)
        if vp is not None:
            port = vp
        else:
            _log.warning(
                "Ignoring invalid OFDD_BRIDGE_PORT=%r (expected 1-65535); using default %s",
                env_port_raw,
                default_port,
            )
    return host, port


def run_gateway(host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "The Open-FDD gateway requires optional desktop dependencies. "
            "Install with: pip install 'open-fdd[desktop]'"
        ) from exc

    host, port = resolve_gateway_bind(default_host=host, default_port=port)
    from open_fdd.gateway.server import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


run_desktop_bridge = run_gateway


if __name__ == "__main__":
    run_gateway()
