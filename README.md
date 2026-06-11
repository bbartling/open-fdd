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

Use GHCR for BACnet polling, Operator Bridge API, React dashboard, historian, and MCP sidecar.

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-bridge`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) | API, dashboard, historian |
| [`ghcr.io/bbartling/openfdd-commission`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-commission) | BACnet discover, read, poll |
| [`ghcr.io/bbartling/openfdd-mcp-rag`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp-rag) | MCP + doc-search |

**Prefer pinned release tags in production** (not floating `latest`):

```bash
export OPENFDD_IMAGE_TAG=3.0.30   # match your release
docker pull ghcr.io/bbartling/openfdd-bridge:${OPENFDD_IMAGE_TAG}
docker pull ghcr.io/bbartling/openfdd-commission:${OPENFDD_IMAGE_TAG}
docker pull ghcr.io/bbartling/openfdd-mcp-rag:${OPENFDD_IMAGE_TAG}
```

Edge bootstrap: [Run with Docker images](https://bbartling.github.io/open-fdd/quick-start/docker/).

### Python package (PyPI)

Use PyPI when you only need the **embeddable Arrow-native FDD runtime** — lint, test, and run rules in your own pipelines (cloud, IoT, notebooks) **without** Docker.

```bash
pip install open-fdd
```

```python
import pyarrow as pa
from open_fdd.arrow_runtime import run_arrow_rule

code = '''
import pyarrow.compute as pc
def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["SAT"], float(cfg["high"]))
'''
result = run_arrow_rule(code, pa.table({"SAT": [70.0, 90.0]}), {"high": 85})
print(result.true_count)
```

| Need | Use |
|------|-----|
| Run FDD in your Python / cloud pipeline | **PyPI** `open-fdd` |
| BACnet + UI + bridge on an edge host | **GHCR** Docker images |
| Portfolio / MCP agent over Tailscale | Docker stack + [portfolio docs](https://bbartling.github.io/open-fdd/portfolio/) |

Examples: [`examples/`](examples/). Release: [developer/release-process](https://bbartling.github.io/open-fdd/developer/release-process/).

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
