"""Build BACnet CLI argv from commission.env keys."""

from __future__ import annotations

from bacnet_toolshed.device_identity import apply_device_identity_defaults
from bacnet_toolshed.nic_bind import resolve_bacnet_bind


def bacnet_argv_from_cfg(cfg: dict[str, str]) -> list[str]:
    """Argv for BACpypes3 Application.from_args — no discover-only flags."""
    cfg = apply_device_identity_defaults(cfg)
    bind = resolve_bacnet_bind(cfg.get("BACNET_BIND"))
    name = cfg["BACNET_NAME"]
    instance = cfg["BACNET_INSTANCE"]
    argv = [
        "--name",
        name,
        "--instance",
        instance,
        "--address",
        bind,
    ]
    vendor = cfg.get("BACNET_VENDOR_ID", "").strip()
    if vendor:
        argv.extend(["--vendoridentifier", vendor])
    if cfg.get("ROUTER_IP", "").strip():
        argv.append("--route-aware")
        argv.extend(["--network", str(cfg.get("BACNET_NETWORK", "1"))])
    return argv


def route_discovery_kwargs(cfg: dict[str, str]) -> dict[str, object]:
    """MS/TP router params for discover_lib / subprocess discover (not BACpypes argv)."""
    router = cfg.get("ROUTER_IP", "").strip()
    if not router:
        return {}
    try:
        mstp = int(str(cfg.get("MSTP_NET", "2000")).strip() or "2000")
    except ValueError:
        mstp = 2000
    return {"router_ip": router, "mstp_net": mstp, "local_too": False}


def discover_timeout_s(cfg: dict[str, str], default: float = 20.0) -> float:
    raw = str(cfg.get("DISCOVER_TIMEOUT", "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
