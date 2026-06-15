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
  Open-source <strong>supervisory fault detection</strong> for buildings — Arrow-native rules,
  optional DataFusion SQL rules for Rust-ready migration,
  optional <strong>PyPI</strong> embeddable runtime, and a full <strong>Docker/GHCR</strong> edge operator stack
  (BACnet, bridge API, dashboard, MCP).
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
  <a href="https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf"><img src="https://img.shields.io/badge/Docs-PDF_download-DC2626?style=for-the-badge" alt="PDF documentation"></a>
</p>

---

## Install / run

### Full Open-FDD edge stack (Docker / GHCR)

Use **GHCR** ([GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) — GitHub’s OCI image registry at `ghcr.io`) for BACnet polling, Operator Bridge API, React dashboard, historian, and MCP sidecar in a `docker pull` workflow.

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-bridge`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) | API, dashboard, historian |
| [`ghcr.io/bbartling/openfdd-commission`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-commission) | BACnet discover, read, poll |
| [`ghcr.io/bbartling/openfdd-mcp-rag`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp-rag) | MCP + doc-search |

**Prefer pinned release tags in production** (not floating `latest`). Set `OPENFDD_IMAGE_TAG` / `--image-tag` / `NEW_TAG` to the current release (today **3.1.3** — bump these on every release):

```bash
# Bootstrap a new edge host (no git clone) — creates ~/open-fdd, auth.env.local, BACnet bind
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
OPENFDD_IMAGE_TAG=3.1.3 bash /tmp/openfdd_edge_bootstrap.sh --start --image-tag 3.1.3

# Update an existing site — backup workspace, pull pinned GHCR tags, recreate containers
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
NEW_TAG=3.1.3 ./scripts/openfdd_site_update.sh
```

From a repo checkout: `./scripts/openfdd_edge_bootstrap.sh --start --image-tag 3.1.3`

Edge bootstrap: [Run with Docker images](https://bbartling.github.io/open-fdd/quick-start/docker/) · Site updates: [Updating the stack](https://bbartling.github.io/open-fdd/quick-start/updating/)

### Python package (PyPI)

Use PyPI when you only need the **embeddable Arrow-native FDD runtime** — lint, test, and run rules in your own pipelines (cloud, IoT, notebooks) **without** Docker.

```bash
pip install open-fdd
```

```python
import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime import run_arrow_rule


def high_sat(table, cfg, context=None):
    return pc.greater(table["SAT"], float(cfg["high"]))


table = pa.table({"SAT": [70.0, 90.0]})

result = run_arrow_rule(high_sat, table, {"high": 85})

print(result.true_count)  # 1
```


---

## Develop

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test,dev,analytics]"
pytest open_fdd/tests -q
```

Contributor layout: `AGENTS.md` and [developer docs](https://bbartling.github.io/open-fdd/developer/).

---

## License

MIT — see [LICENSE](LICENSE).
