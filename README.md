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


> **Open-source semantic building analytics and HVAC supervisory fault detection. Local-first. On-premises. Vendor-neutral. Free to run at the edge or offline.**

Open-FDD is an open-source analytics platform for building automation that combines **semantic knowledge graph modeling**, **live operational technology (OT) data**, and **high-performance columnar analytics**.

The platform includes:

- Semantic building modeling using **Project Haystack** knowledge graphs
- JWT authentication and a modern React web interface
- Apache Arrow & Feather columnar data storage
- Apache DataFusion SQL analytics and fault detection (59+ cookbook rules)
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

## Install / run

### GHCR images

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-central`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-central) | MQTTS ingest, Feather historian, FDD registry, REST API |
| [`ghcr.io/bbartling/openfdd-ui`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-ui) | React operator dashboard (Caddy → central) |
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

## Develop

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
./scripts/openfdd_stack_up.sh csv --build   # or: cargo run -p openfdd-central
./scripts/openfdd_ui_dev.sh                 # Vite :5173 → API :8080
```

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
