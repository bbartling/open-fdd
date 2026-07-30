# Open-FDD

<p align="center">
  <a href="https://discord.gg/Ta48yQF8fC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/rust-ci.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/rust-ci.yml/badge.svg?branch=master" alt="CI"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/docs-pages.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/docs-pages.yml/badge.svg?branch=master" alt="Docs"></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Alpha-orange" alt="Alpha">
  <img src="https://img.shields.io/badge/Rust-1.93-orange?logo=rust&logoColor=white" alt="Rust 1.93">
  <img src="https://img.shields.io/badge/Apache%20Arrow-53-blue" alt="Arrow">
  <img src="https://img.shields.io/badge/DataFusion-SQL-purple" alt="DataFusion">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image_new_chiller.png" alt="Open-FDD logo" width="440">
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/">
    <img src="https://img.shields.io/badge/Docs-online-2563EB?style=for-the-badge" alt="Online docs">
  </a>
  <a href="https://bbartling.github.io/open-fdd/rules/cookbook/">
    <img src="https://img.shields.io/badge/FDD%20Rule%20Cookbook-59%20rules%20SQL%20%2B%20Pandas-DC2626?style=for-the-badge" alt="FDD Rule Cookbook — DataFusion SQL + Pandas">
  </a>
  <a href="https://pypi.org/project/open-fdd/">
    <img src="https://img.shields.io/pypi/v/open-fdd?style=for-the-badge&label=PyPI&color=3775A9" alt="Open-FDD on PyPI">
  </a>
  <a href="https://bbartling.github.io/open-fdd/quick-start/docker-ghcr.html">
    <img src="https://img.shields.io/badge/Quick%20Start-GHCR%20stack-059669?style=for-the-badge" alt="Quick start">
  </a>
  <a href="https://arrow.apache.org/">
    <img src="https://img.shields.io/badge/Apache%20Arrow-columnar%20data-0B7285?style=for-the-badge" alt="Apache Arrow">
  </a>
  <a href="https://datafusion.apache.org/">
    <img src="https://img.shields.io/badge/DataFusion-SQL%20engine-6D28D9?style=for-the-badge" alt="Apache DataFusion">
  </a>
</p>


> **Open-source semantic building analytics and HVAC supervisory fault detection. Local-first. On-premises. Vendor-neutral. Free to run at the edge or offline.**

Open-FDD is an open-source analytics platform for building automation that combines **semantic knowledge graph modeling**, **live operational technology (OT) data**, and **high-performance columnar analytics**.

The platform includes:

- Semantic building modeling using **Project Haystack** knowledge graphs
- JWT authentication and a modern **Streamlit** engineering UI (`openfdd-ui`)
- Apache Arrow & Feather columnar data storage
- Apache DataFusion SQL analytics and fault detection (59 cookbook rules; 63 SQL registry IDs)
- BACnet, Modbus, Haystack, and JSON API drivers (fieldbus container)
- Interactive plotting, dashboards, and CSV job workflows
- Optional **external** agent integration via MCP stdio and JWT REST (no embedded chatbot)
- Docker compose **build recipes** published to GitHub Container Registry

Open-FDD supports flexible deployment recipes:

### Standalone (all-on-edge)

`mqtt` + `central` + `ui` + `fieldbus` on one host — internal MQTTS, full OT + analytics.

### Central hub

`mqtt` + `central` + `ui` — cloud or LAN hub; remote fieldbus edges attach over MQTTS.

### Fieldbus edge only

`fieldbus` alone — attach to a remote central via MQTTS.

### CSV-only

`central` + `ui` — bulk CSV jobs and FDD without pulling mqtt or fieldbus images.

---

## FDD Rule Cookbook (the heart of the project)

The **[HVAC FDD Rule Cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/)** is the validated catalog of **59 fault-detection rules**, published in two parity-matched flavors:

- **[DataFusion SQL cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/datafusion-sql-cookbook.html)** — copy-paste SQL that runs on the edge/central Arrow historian
- **[Pandas cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html)** — the same rules for notebooks, CSV exports, and RCx studies

Rules use generic Haystack semantic roles, so they are portable across any modeled site. CI enforces a minimum of 59 rule headings in both cookbooks (`scripts/cookbook_parity_check.py`) — the catalog can never shrink.

**Count contract (honest):** the public dual cookbooks document **59** rules. The production DataFusion SQL registry (`sql_rules/registry.yaml`) currently lists **63** rule IDs (59 cookbook-covered + SQL-only additions). See the [parity matrix](docs/rules/cookbook/parity-matrix.md). Do not treat badge “59” as the registry length.

---

## Install / run

### GHCR images

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-central`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-central) | MQTTS ingest, Feather historian, FDD registry, REST API |
| [`ghcr.io/bbartling/openfdd-ui`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-ui) | Streamlit operator UI (vibe19 + WattLab export → central) |
| [`ghcr.io/bbartling/openfdd-fieldbus`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-fieldbus) | BACnet / Modbus / Haystack edge |
| [`ghcr.io/bbartling/openfdd-mqtt`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mqtt) | Mosquitto MQTTS broker |
| [`ghcr.io/bbartling/openfdd-mcp`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp) | Optional slim MCP stdio sidecar → central API |

Open-FDD does **not** ship an embedded AI chatbot. External agents connect via MCP or REST — see [docs/examples/external-agents.md](docs/examples/external-agents.md).

### Quick start (standalone)

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_JWT_SECRET='change-me'
export OPENFDD_ADMIN_PASSWORD='change-me'
./scripts/openfdd_stack_up.sh standalone
# UI http://127.0.0.1:3000  API http://127.0.0.1:8080
```

### Other recipes

```bash
./scripts/openfdd_stack_up.sh csv          # central + ui only
./scripts/openfdd_stack_up.sh central      # hub without fieldbus
./scripts/openfdd_stack_up.sh edge         # fieldbus only (set OPENFDD_MQTT_HOST)
```

See [Build recipes](docs/operations/build-recipes.md) and [docker/VERSION_MANIFEST.md](docker/VERSION_MANIFEST.md).

### MCP (external agents)

```bash
docker run -i --rm --network host \
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \
  -e OPENFDD_MCP_TOKEN="$TOKEN" \
  ghcr.io/bbartling/openfdd-mcp:nightly
```

Full tool list: [mcp/README.md](mcp/README.md).

---

## PyPI package (`pip install open-fdd`)

The [PyPI package](https://pypi.org/project/open-fdd/) is a **library** surface — not a substitute for the operator stack.

| Install | What you get |
|---------|----------------|
| `pip install open-fdd` | ECM engineering helpers / workbook builders |
| `pip install "open-fdd[oracle]"` | Optional pandas oracle for rule screening |
| `pip install "open-fdd[reporting]"` | Engineering findings / report writers |
| `pip install "open-fdd[vibe19]"` | vibe19-aligned pandas rule helpers |

**FDD (DataFusion SQL)** — historian, registry, Streamlit UI, BACnet/Modbus — ships in the **GHCR container stack** (`openfdd-central` / `openfdd-ui` / …), not as the default PyPI runtime. Use `./scripts/openfdd_stack_up.sh` (above) for that path.

Docs: [ECM](docs/ecm/README.md) · [pandas cookbook](docs/rules/cookbook/pandas-cookbook.md) · [DataFusion SQL cookbook](docs/rules/cookbook/datafusion-sql-cookbook.md)

---

## Develop

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
./scripts/openfdd_stack_up.sh csv --build   # or: cargo run -p openfdd-central
./scripts/openfdd_ui_dev.sh                 # Streamlit UI → central API :8080
```

The production operator UI is **Streamlit** (`services/ui` / `ghcr.io/bbartling/openfdd-ui`), not a Vite/Caddy SPA.

Native Rust: `cargo test --workspace`

## Releases

| Channel | Tag | When to use |
|---------|-----|-------------|
| **Nightly** | `:nightly` / `:sha-*` | Dev, bench, agents (default) |
| **Beta** | `:beta` / `3.3.0-beta.N` | Pilot sites after bench sign-off |
| **Stable** | `:latest` / `3.3.0` | Production (when promoted) |

**Maintainers:** Actions → **Rust Release** → set `VERSION` match + channel `beta` or `stable`.

Full policy: [Release channels](https://bbartling.github.io/open-fdd/operations/release-channels.html) · [GHCR images](https://bbartling.github.io/open-fdd/operations/ghcr-images.html)

Open-FDD is for **LAN / VPN / OT networks**, not public internet hosting.

## License

MIT — see [LICENSE](LICENSE).

Version: **3.3.0-beta.1** (next release candidate — see [release channels](https://bbartling.github.io/open-fdd/operations/release-channels.html))
