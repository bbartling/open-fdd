---
title: Home
nav_order: 1
---

# Open-FDD (PyPI engine)

This repository publishes the **`open-fdd`** package on **[PyPI](https://pypi.org/project/open-fdd/)**. Install with `pip install open-fdd` and use **`open_fdd.engine`** (`RuleRunner`, YAML-defined rules on **pandas**), **`open_fdd.schema`**, **`open_fdd.reports`**, and optional extras (`[brick]`, `[bacnet]`, `[viz]`, `[dev]`). The optional **`openfdd_engine`** namespace re-exports the same engine API for legacy imports.

The **full on-prem AFDD platform** (Docker Compose, FastAPI, BACnet and weather scrapers, FDD loop, React UI, `bootstrap.sh`) lives in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**. That stack installs **`open-fdd` from PyPI** inside containers; platform Python code is **`openfdd_stack.platform`**. Published stack documentation: **[bbartling.github.io/open-fdd-afdd-stack](https://bbartling.github.io/open-fdd-afdd-stack/)**.

---

## Who this site is for

| Audience | Start here |
|----------|------------|
| **Library users** (embed rules in your own IoT or analytics stack) | [Getting started](getting_started) · [Engine-only / IoT](howto/engine_only_iot) · [Rule authoring](rules/overview) |
| **Contributors** to the engine | [Contributing](contributing) · [Developer guide](appendix/developer_guide) · [TESTING.md](https://github.com/bbartling/open-fdd/blob/master/TESTING.md) (repo root) |
| **AFDD operators** (Docker, UI, BACnet, TimescaleDB) | **[Stack docs](https://bbartling.github.io/open-fdd-afdd-stack/)** — bootstrap, ports, security, data model |

Many pages below were written when engine and stack lived in one tree. Sections that describe **`./scripts/bootstrap.sh`**, **Caddy**, **Grafana**, or **port 5173** apply to **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** deployments, not to `pip install open-fdd` alone.

---

## Quick start (library)

```bash
pip install open-fdd
```

```python
from open_fdd import RuleRunner

runner = RuleRunner("/path/to/rules")
df_out = runner.run(df)
```

Clone and run tests:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
pytest open_fdd/tests/ -v --tb=short
```

---

## Documentation (engine-focused index)

| Section | Description |
|---------|-------------|
| [Getting started](getting_started) | Install from PyPI, minimal usage, tests, pointer to the AFDD stack |
| [System overview](overview) | How the engine fits in; reference architecture for full stack (separate repo) |
| [Modular architecture](modular_architecture) | Collector / model / engine / UI boundaries (orchestrated in the stack repo) |
| [Fault rules for HVAC](rules/overview) | Rule types, expression cookbook, [test bench catalog](rules/test_bench_rule_catalog) |
| [How-to guides](howto/index) | [Engine-only / IoT](howto/engine_only_iot), [openfdd-engine vs `open_fdd.engine`](howto/openfdd_engine), [open-fdd on PyPI](howto/openfdd_engine_pypi) |
| [Standalone CSV / pandas](standalone_csv_pandas) | Running rules without the platform database |
| [Appendix](appendix) | [Technical reference](appendix/technical_reference), [Developer guide](appendix/developer_guide) |
| [Contributing](contributing) | PRs, scope, where to report issues |

### Platform and operations (reference)

These chapters describe the **AFDD stack** deployment model (API, scrapers, React app, Caddy, optional Grafana). They remain here for integrators and cross-links; when in doubt, prefer the **[stack documentation site](https://bbartling.github.io/open-fdd-afdd-stack/)** for URLs, ports, and bootstrap flags.

| Section | Description |
|---------|-------------|
| [BACnet](bacnet/overview) | Discovery, RDF/Brick (with stack UI or API) |
| [Data modeling](modeling/overview) | Sites, equipment, points, SPARQL, TTL |
| [Configuration](configuration) | Platform config in the RDF graph (`stack` repo) |
| [Security & Caddy](security) | Auth, reverse proxy, TLS |
| [Operations](operations/index) | Integrity sweep, testing plan, MCP RAG, runbooks |
| [Using the React dashboard](frontend) | Stack UI only — page links to [open-fdd-afdd-stack docs](https://bbartling.github.io/open-fdd-afdd-stack/frontend) |
| [Appendix: API reference](appendix/api_reference) | REST summary for the stack API |

---

## Behind the firewall

Open-FDD’s **design center** is on-prem analytics and control of building data. The **engine** runs anywhere Python runs; the **AFDD stack** adds databases, scrapers, and APIs on your network. Cloud export patterns are **pull-based** from your integration (see [Cloud export](concepts/cloud_export) when using the stack API).

---

## License

MIT — see the [repository](https://github.com/bbartling/open-fdd).
