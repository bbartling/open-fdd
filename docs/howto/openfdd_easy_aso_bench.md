---
title: Open-FDD + Easy-ASO test bench
parent: How-to Guides
nav_order: 14
description: "Co-run Open-FDD and easy-aso with diy-bacnet-server for optimization script experiments validated by FDD."
---

# Open-FDD + Easy-ASO test bench

Use this when you want one operator/agent workflow that does both:

- **FDD + analytics** in Open-FDD (bridge, plots, rules, readiness), and
- **supervisory optimization loops** in easy-aso against the same DIY BACnet RPC core.

## Architecture

- `diy-bacnet-server` is the BACnet wire-facing core (JSON-RPC surface).
- Open-FDD bridge ingests BACnet snapshots and runs FDD/rules/plots.
- easy-aso runs optimization agent loops (read/write/release) via the same JSON-RPC backend.

Open-FDD and easy-aso both avoid duplicating a second BACnet UDP stack when using JSON-RPC.

## Ports (recommended)

- Open-FDD bridge: `8765`
- Open-FDD MCP RAG: `8090`
- Open-FDD UI (vite dev): `5173`
- DIY BACnet JSON-RPC: `8080`
- easy-aso supervisor: `18090` (intentionally not `8090`)

## Install

Open-FDD with easy-aso integration extras:

```bash
pip install "open-fdd[desktop,optimization]"
```

`optimization` installs `easy-aso[platform]`.

## Boot sequence

1. Start Open-FDD (`scripts/start-local.ps1` or `scripts/start-local.sh`).
2. Start DIY BACnet server (same endpoint open-fdd and easy-aso can reach).
3. Start easy-aso supervisor:

```bash
easy-aso-supervisor --host 0.0.0.0 --port 18090
```

4. Validate health:
   - `GET http://127.0.0.1:8765/health`
   - `GET http://127.0.0.1:8090/health`
   - `GET http://127.0.0.1:18090/health`

## Agent workflow pattern

For AI-assisted experiments:

1. Use Open-FDD readiness + plots to identify control opportunities.
2. Generate a candidate optimization agent script under `toolshed/scratch/`.
3. Run the script against DIY BACnet JSON-RPC (`BACNET_RPC_API_KEY` as needed).
4. Re-check Open-FDD plots/FDD outputs for before/after validation.
5. Promote stable helpers into `toolshed/published/` via PR.

Use `toolshed/published/easy_aso_bench_runner.py` to scaffold a bench agent and run preflight checks.

## Safety defaults

- Keep write actions bounded and reversible.
- Always implement `on_stop` release logic in easy-aso agents.
- Use Open-FDD preview-first flows (`commit:false`) before mutating model/rules.
- Keep bearer tokens in env vars, never in committed files.

## Private-LAN Option A deployment bundle

For a ready baseline with one authenticated ingress:

- `scripts/linux-lan/Caddyfile`
- `scripts/linux-lan/bench.env.example`
- `scripts/linux-lan/systemd/*.service`
- `scripts/linux-lan/README.md`

This keeps backend services private and fronts them with Caddy Basic Auth on LAN.
