# Open-FDD

<p align="center">
  <a href="https://discord.gg/Ta48yQF8fC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/rust-ci.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/rust-ci.yml/badge.svg?branch=master" alt="CI"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/docs-pages.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/docs-pages.yml/badge.svg?branch=master" alt="Docs"></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Alpha-orange" alt="Alpha">
  <img src="https://img.shields.io/badge/Rust-1.93-orange?logo=rust&logoColor=white" alt="Rust 1.93">
  <img src="https://img.shields.io/badge/TimescaleDB-PostgreSQL-blue" alt="TimescaleDB">
  <img src="https://img.shields.io/badge/SQL-FDD-purple" alt="SQL FDD">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image_new_chiller.png" alt="Open-FDD logo" width="440">
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/">
    <img src="https://img.shields.io/badge/Docs-online-2563EB?style=for-the-badge" alt="Online docs">
  </a>
  <a href="https://bbartling.github.io/open-fdd/rules/">
    <img src="https://img.shields.io/badge/FDD%20Rule%20Cookbook-71%20%2F%2077%20SQL%20%2B%20Pandas-DC2626?style=for-the-badge" alt="FDD Rule Cookbook — 71 / 77 SQL + Pandas">
  </a>
  <a href="https://pypi.org/project/open-fdd/">
    <img src="https://img.shields.io/pypi/v/open-fdd?style=for-the-badge&label=PyPI&color=3775A9" alt="Open-FDD on PyPI">
  </a>
  <a href="https://bbartling.github.io/open-fdd/quick-start/docker-ghcr.html">
    <img src="https://img.shields.io/badge/Quick%20Start-GHCR%20stack-059669?style=for-the-badge" alt="Quick start">
  </a>
  <a href="https://www.timescale.com/">
    <img src="https://img.shields.io/badge/TimescaleDB-historian-0B7285?style=for-the-badge" alt="TimescaleDB historian">
  </a>
  <a href="https://bbartling.github.io/open-fdd/architecture/adr-010-timescale-hard-cutover.html">
    <img src="https://img.shields.io/badge/ADR--010-Timescale%20only-6D28D9?style=for-the-badge" alt="ADR-010 Timescale only">
  </a>
</p>


Open-FDD is a free, open-source building-to-cloud pipeline for HVAC analytics and fault detection. It is very friendly to AI agents. The same stack runs on-premises or in the cloud: a time-series database (Timescale on PostgreSQL) for faults, where analytics are produced, a Rust central service, React operator UI, Mosquitto MQTTS ingest, and fieldbus edge agents for BACnet, Modbus, and Haystack — plus REST APIs and CSV/zip import when you are not on live OT. The product services are written in Rust, with Python tooling for tests. Machine learning and clustering are on the roadmap for that same foundation.

Python tooling is for tests. A PyPI package ships pandas FDD for notebooks and checks, plus report tools that write a PDF from mapped HVAC history. AI agents install that package, read the project skills, and run the CLI beside the live stack.

---


## Install / run GHCR images

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-central`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-central) | MQTTS ingest, **Timescale** historian, SQL FDD, REST `/api` |
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

Third-party / oracle library (`open_fdd.rules`) for notebooks and parity — not the product request path. Production FDD is Timescale / PostgreSQL SQL (`sql/fdd`, [ADR-010](docs/architecture/adr-010-timescale-hard-cutover.md)). Human catalogs: [Rule Cookbook](https://bbartling.github.io/open-fdd/rules/) · [pandas-cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html).


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

Version **4.0.1** on tip · PyPI **4.4.9**
