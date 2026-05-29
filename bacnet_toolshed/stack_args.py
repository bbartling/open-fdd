"""Build BACnet CLI argv from commission.env keys."""

from __future__ import annotations


def bacnet_argv_from_cfg(cfg: dict[str, str]) -> list[str]:
    argv = [
        "--name",
        cfg.get("BACNET_NAME", "OpenFddEdge"),
        "--instance",
        str(cfg.get("BACNET_INSTANCE", "599999")),
        "--address",
        cfg.get("BACNET_BIND", "0.0.0.0/24:47808"),
    ]
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
