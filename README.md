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
    <img src="https://img.shields.io/badge/FDD%20Rule%20Cookbook-62%20rules%20SQL%20%2B%20Pandas-DC2626?style=for-the-badge" alt="FDD Rule Cookbook — DataFusion SQL + Pandas">
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


> **Semantic building analytics and HVAC fault detection — local-first, on-premises, vendor-neutral.**

Open-FDD maps Haystack-style JSON point roles to live or historical OT/CSV data and runs fault detection with **DataFusion SQL** over an **Apache Arrow** historian. The operator stack is **Rust central** and **React web**; the SPA talks to central `/api` only.

- **62** cookbook rules (**66** SQL registry ids) — FDD, RCx, Overview, findings
- GHCR images: `central`, `web`, `fieldbus`, `mqtt`, `mcp`
- [PyPI `open-fdd`](https://pypi.org/project/open-fdd/) — pandas cookbooks and ECM for notebooks; not the product runtime

**Ready today — local, behind the firewall:** `./scripts/openfdd_stack_up.sh react` for CSV/zip FDD on your LAN or VPN. Not intended for the public internet.

**Experimental cloud lab:** Railway can run the minimal `openfdd-central` + `openfdd-web` CSV/package stack directly from GHCR. The web image supports a runtime central upstream for Railway private DNS. See [Railway deployment](docs/operations/RAILWAY_DEPLOYMENT.md). This is a lab/demo path, not a production-hardening claim.

**Coming soon:** OT edge (`react-ot` — BACnet, Modbus, Haystack, MQTTS) and managed **cloud hosting**. Internet-facing deployment with production security hardening targets **Fall 2026**.

---

## FDD Rule Cookbook (the heart of the project)

The **[HVAC FDD Rule Cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/)** is the validated catalog of **62 fault-detection rules**, published in two parity-matched flavors:

- **[DataFusion SQL cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/datafusion-sql-cookbook.html)** — copy-paste SQL that runs on the edge/central Arrow historian
- **[Pandas cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html)** — the same rules for notebooks, CSV exports, and RCx studies

---

## Install / run

### GHCR images

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-central`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-central) | MQTTS ingest, Feather historian, DataFusion FDD, REST `/api` |
| [`ghcr.io/bbartling/openfdd-web`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-web) | React operator SPA (browser → central `/api` only) |
| [`ghcr.io/bbartling/openfdd-fieldbus`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-fieldbus) | BACnet / Modbus / Haystack / JSON edge |
| [`ghcr.io/bbartling/openfdd-mqtt`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mqtt) | Mosquitto MQTTS broker |
| [`ghcr.io/bbartling/openfdd-mcp`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp) | Optional slim MCP stdio sidecar → central API |

### Run

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_JWT_SECRET='change-me'
export OPENFDD_ADMIN_PASSWORD='change-me'

./scripts/openfdd_stack_up.sh react       # local CSV lab (ready today)
./scripts/openfdd_stack_up.sh csv         # central + web only
# react-ot (OT edge) — coming soon; bench preview only
```

Update a running stack (pull, backup, rollback if health fails):

```bash
./scripts/openfdd_maint_update_resume.sh react nightly
```

UI `http://127.0.0.1:3000` · API `http://127.0.0.1:8080` · [build recipes](docs/operations/build-recipes.md)

### MCP

Open-FDD does **not** ship an embedded AI chatbot. External agents connect via MCP or REST — see [external agents](docs/examples/external-agents.md).

```bash
docker run -i --rm --network host \
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \
  -e OPENFDD_MCP_TOKEN="$TOKEN" \
  ghcr.io/bbartling/openfdd-mcp:nightly
```

Tool list: [mcp/README.md](mcp/README.md).

---

## PyPI package

```bash
pip install open-fdd
```

Library for notebooks and ECM helpers — not the operator stack. See [PyPI](https://pypi.org/project/open-fdd/) and [docs](https://bbartling.github.io/open-fdd/).

---

## Develop

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
./scripts/openfdd_stack_up.sh react --build
cd frontend/web && npm ci && npm run dev
```

Rust: `cargo test --workspace`

## Releases

GHCR images build on every `master` merge. Set **`OPENFDD_IMAGE_TAG=nightly`** (or `sha-<7>` to pin). Beta/stable are not published yet — [release policy](https://bbartling.github.io/open-fdd/operations/release-channels.html).

Intended for **LAN / VPN / OT networks**, not public internet hosting.

## Security

Do **not** report vulnerabilities through public GitHub issues or discussions. Use [GitHub Private Vulnerability Reporting](https://github.com/bbartling/open-fdd/security/advisories/new). See [SECURITY.md](SECURITY.md) for what to include and how to redact sensitive OT/deployment evidence.

## License

MIT — see [LICENSE](LICENSE).

Version **3.3.3** on `master` · PyPI **4.4.2**
