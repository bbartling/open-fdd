"""Scaffold an easy-aso HVAC bench agent and run basic endpoint preflight checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests


def _get_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"Expected JSON object from {url}, got: {type(body).__name__}")
    return body


def run_preflight(openfdd_base: str, mcp_base: str, supervisor_base: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["openfdd_health"] = _get_json(f"{openfdd_base.rstrip('/')}/health")
    out["mcp_health"] = _get_json(f"{mcp_base.rstrip('/')}/health")
    if supervisor_base and supervisor_base.strip():
        out["easy_aso_supervisor_health"] = _get_json(f"{supervisor_base.rstrip('/')}/health")
    return out


def scaffold_agent(output_path: Path, device_instance: str, sat_oid: str, fan_ao_oid: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    device_lit = repr(device_instance)
    sat_lit = repr(sat_oid)
    fan_lit = repr(fan_ao_oid)
    source = f'''"""Bench optimization agent scaffold for easy-aso RPC-docked mode."""

from __future__ import annotations

import asyncio
from easy_aso.runtime.rpc_docked import RpcDockedEasyASO


class BenchHvacOptimizationAgent(RpcDockedEasyASO):
    async def on_start(self) -> None:
        print("BenchHvacOptimizationAgent start")

    async def on_step(self) -> None:
        # Device key is diy-bacnet-server device instance, not IP.
        device = {device_lit}
        sat = await self.bacnet_read(device, {sat_lit})
        if sat is None:
            await asyncio.sleep(30)
            return

        # TODO: Replace with your real optimization sequence.
        # Example: nudge fan command based on SAT guardrail.
        cmd = 65.0 if float(sat) > 57.0 else 45.0
        await self.bacnet_write(device, {fan_lit}, cmd)
        await asyncio.sleep(60)

    async def on_stop(self) -> None:
        # Safe release pattern for bench override tests.
        await self.bacnet_write({device_lit}, {fan_lit}, "null", priority=8)
        await self.close_rpc_dock()
        print("BenchHvacOptimizationAgent stop/release complete")
'''
    output_path.write_text(source, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openfdd-base", default="http://127.0.0.1:8765")
    parser.add_argument("--mcp-base", default="http://127.0.0.1:8090")
    parser.add_argument(
        "--easy-aso-supervisor-base",
        default=None,
        help="Optional easy-aso supervisor base URL; omit to skip supervisor health preflight.",
    )
    parser.add_argument("--device-instance", default="3456789")
    parser.add_argument("--sat-oid", default="analog-input,1")
    parser.add_argument("--fan-ao-oid", default="analog-output,2")
    parser.add_argument(
        "--output",
        default="toolshed/scratch/easy_aso_bench_agent.py",
        help="Where to write the scaffolded agent.",
    )
    args = parser.parse_args()

    preflight = run_preflight(
        openfdd_base=args.openfdd_base,
        mcp_base=args.mcp_base,
        supervisor_base=args.easy_aso_supervisor_base,
    )
    print(json.dumps({"preflight": preflight}, indent=2))

    out = Path(args.output).resolve()
    scaffold_agent(
        output_path=out,
        device_instance=str(args.device_instance).strip(),
        sat_oid=str(args.sat_oid).strip(),
        fan_ao_oid=str(args.fan_ao_oid).strip(),
    )
    print(f"Wrote easy-aso bench scaffold: {out}")
    print(
        "Run with: EASY_ASO_AGENT_MODULE=toolshed.scratch.easy_aso_bench_agent "
        "EASY_ASO_AGENT_CLASS=BenchHvacOptimizationAgent easy-aso-agent run",
    )


if __name__ == "__main__":
    main()
