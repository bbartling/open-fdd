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


Open-FDD is a free, open-source building-to-cloud pipeline for HVAC analytics and fault detection. The same stack runs on-premises or in the cloud: high-performance Apache Arrow storage and Apache DataFusion SQL, a Rust central service, React operator UI, Mosquitto MQTTS ingest, and fieldbus edge agents for BACnet, Modbus, and Haystack — plus REST APIs and CSV/zip import when you are not on live OT.

Deploy locally or as a cloud hub and pull building data over MQTTS, APIs, or files. Today’s product is SQL-based FDD and RCx on that Arrow/DataFusion engine; the roadmap is ML and clustering on the same foundation.

**FDD Rule Cookbook** — **62** public rules / **66** SQL registry ids: [datafusion-sql-cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/datafusion-sql-cookbook.html) · [pandas-cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html)

---


## Install / run GHCR images

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
# Cloud hub path: openfdd-fieldbus → MQTTS (see docs/operations/RAILWAY_DEPLOYMENT.md)
```

Update a running stack (pull, backup, rollback if health fails):

```bash
./scripts/openfdd_maint_update_resume.sh react nightly
```

AI Agent assistance : [AGENTS.md](https://github.com/bbartling/open-fdd/blob/master/AGENTS.md).


## PyPI package

```bash
pip install open-fdd
```

This is a library of rule-based FDD equations built with Pandas that serves as a reference implementation for the Open-FDD platform, which uses Apache DataFusion and SQL for production rules. It also includes tooling for AI agents to assist with engineering calculations, EnergyPlus modeling, Open-FDD stress testing, and more. Future capabilities include report writing and daily HVAC-fault email alerts—yet to be tested with Grok, OpenClaw, or the AI agent tooling of your choice.


<details>
<summary>💛 Support This Work</summary>

Support for Open-FDD directly funds the monthly time and labor required to keep the project moving forward, along with professional application-security testing to keep it strong, robust, free, and secure. Your support is greatly appreciated.


<p align="center">
  <a href="https://paypal.me/benbartling20/25"><img src="https://img.shields.io/badge/Donate-$25-0070BA?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate $25 via PayPal"></a>
  <a href="https://paypal.me/benbartling20/50"><img src="https://img.shields.io/badge/Donate-$50-0070BA?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate $50 via PayPal"></a>
  <a href="https://paypal.me/benbartling20/250"><img src="https://img.shields.io/badge/Donate-$250-0070BA?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate $250 via PayPal"></a>
  <a href="https://paypal.me/benbartling20"><img src="https://img.shields.io/badge/Donate-Custom%20Amount-0070BA?style=for-the-badge&logo=paypal&logoColor=white" alt="Choose a custom PayPal donation amount"></a>
</p>

</details>

## License

MIT — see [LICENSE](LICENSE).

Version **3.3.38** on tip · PyPI **4.4.2**
