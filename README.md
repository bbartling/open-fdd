# Open-FDD

The Open-FDD runtime is now **Arrow-native by default**. Rules operate over Arrow Tables and return Arrow BooleanArrays or ChunkedArrays. This avoids Python row loops and enables columnar, threaded, batch-oriented execution for large HVAC histories.

See [Arrow-native runtime](docs/developer/arrow-native-runtime.md).

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
  <strong>Arrow-native</strong> rule-based HVAC fault detection — columnar Python rules in the dashboard, optional YAML via <code>open_fdd.engine</code>, summaries via <code>open_fdd.reports</code>
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><strong>bbartling.github.io/open-fdd</strong></a>
  &nbsp;·&nbsp;
  <a href="https://pypi.org/project/open-fdd/"><strong>PyPI open-fdd</strong></a>
  &nbsp;·&nbsp;
  Docker images via <code>./scripts/docker_build.sh</code>
</p>

---

Everything you need to run the **operator bridge**, BACnet commissioning, Rule Lab, feather historian, and edge deploy lives in the **[online documentation](https://bbartling.github.io/open-fdd/)** — start with [Getting started](https://bbartling.github.io/open-fdd/getting_started/).

| Topic | Doc |
|-------|-----|
| Deploy checklist + AI can/cannot | [Getting started](https://bbartling.github.io/open-fdd/getting_started/) |
| Docker containers + Acme flow | [Edge deploy (Docker)](https://bbartling.github.io/open-fdd/edge_deploy_docker/) |
| Local Ollama (check-engine) | [Local Ollama](https://bbartling.github.io/open-fdd/local_ollama/) |
| BACnet discover / read / write / poll | [BACnet capabilities](https://bbartling.github.io/open-fdd/bacnet/capabilities/) |
| Bridge REST API | [Bridge API](https://bbartling.github.io/open-fdd/appendix/bridge_api/) |
| Security / LAN hardening | [Security hardening](https://bbartling.github.io/open-fdd/security_hardening/) |

**Distribution:** The **operator web app** (bridge + dashboard) runs from this repo via Docker/Ansible. **`pip install open-fdd`** provides the YAML engine, **`open_fdd.playground`** (`evaluate()` rules), and optional reports — see [PyPI docs](https://bbartling.github.io/open-fdd/open_fdd_playground_pypi.html).

---

## Develop locally

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd

./scripts/build_and_test.sh
./scripts/docker_maintenance.sh --prune --rebuild
./scripts/openfdd_stack.sh health
```

See [Getting started](https://bbartling.github.io/open-fdd/getting_started/) and `AGENTS.md` for contributor layout.

---

## License

MIT — see [LICENSE](LICENSE).
