# Open-FDD

<p align="center">
  <a href="https://discord.gg/Ta48yQF8fC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/ci.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Beta-blue" alt="Beta">
  <img src="https://img.shields.io/badge/Python-%3E%3D3.10-blue?logo=python&logoColor=white" alt="Python 3.10+">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png" alt="Open-FDD logo" width="440">
</p>

<p align="center">
  Open-source <strong>supervisory fault detection</strong> that runs <strong>locally on the edge</strong> — BACnet polling,
  <strong>BRICK</strong> equipment and point modeling, and <strong>AI-assisted</strong> commissioning, rule assignment, and diagnostics.
  Author <strong>Arrow-native</strong> Python rules in Rule Lab; trend plots and live operations from the Operator Bridge.
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
  <a href="https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf"><img src="https://img.shields.io/badge/Docs-PDF_download-DC2626?style=for-the-badge" alt="PDF documentation"></a>
</p>



---

## Get started

**Docker (Operator Bridge)** — published on [GitHub Container Registry](https://github.com/bbartling?tab=packages). Pull the three edge images (default tag `latest`):

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-bridge`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) | API, dashboard, historian |
| [`ghcr.io/bbartling/openfdd-commission`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-commission) | BACnet discover, read, poll |
| [`ghcr.io/bbartling/openfdd-mcp-rag`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp-rag) | Doc-search sidecar |

```bash
docker pull ghcr.io/bbartling/openfdd-bridge:latest
docker pull ghcr.io/bbartling/openfdd-commission:latest
docker pull ghcr.io/bbartling/openfdd-mcp-rag:latest
```

Edge bootstrap (compose, `workspace/`, auth): [Run with Docker images](https://bbartling.github.io/open-fdd/quick-start/).

**Python (`open-fdd`)** — [PyPI](https://pypi.org/project/open-fdd/) package for Arrow-native rule linting and offline Rule Lab work:

```bash
pip install open-fdd
```

Full operator stack (BACnet polling, UI, assignments): use the Docker images above. Local clone, tests, and contributor layout: `AGENTS.md` and [developer docs](https://bbartling.github.io/open-fdd/developer/).

---

## License

MIT — see [LICENSE](LICENSE).
