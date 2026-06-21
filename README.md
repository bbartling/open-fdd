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
  <strong>Open-source HVAC supervisory fault detection for buildings.</strong><br>
  Local-first, on-prem, vendor-neutral, and free to run at the edge.
</p>

<p align="center">
  Arrow-native rules · optional DataFusion SQL rules · PyPI embeddable runtime · Docker/GHCR edge stack<br>
  BACnet · bridge API · dashboard · MCP · AI-assisted commissioning and diagnostics
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
  <a href="https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf"><img src="https://img.shields.io/badge/Docs-PDF_download-DC2626?style=for-the-badge" alt="PDF documentation"></a>
</p>

---

## What Open-FDD is

Open-FDD is an edge-oriented fault detection and diagnostics stack for HVAC and building automation systems.

It is designed for:

- running locally on an OT/LAN building edge host;
- collecting telemetry from BACnet, Niagara, JSON APIs, and other site adapters;
- evaluating Arrow-native FDD rules against columnar telemetry;
- optionally running SQL-style FDD rules through DataFusion;
- supporting AI-assisted commissioning, model review, diagnostics, and report workflows;
- keeping the building data on-prem unless the operator chooses otherwise.

The core Python package is intentionally small and Arrow-first. The full operator experience is delivered through GHCR Docker images.

---

## Install / run

### Full Open-FDD edge stack

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-bridge`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) | API, dashboard, historian |
| [`ghcr.io/bbartling/openfdd-commission`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-commission) | BACnet discover, read, poll, override scan |
| [`ghcr.io/bbartling/openfdd-mcp-rag`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp-rag) | MCP + doc search / knowledge sidecar |

GHCR publishes multi-arch images (`linux/amd64` and `linux/arm64`) from release `3.1.6` onward. Edge scripts auto-detect the host CPU and pull the matching manifest.

| Host CPU (`uname -m`) | Docker platform | Typical hardware |
|-----------------------|-----------------|------------------|
| `x86_64`, `amd64` | `linux/amd64` | Intel/AMD servers, VMs |
| `aarch64`, `arm64` | `linux/arm64` | Raspberry Pi 4/5 with 64-bit OS |

Optional platform check:

```bash
cd ~/open-fdd
./scripts/openfdd_check_ghcr_platform.sh
```

Raspberry Pi details: [Raspberry Pi edge bootstrap](docs/quick-start/raspberry-pi-edge.md).

---

## Fresh edge install

This process does **not** clone the GitHub repository. It pulls GHCR images and creates a local `~/open-fdd` site folder with a persistent `workspace/`.

```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh

bash /tmp/openfdd_edge_bootstrap.sh --start
```

Expected site layout:

```text
~/open-fdd/
  docker-compose.yml
  scripts/
  workspace/
    auth.env.local
    data.env.local
    bacnet/commissioning/commission.env
    data/
```

Validate:

```bash
cd ~/open-fdd

docker compose ps
curl -sS http://127.0.0.1:8765/health
echo
```

---

## Update an existing non-git edge site

Most live edge sites are **not git clones**. Refresh scripts with `curl`, back up the workspace, then pull/recreate the containers from GHCR.

Never use `docker compose down -v` on a live site.

### 1. Refresh edge scripts

```bash
cd ~/open-fdd

mkdir -p scripts

curl -fsSL \
  https://raw.githubusercontent.com/bbartling/open-fdd/master/scripts/openfdd_site_lib.sh \
  -o scripts/openfdd_site_lib.sh

curl -fsSL \
  https://raw.githubusercontent.com/bbartling/open-fdd/master/scripts/openfdd_site_backup.sh \
  -o scripts/openfdd_site_backup.sh

curl -fsSL \
  https://raw.githubusercontent.com/bbartling/open-fdd/master/scripts/openfdd_site_update.sh \
  -o scripts/openfdd_site_update.sh

curl -fsSL \
  https://raw.githubusercontent.com/bbartling/open-fdd/master/scripts/openfdd_check_ghcr_platform.sh \
  -o scripts/openfdd_check_ghcr_platform.sh

chmod +x scripts/openfdd_site_lib.sh \
  scripts/openfdd_site_backup.sh \
  scripts/openfdd_site_update.sh \
  scripts/openfdd_check_ghcr_platform.sh

bash -n scripts/openfdd_site_lib.sh
bash -n scripts/openfdd_site_backup.sh
bash -n scripts/openfdd_site_update.sh
bash -n scripts/openfdd_check_ghcr_platform.sh
```

### 2. Check current health

```bash
cd ~/open-fdd

curl -sS http://127.0.0.1:8765/health
echo

docker compose ps
docker compose config --images
```

### 3. Repair workspace ownership before backup

Some containers or previous maintenance steps may leave root-owned files in `workspace/`. Repair that before backup or update:

```bash
cd ~/open-fdd

sudo chown -R "$(id -u):$(id -g)" workspace
sudo chmod -R u+rwX workspace
```

### 4. Back up workspace

```bash
cd ~/open-fdd

./scripts/openfdd_site_backup.sh 2>&1 | tee "$HOME/openfdd-backup-before-update.log"

tar -tzf ~/openfdd-backups/latest/workspace-full.tgz >/dev/null && echo "backup OK"
```

### 5. Update containers

Use a pinned tag when testing a specific build, or `latest` when tracking the newest published edge images.

```bash
cd ~/open-fdd

NEW_TAG=latest \
PURGE_BACKUP_AFTER_SUCCESS=0 \
OPENFDD_HEALTH_TIMEOUT_SECS=180 \
./scripts/openfdd_site_update.sh 2>&1 | tee "$HOME/openfdd-update.log"
```

For a pinned smoke-test tag:

```bash
NEW_TAG=3.1.6-edge348 \
PURGE_BACKUP_AFTER_SUCCESS=0 \
OPENFDD_HEALTH_TIMEOUT_SECS=180 \
./scripts/openfdd_site_update.sh
```

`PURGE_BACKUP_AFTER_SUCCESS=0` is recommended for live HVAC sites so the backup is retained after a successful update.

---

## Post-update validation

Run this after every live edge update.

```bash
cd ~/open-fdd

echo "=== health ==="
curl -sS http://127.0.0.1:8765/health
echo

echo "=== containers ==="
docker compose ps

echo "=== resolved images ==="
docker compose config --images

echo "=== backup ==="
tar -tzf ~/openfdd-backups/latest/workspace-full.tgz >/dev/null && echo "backup OK"

echo "=== recent bridge ingest ==="
docker compose logs --since 10m bridge | grep 'ingest-samples' | tail -20 || true

echo "=== latest BACnet feather ==="
find workspace/data/feather_store/bacnet -type f -name '*.feather' \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' 2>/dev/null | sort | tail -10 || true

echo "=== BACnet override crash check ==="
docker compose logs --since 10m commission | grep -E 'Exception in thread|unknown-property|BACnet override scan' || true

sleep 180

echo "=== BACnet override check after 3 minutes ==="
docker compose logs --since 3m commission | grep -E 'Exception in thread|unknown-property|BACnet override scan' || true
```

Good signs:

```text
Bridge /health returns ok:true
Containers are Up / healthy
Resolved images match the requested GHCR tag
Backup archive validates
BACnet ingest returns HTTP 200
Feather shards continue updating
No "Exception in thread bacnet-override-scan"
```

A handled warning such as a device-level `unknown-property` can be acceptable if the thread stays alive and polling continues.

---

## AI-agent-safe operations

AI agents can help run Open-FDD, but they must follow a safety contract.

### AI agents may

- refresh edge scripts with `curl`;
- run backup and update scripts;
- validate `/health`, Docker status, GHCR tags, and logs;
- inspect BACnet polling, feather shards, stale points, and driver health;
- help commission BACnet, Niagara, and JSON API data sources;
- draft and bind FDD rules through the Rule Lab flow;
- generate RCx reports and summarize faults;
- use MCP or bridge JWT APIs for read-only building diagnostics.

### AI agents must not

- run `docker compose down -v`;
- run `docker volume prune`;
- run `docker system prune --volumes`;
- delete `workspace/`;
- print passwords, JWTs, or `workspace/auth.env.local` contents;
- expose bridge or MCP to the public internet;
- perform BACnet writes or releases without explicit human approval.

Deeper route maps:

- [AI agent context](docs/ai-agent-context.md)
- [Edge site lifecycle](docs/quick-start/site-lifecycle.md)
- [AGENTS.md](AGENTS.md)
- MCP tools in `workspace/mcp_server/server.py`

---

## Copy-paste AI agent prompts

These are intentionally short. Keep long runbooks in docs and scripts so agents execute deterministic commands instead of improvising.

### Fresh edge bootstrap prompt

```text
You are operating an Open-FDD edge install on a new Linux host.

Goal:
Install Docker if needed, bootstrap Open-FDD from GHCR, start the edge stack, and validate bridge health.

Rules:
- Use the official bootstrap script from:
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
- Do not clone the repo for an edge install.
- Do not delete workspace/.
- Do not print secrets from auth.env.local.
- Do not expose bridge or MCP publicly.
- Do not perform BACnet writes.

Steps:
1. Identify OS, architecture, LAN IPs, Docker version, and Compose version.
2. Install Docker only if missing.
3. Run:
   curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
   bash /tmp/openfdd_edge_bootstrap.sh --start
4. Validate:
   cd ~/open-fdd
   docker compose ps
   curl -sS http://127.0.0.1:8765/health
5. Report host summary, container status, bridge health, auth file location, and next commissioning steps.
```

### Existing edge update prompt

```text
You are operating an existing Open-FDD edge site at ~/open-fdd.

Goal:
Safely update GHCR containers without losing workspace data.

Rules:
- This site may not be a git clone.
- Refresh scripts with curl from master.
- Backup before update.
- Keep backup after update with PURGE_BACKUP_AFTER_SUCCESS=0.
- Never run docker compose down -v.
- Never run docker volume prune.
- Never delete workspace/.
- Do not print secrets.

Steps:
1. Refresh scripts:
   openfdd_site_lib.sh
   openfdd_site_backup.sh
   openfdd_site_update.sh
   openfdd_check_ghcr_platform.sh
2. Syntax-check scripts with bash -n.
3. Check current /health and docker compose ps.
4. Repair workspace ownership:
   sudo chown -R "$(id -u):$(id -g)" workspace
   sudo chmod -R u+rwX workspace
5. Run:
   ./scripts/openfdd_site_backup.sh
6. Validate:
   tar -tzf ~/openfdd-backups/latest/workspace-full.tgz >/dev/null
7. Run:
   NEW_TAG=latest PURGE_BACKUP_AFTER_SUCCESS=0 OPENFDD_HEALTH_TIMEOUT_SECS=180 ./scripts/openfdd_site_update.sh
8. Validate /health, resolved images, BACnet ingest logs, latest feather shards, and commission crash logs.
9. Report backup path, image tag, health result, and any warnings.
```

### Ongoing operator prompt

```text
You are helping operate an Open-FDD edge site.

Start read-only:
- GET /health
- authenticated /health/stack
- building check-in
- driver health
- stale point and fault summaries

You may help:
- review BACnet/Niagara/JSON API data sources;
- validate BRICK model context;
- bind and test Arrow/DataFusion FDD rules;
- generate RCx reports;
- summarize faults and likely next actions.

Never:
- print secrets;
- delete workspace/;
- run destructive Docker volume commands;
- expose services publicly;
- perform BACnet writes without explicit human approval.
```

---

## Python package

Use PyPI when you only need the embeddable Arrow-native FDD runtime — lint, test, and run rules in your own pipelines without Docker.

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

### Optional DataFusion SQL

```bash
pip install "open-fdd[datafusion]"
```

```python
from open_fdd.arrow_runtime import run_datafusion_sql_rule

SQL = """
SELECT
  *,
  "SAT" > 85.0 AS fault
FROM telemetry
"""

result = run_datafusion_sql_rule(SQL, table, {"min_true_rows": 5, "poll_interval_s": 60})

print(result.true_count)  # 1
```

Rule `config` fields such as `min_elapsed_minutes` and `min_true_rows` apply to both backends. See [fault confirmation](docs/rule-cookbook/fault-confirmation.md).

---

## Develop

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"

python -m pytest -q -rs
```

For the package/runtime tests only:

```bash
python -m pytest open_fdd/tests -q -rs
```

Optional test groups may require extra dependencies and explicit commands:

```bash
# DataFusion parity
python -m pip install -e ".[datafusion]"
python -m pytest open_fdd/tests/arrow_runtime -q -rs

# BACnet toolshed tests
python -m pip install bacpypes3
python -m pytest tests/bacnet_toolshed -q

# Portfolio / dashboard tests may require app-stack dependencies.
```

Contributor layout:

- [AGENTS.md](AGENTS.md)
- [developer docs](https://bbartling.github.io/open-fdd/developer/)

---

## Release / image publishing

The edge stack is normally updated through GHCR images. A typical release flow is:

```bash
git checkout master
git pull --ff-only origin master

python -m pytest -q -rs

# bump version in pyproject.toml / package metadata first
git tag -a v3.1.7 -m "Open-FDD 3.1.7"
git push origin v3.1.7
```

For a pre-release edge smoke test, publish a temporary GHCR tag through the multi-arch workflow and update a live edge with `NEW_TAG=<tag>`.

---

## License

MIT — see [LICENSE](LICENSE).
