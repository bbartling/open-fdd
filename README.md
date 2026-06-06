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
  <strong>Arrow-native</strong> HVAC fault detection — columnar Python rules in the dashboard, optional YAML via <code>open_fdd.engine</code>, summaries via <code>open_fdd.reports</code>.
</p>

<p align="center">
  <a href="https://pypi.org/project/open-fdd/"><strong>PyPI open-fdd</strong></a>
</p>

---

## Develop locally

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd

./scripts/build_and_test.sh
```

**Docker** — build images locally or pull published tags from GHCR:

```bash
./scripts/docker_build.sh

# or pull from GitHub Container Registry (tags on ghcr.io/bbartling/openfdd-bridge)
export OPENFDD_IMAGE_TAG=2026.06.07-edge
docker pull ghcr.io/bbartling/openfdd-bridge:${OPENFDD_IMAGE_TAG}
docker pull ghcr.io/bbartling/openfdd-commission:${OPENFDD_IMAGE_TAG}
docker pull ghcr.io/bbartling/openfdd-mcp-rag:${OPENFDD_IMAGE_TAG}
./scripts/openfdd_stack.sh up
```

Documentation: [bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/) — Docker, edge deploy, Rule Lab, and contributor layout (`AGENTS.md`).

---

## License

MIT — see [LICENSE](LICENSE).
