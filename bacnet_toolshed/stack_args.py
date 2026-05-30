"""Build BACnet CLI argv from commission.env keys."""

from __future__ import annotations

from bacnet_toolshed.nic_bind import resolve_bacnet_bind


def bacnet_argv_from_cfg(cfg: dict[str, str]) -> list[str]:
    bind = resolve_bacnet_bind(cfg.get("BACNET_BIND"))
    name = cfg.get("BACNET_NAME", "OpenFddEdge").strip() or "OpenFddEdge"
    instance = str(cfg.get("BACNET_INSTANCE", "599999")).strip() or "599999"
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
        argv.extend(
            [
                "--route-aware",
                "--network",
                str(cfg.get("BACNET_NETWORK", "1")),
                "--router-ip",
                cfg["ROUTER_IP"].strip(),
                "--mstp-net",
                str(cfg.get("MSTP_NET", "2000")),
            ]
        )
    return argv
