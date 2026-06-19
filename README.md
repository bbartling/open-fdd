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
  Open-source HVAC systems supervisory fault detection for buildings — local-first, on-prem, vendor-neutral, and free to run at the edge.

  Arrow-native rules, optional DataFusion SQL rules for Rust-ready migration, optional PyPI embeddable runtime, and a full Docker/GHCR edge operator stack: BACnet, bridge API, dashboard, and MCP.

  Includes an open, free knowledge layer for AI-assisted building diagnostics, commissioning support, and HVAC fault investigation.
</p>

<p align="center">
  <a href="https://bbartling.github.io/open-fdd/"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
  <a href="https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf"><img src="https://img.shields.io/badge/Docs-PDF_download-DC2626?style=for-the-badge" alt="PDF documentation"></a>
</p>

---

## Install / run

### Full Open-FDD edge stack (Docker / GitHub Container Registry)


| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-bridge`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) | API, dashboard, historian |
| [`ghcr.io/bbartling/openfdd-commission`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-commission) | BACnet discover, read, poll |
| [`ghcr.io/bbartling/openfdd-mcp-rag`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp-rag) | MCP + doc-search |


### Manual Installation

This process does not clone the GitHub repository. It only pulls the `latest` images from GHCR and uses a Bash script to set up the basic file structure on the Linux filesystem.


```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh --start
```

### Update an Existing Site

This backs up site data, runs safe Docker maintenance, updates the containers, validates health, and removes the backup archive on success. See [Edge site lifecycle](docs/quick-start/site-lifecycle.md).


```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
./scripts/openfdd_site_update.sh
```

### AI Agent Prompt


| Area | Examples |
|------|----------|
| **Edge deploy** | `openfdd_edge_bootstrap.sh`, `openfdd_site_backup.sh`, `openfdd_site_update.sh`, health checks |
| **Drivers** | BACnet discover/poll/bind, Niagara station setup, JSON API endpoints |
| **Model & rules** | BRICK sites/equipment/points, Rule Lab save/bind, batch FDD, tuning brief/apply |
| **Operations** | Building check-in, zone temps, device poll health, BACnet P8 override scans |
| **Reports** | `rcx_plan_report`, `rcx_generate_report`, list/download saved DOCX |
| **Safety** | No BACnet writes without approval; never `docker compose down -v`; never delete `workspace/` |

Deeper route maps: [AI agent context](docs/ai-agent-context.md) · [Edge site lifecycle](docs/quick-start/site-lifecycle.md) · [AGENTS.md](AGENTS.md) · MCP tools in `workspace/mcp_server/server.py`.

<details>
<summary><strong>Copy-paste: OpenClaw — fresh Raspberry Pi edge bootstrap</strong></summary>

Prompt tuned for **OpenClaw** on a new Pi. Edge deploy uses **GHCR Docker** (not a source clone): `openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag`. Bootstrap script: [`scripts/openfdd_edge_bootstrap.sh`](scripts/openfdd_edge_bootstrap.sh).

```text
You are OpenClaw running on a fresh Raspberry Pi intended to become an Open-FDD edge device.

Goal:
Install and bootstrap Open-FDD from https://github.com/bbartling/open-fdd on this fresh Raspberry Pi, start the Docker edge stack, then validate that:
1. Docker is installed and working.
2. Open-FDD edge stack is running.
3. Bridge health is good.
4. Auth is configured.
5. MCP sidecar / mcp-rag is online.
6. The install is safe for a local OT/LAN edge box and is not exposed publicly.

Important project facts:
- Open-FDD edge deploy should use the GHCR Docker stack, not a source-code dev install.
- The edge stack uses these images:
  - ghcr.io/bbartling/openfdd-bridge:latest
  - ghcr.io/bbartling/openfdd-commission:latest
  - ghcr.io/bbartling/openfdd-mcp-rag:latest
- The official bootstrap script is:
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
- Default site root should be:
  ~/open-fdd
- The persistent workspace must not be deleted after creation:
  ~/open-fdd/workspace
- Never run `docker compose down -v`.
- Never delete `workspace/`.
- Do not print secrets into long logs, reports, Git commits, or chat output. You may say where the auth file is located.

Work plan:

Step 0 — Identify host
Run:
set -euo pipefail
whoami
hostname
uname -a
uname -m
cat /etc/os-release || true
ip -4 addr show scope global || true

If `uname -m` is not `aarch64` or `arm64`, warn that the Pi may be 32-bit and GHCR Docker images may not support it. Continue only if Docker image pull succeeds.

Step 1 — Install base packages
Run:
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release jq git nano

Step 2 — Install Docker if missing
Check:
docker --version || true
docker compose version || true

If Docker or Docker Compose v2 is missing, install Docker using the official Docker apt repo for Debian/Raspberry Pi OS. Use the OS codename from `/etc/os-release`.

Use commands similar to:
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

Then enable Docker:
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true

If the current shell cannot access Docker without sudo yet, either use `newgrp docker` or use `sudo docker` only long enough to validate. Prefer to make the final setup work with normal `docker` commands for this user.

Validate:
docker --version
docker compose version
docker run --rm hello-world

Step 3 — Bootstrap Open-FDD edge
Download and run the official bootstrap:
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh

chmod +x /tmp/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh --start

This should create:
~/open-fdd/docker-compose.yml
~/open-fdd/workspace/auth.env.local
~/open-fdd/workspace/data.env.local
~/open-fdd/workspace/bacnet/commissioning/commission.env
~/open-fdd/scripts/openfdd_site_backup.sh
~/open-fdd/scripts/openfdd_site_update.sh

Step 4 — Validate stack
Run:
cd ~/open-fdd
docker compose ps
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

Expected services:
- bridge
- commission
- mcp-rag

All should be `Up` or restarting briefly during first boot.

Step 5 — Validate bridge public health
Run:
curl -sf http://127.0.0.1:8765/health | jq .

Expected:
- HTTP 200
- JSON has `ok: true`
- ideally `auth_required: true`

If health fails, inspect:
cd ~/open-fdd
docker compose logs --since 10m bridge
docker compose logs --since 10m commission
docker compose logs --since 10m mcp-rag

Step 6 — Validate auth file exists without leaking secrets
Run:
test -f ~/open-fdd/workspace/auth.env.local
chmod 600 ~/open-fdd/workspace/auth.env.local || true
grep -E '^OFDD_(OPERATOR_USER|INTEGRATOR_USER|AGENT_USER)=' ~/open-fdd/workspace/auth.env.local

Do not print passwords in your final report. State that dashboard login uses the `integrator` user and the password from:
~/open-fdd/workspace/auth.env.local

Step 7 — Login smoke test
Extract integrator credentials locally and test login:
cd ~/open-fdd
set -a
. ./workspace/auth.env.local
set +a

TOKEN="$(curl -sf -X POST http://127.0.0.1:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${OFDD_INTEGRATOR_USER}\",\"password\":\"${OFDD_INTEGRATOR_PASSWORD}\"}" \
  | jq -r .token)"

test -n "$TOKEN"
test "$TOKEN" != "null"
echo "Login token acquired OK"

Then test authenticated stack health:
curl -sf http://127.0.0.1:8765/health/stack \
  -H "Authorization: Bearer $TOKEN" | jq .

Expected:
- API responds successfully.
- Stack health lists services.
- BACnet may be yellow if no points are commissioned yet; that is acceptable on a fresh Pi.
- Bridge should be green/healthy.

Step 8 — Validate MCP sidecar is online
The Docker edge compose may not publish port 8090 directly to the host. First inspect:
cd ~/open-fdd
docker compose ps mcp-rag
docker compose logs --since 10m mcp-rag

Try health from inside the MCP container:
docker compose exec -T mcp-rag sh -lc '
  command -v curl >/dev/null 2>&1 && curl -sf http://127.0.0.1:8090/health ||
  command -v wget >/dev/null 2>&1 && wget -qO- http://127.0.0.1:8090/health ||
  python - <<PY
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=5).read().decode())
PY
'

Also test from the bridge container to the compose service name:
docker compose exec -T bridge sh -lc '
  command -v curl >/dev/null 2>&1 && curl -sf http://mcp-rag:8090/health ||
  command -v wget >/dev/null 2>&1 && wget -qO- http://mcp-rag:8090/health ||
  python - <<PY
import urllib.request
print(urllib.request.urlopen("http://mcp-rag:8090/health", timeout=5).read().decode())
PY
'

If `/health` is not available but the container is running, inspect logs for FastMCP startup and check the MCP endpoint:
docker compose logs --since 10m mcp-rag | tail -200

If MCP needs host-local access for OpenClaw, do not expose it publicly. Add a localhost-only port mapping to `~/open-fdd/docker-compose.yml` under the `mcp-rag` service:

ports:
  - "127.0.0.1:8090:8090"

Then recreate only mcp-rag:
cd ~/open-fdd
docker compose up -d --force-recreate mcp-rag
curl -sf http://127.0.0.1:8090/health || true

Do not bind MCP to `0.0.0.0` unless explicitly instructed.

Step 9 — Validate BACnet bind config, but do not start writing to controllers
Show safe config summary:
grep '^BACNET_BIND=' ~/open-fdd/workspace/bacnet/commissioning/commission.env || true
ip -4 addr show scope global || true

If BACNET_BIND looks wrong, report it and suggest the correct LAN IP/prefix. Do not run BACnet writes. On a fresh Pi with no commissioned devices, it is OK if polling has no samples yet.

Step 10 — Optional reboot survival check
Only do this if allowed by the operator. Otherwise skip.
sudo reboot

After reconnect:
cd ~/open-fdd
docker compose ps
curl -sf http://127.0.0.1:8765/health | jq .

Final report format:
Return a concise report with:

1. Host summary:
   - hostname
   - architecture
   - OS
   - LAN IPs

2. Docker status:
   - Docker version
   - Compose version
   - hello-world pass/fail

3. Open-FDD files created:
   - ~/open-fdd/docker-compose.yml
   - ~/open-fdd/workspace/auth.env.local
   - ~/open-fdd/workspace/bacnet/commissioning/commission.env

4. Container status:
   - bridge
   - commission
   - mcp-rag

5. Health results:
   - GET /health
   - authenticated /health/stack
   - MCP /health or log-based MCP startup proof

6. Login:
   - say whether integrator login succeeded
   - do not print passwords or token

7. Next manual steps:
   - open dashboard locally or through a safe localhost/Caddy/Tailscale route
   - use integrator credentials from ~/open-fdd/workspace/auth.env.local
   - commission BACnet / Niagara / JSON API drivers via dashboard or API
   - validate BACNET_BIND before OT polling
   - never delete workspace/
   - update later with:
     cd ~/open-fdd && ./scripts/openfdd_site_backup.sh && ./scripts/openfdd_site_update.sh

Stop immediately and report clearly if:
- Docker cannot install.
- GHCR images do not support this Pi architecture.
- docker compose pull fails.
- Bridge /health never becomes healthy.
- MCP container exits repeatedly.
```

</details>

<details>
<summary><strong>Copy-paste: OpenClaw — ongoing edge operator (drivers + FDD)</strong></summary>

Use after bootstrap when the stack is healthy. Agent connects via MCP (`8090`) or bridge JWT (`8765`).

```text
You are OpenClaw maintaining an Open-FDD edge site at ~/open-fdd.

Goal:
Help the human operator keep drivers, model, and FDD healthy — without BACnet writes unless explicitly approved.

You can:
- Check health: GET /health, GET /health/stack (JWT), MCP health_check
- Commission drivers: BACnet discover/poll config, Niagara stations, JSON API endpoints
- Maintain BRICK model: sites, equipment, points (preserve point IDs on import)
- Rule Lab: search cookbook, draft/save/bind PyArrow rules, run POST /api/rules/batch
- Operations: building.checkin, zone temps, device poll health, override scan status
- Reports: rcx_plan_report → rcx_generate_report (DOCX saved to workspace/reports/rcx)
- Updates: ./scripts/openfdd_site_backup.sh then ./scripts/openfdd_site_update.sh

Never:
- docker compose down -v
- delete workspace/
- print passwords, tokens, or auth.env.local contents in chat
- expose MCP or bridge to 0.0.0.0 on the public internet

Start each session with integrator JWT login, then building_agent_checkin or get_building_status.
Report faults, stale points, and recommended next steps in plain language.
```

</details>

<details>
<summary><strong>Copy-paste: OpenClaw — backup, update & restore</strong></summary>

Use for scheduled upgrades or disaster recovery on an existing `~/open-fdd` site. Full reference: [Edge site lifecycle](docs/quick-start/site-lifecycle.md).

```text
You are OpenClaw upgrading an Open-FDD edge site at ~/open-fdd.

Goal:
Run a safe image upgrade with backup, Docker maintenance, validation, and backup purge — or restore workspace from backup if requested.

Standard upgrade (workspace bind-mount preserved):
  cd ~/open-fdd
  ./scripts/openfdd_site_backup.sh
  ./scripts/openfdd_site_update.sh

What openfdd_site_update.sh does:
1. Verify ~/openfdd-backups/latest/workspace-full.tgz integrity
2. Safe Docker maintenance (container/network/dangling image prune + unused image prune)
   - NEVER: docker volume prune, docker compose down -v
3. docker compose pull && up -d --force-recreate
4. Validate workspace/ layout + GET http://127.0.0.1:8765/health
5. On success: delete ~/openfdd-backups/latest (PURGE_BACKUP_AFTER_SUCCESS=1 default)

Restore workspace from backup (corruption / rollback):
  RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh

Historian cap on restore (default keeps newest ~200 GiB of feather shards):
  RESTORE_WORKSPACE=1 RESTORE_FEATHER_MAX_GIB=200 ./scripts/openfdd_site_update.sh

Restore ALL historian data (no cap):
  RESTORE_WORKSPACE=1 RESTORE_FEATHER_MAX_GIB=0 ./scripts/openfdd_site_update.sh

Useful env vars:
  NEW_TAG=latest                    GHCR tag (or OPENFDD_IMAGE_TAG)
  BACKUP_INCLUDE_POLL_SAMPLES=0     fast backup (skip poll CSV history)
  SKIP_DOCKER_MAINTENANCE=1         skip prune
  PURGE_BACKUP_AFTER_SUCCESS=0      keep backup after successful upgrade
  REQUIRE_BACKUP=0                  upgrade without prior backup (not recommended)

If validation fails:
- Backup is KEPT at ~/openfdd-backups/latest
- Inspect: docker compose logs --since 10m bridge
- Retry restore: RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh

Never:
- docker compose down -v
- delete workspace/
- print auth.env.local passwords in chat

Report: backup size, image tag, health pass/fail, whether backup was purged, feather cap if restore was used.
```

</details>


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

**DataFusion SQL** (same telemetry table, optional `pip install 'open-fdd[datafusion]'`):

```python
from open_fdd.arrow_runtime import run_datafusion_sql_rule

SQL = """
SELECT
  *,
  "SAT" > 85.0 AS fault
FROM telemetry
"""

result = run_datafusion_sql_rule(SQL, table, {"min_true_rows": 5, "poll_interval_s": 60})

print(result.true_count)  # 1 — same confirmed count as PyArrow when cfg matches
```

Rule `config` fields such as `min_elapsed_minutes` and `min_true_rows` apply to **both** backends (fault confirmation / minimum duration). See [fault confirmation](docs/rule-cookbook/fault-confirmation.md).


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
