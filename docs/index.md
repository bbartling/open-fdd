---
title: Home
nav_order: 1
description: "Open-FDD — open-source HVAC fault detection and building data platform."
---

# Open-FDD

Open-FDD is an open-source platform for **fault detection**, **BACnet integration**, and **operator analytics** at the building edge. It combines a React dashboard, FastAPI Operator Bridge, Python Rule Lab, local feather historian, and optional Brick/RDF modeling.

**Who it is for**

| Audience | Start here |
|----------|------------|
| IT / controls engineer trying the stack | [Quick Start — Docker](quick-start/) |
| Developer contributing or customizing | [Developer Guide](developer/) |
| Integrator wiring APIs | [Appendix — API routes](appendix/bridge_api) |
| Analyst authoring FDD rules | [Rule Cookbook](rule-cookbook/) · [Fault Codes](fault-codes/) |

## What you get

| Component | Purpose |
|-----------|---------|
| **Operator Bridge** | Web API + dashboard (trends, faults, Rule Lab, model tools) |
| **BACnet tools** | Discover, read, poll, optional supervised writes |
| **Rule Lab** | Arrow-native `apply_faults_arrow(table, cfg)` rules on feather historian data |
| **Local historian** | Feather-based telemetry store on the edge host |
| **Brick / RDF model** | Equipment and point semantics for bindings and analytics |
| **Docker images** | Published on GHCR — pull and run without building from source |
| **Python package** | `pip install open-fdd` for offline CSV/notebook and YAML engine use |

## Two paths

### Try it with Docker (recommended)

Pull published images from `ghcr.io/bbartling/`, configure auth and BACnet env files, start the stack, open the dashboard.

→ [Quick Start](quick-start/)

### Develop locally

Clone the repo, create `workspace/auth.env.local`, build images, run tests, submit a PR.

→ [Developer Guide](developer/)

## Distribution

| Channel | Use when |
|---------|----------|
| **GHCR images** `ghcr.io/bbartling/openfdd-*` | Production or trial edge deploy |
| **This repository** | Custom builds, BACnet commissioning, Rule Lab development |
| **PyPI** [`open-fdd`](https://pypi.org/project/open-fdd/) | Library-only pandas/YAML workflows (no full UI) |

## License

MIT — see repository `LICENSE`.
