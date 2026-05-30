#!/usr/bin/env python3
"""Who-Is smoke test — BACpypes3 shell pattern (see bacpypes3 Q&A #125).

Uses workspace/bacnet/commissioning/commission.env for --name, --instance, --address.

Examples:
  python -m bacnet_toolshed.smoke_whois
  python -m bacnet_toolshed.smoke_whois --low 3456788 --high 3456799
  python -m bacnet_toolshed.smoke_whois --address 192.168.204.12/24 --name OpenFddEdge --instance 599999
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser

from bacnet_toolshed.commission_agent import _cfg
from bacnet_toolshed.nic_bind import resolve_commission_cfg
from bacnet_toolshed.stack_args import bacnet_argv_from_cfg


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="BACnet Who-Is smoke test (Open-FDD)")
    p.add_argument("--low", type=int, default=None, help="Who-Is range low (default: DISCOVER_LOW)")
    p.add_argument("--high", type=int, default=None, help="Who-Is range high (default: DISCOVER_HIGH)")
    p.add_argument("--timeout", type=float, default=8.0, help="Seconds to wait for I-Am responses")
    p.add_argument("--address", default="", help="Override BACpypes3 bind (e.g. 192.168.204.12/24)")
    p.add_argument("--name", default="", help="Override BACnet device name")
    p.add_argument("--instance", type=int, default=None, help="Override local BACnet instance")
    p.add_argument("--debug", action="store_true", help="Enable bacpypes3 debug logging")
    return p


async def _run(args: argparse.Namespace) -> int:
    cfg = resolve_commission_cfg(_cfg())
    if args.address:
        cfg["BACNET_BIND"] = args.address
    if args.name:
        cfg["BACNET_NAME"] = args.name
    if args.instance is not None:
        cfg["BACNET_INSTANCE"] = str(args.instance)

    low = args.low if args.low is not None else int(cfg.get("DISCOVER_LOW", "1"))
    high = args.high if args.high is not None else int(cfg.get("DISCOVER_HIGH", "4194303"))
    argv = bacnet_argv_from_cfg(cfg)
    if args.debug:
        argv.append("--debug")

    print(f"BACpypes3 argv: {' '.join(argv)}", flush=True)
    print(f"Who-Is {low} .. {high}", flush=True)

    parser = SimpleArgumentParser()
    app = Application.from_args(parser.parse_args(argv))
    try:
        i_ams = await app.who_is(low, high)
        if not i_ams:
            print("No I-Am responses (check bind IP, firewall UDP/47808, and device range).", flush=True)
            return 1
        for i_am in i_ams:
            inst = i_am.iAmDeviceIdentifier[1]
            print(f"{inst} {i_am.pduSource}", flush=True)
        print(f"OK — {len(i_ams)} device(s)", flush=True)
        return 0
    finally:
        app.close()


def main() -> int:
    args = _build_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
