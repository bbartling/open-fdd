# Ansible edge deploy (Open-FDD)

Inventory → component deploy → optional post-check. Same pattern as `vibe_code_apps_12/ansible`.

## Quick start

```bash
cd infra/ansible
cp inventory.example.yml inventory.yml
cp host_vars/bacnet_pi.yml.example host_vars/bacnet_pi.yml
cp host_vars/acme_vm_bbartling.yml.example host_vars/acme_vm_bbartling.yml
cp secrets/acme.env.example secrets/acme.env.local   # SSH + site facts (chmod 600)

# deploy.sh loads secrets/acme.env.local when --limit acme_vm_bbartling
./deploy.sh help
./deploy.sh all --limit bacnet_pi -v
./deploy.sh all --limit acme_vm_bbartling -v
```

**Secrets layout:** [secrets/README.md](secrets/README.md) · public overview: [docs/edge_deploy.md](../../docs/edge_deploy.md)

## Deploy paths

| Path | Use when |
|------|----------|
| **`docker`** (recommended) | Acme VM, x86 edges — images + compose; no app systemd units |
| **`all`** / components | Pi/lab without Docker — rsync + venv + systemd app units |

Use **`./deploy.sh <component> --limit <host>`** or **`make <component> HOST=<host>`** from this directory.

| Component | What it updates |
|-----------|-----------------|
| **`docker`** | **Primary.** Image bundle + compose + workspace state — [edge_deploy_docker.md](../../docs/edge_deploy_docker.md) |
| **`all`** | Legacy full stack (rsync + systemd app units) |
| **`ui`** / **`web`** | Built React dashboard → `workspace/api/static/app/` (baked into Docker image for `docker` path) |
| **`backend`** | Bridge API rsync + **legacy** `openfdd-bridge` systemd |
| **`core`** | `open_fdd/` Python package + editable install |
| **`drivers`** | `bacnet_toolshed/`, **legacy** poll/commission units, `points.csv` |
| **`data`** | `workspace/data/` (models, rules paths — not live historian DB) |
| **`config`** | `auth.env.local`, bridge secrets, Caddyfile |
| **`caddy`** | Caddy package + TLS + reverse proxy (host; used with Docker too) |
| **`systemd`** | **Legacy only** — reload app unit files (ignored when `openfdd_docker_stack: true`) |
| **`pip`** | venv + pip installs (legacy path) |
| **`commission`** | Push `points.csv` from `edge_backup/local/<site>/<building>/` |
| **`mcp`** | MCP RAG sidecar (`edge_ai_stack.yml`; legacy systemd or Docker) |
| **`ai`** | Ollama bootstrap + MCP |
| **`os`** | `apt update` + safe upgrade |
| **`check`** | Post-deploy probes (compose or systemd, per host vars) |

**Examples**

```bash
# Docker path (Caddy on host; images built on bensserver)
../../scripts/docker_build.sh --save
./deploy.sh docker --limit acme_vm_bbartling

# After dashboard changes (build first)
../../scripts/build_operator_dashboard.sh prod
./deploy.sh ui --limit acme_vm_bbartling

# Bridge API only
./deploy.sh backend --limit acme_vm_bbartling

# BACnet poll driver + points.csv
./deploy.sh drivers --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true

# OS packages (optional reboot)
./deploy.sh os --limit acme_vm_bbartling -e os_upgrade_reboot=true

# Makefile shortcuts
make ui HOST=acme_vm_bbartling
make ui-deploy HOST=acme_vm_bbartling   # build + ui
make docker-build HOST=acme_vm_bbartling
make docker-deploy HOST=acme_vm_bbartling   # build bundle + deploy
make os HOST=acme_vm_bbartling
```

**Build before `ui` or `all`:** `workspace/api/static/app/index.html` must exist (`../../scripts/build_and_test.sh` or `build_operator_dashboard.sh prod`).

**Env:** `SSHPASS` (or `secrets/acme.env.local` auto-loaded); `RUN_POST_CHECK=0` to skip insurance script; `ANSIBLE_INVENTORY` to override inventory path.

## Services on edge

### Docker path (`openfdd_docker_stack: true`)

| Runtime | Role |
|---------|------|
| **compose: bridge** | FastAPI Rule Lab + FDD + ingest (:8765) |
| **compose: commission** | BACnet discover/write HTTP (:8767) + poll loop |
| **compose: bacnet-poll** | Optional dedicated poll container (`network_mode: host`) |
| **compose: mcp-rag** | Doc search (:8090) |
| **host: caddy** | LAN **:80** → loopback bridge |
| **host: openfdd-fdd-loop.timer** | Scheduled FDD batch (`docker compose exec bridge …`) |
| **host: openfdd-feather-retention.timer** | Feather prune |

Logs: `docker compose -f ~/open-fdd/docker-compose.yml logs -f bridge commission`

### Legacy systemd path (e.g. `bacnet_pi`)

| Unit | Role |
|------|------|
| `openfdd-bridge` | FastAPI (:8765) |
| `openfdd-bacnet-commission` | Commission agent (:8767) |
| `openfdd-bacnet-poll` | RPM → `samples.csv` |
| `openfdd-fdd-loop.timer` | Scheduled FDD batch (host `.venv`) |
| `openfdd-feather-retention.timer` | Feather prune |
| `caddy` | LAN entry **:80** → bridge |

Poll driver is **off** until `points.csv` is commissioned:

```bash
./deploy.sh drivers --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
./stop_bacnet_polling.sh --limit acme_vm_bbartling
```

## Acme real building (`acme_vm_bbartling`)

x86 Ubuntu VM on OT BACnet (bind address in private `host_vars` / `secrets/acme.env.local`). SSH via Tailscale/LAN — set `ansible_host` in `inventory.yml` and `ACME_SSH_HOST` in `secrets/acme.env.local` (never commit).

```bash
./scripts/acme_commission_gl36.sh          # GL36 + economizer poll set @ 60s
./acme_go_live.sh --limit acme_vm_bbartling
PYTHONPATH=../../workspace/api python3 ../../scripts/gl36_site_model.py --site-id acme --building-id vm-bbartling
python3 ../../scripts/gl36_mechanical_validate.py --site-id acme --building-id vm-bbartling --samples /path/to/samples.csv
```

| Fact | Value |
|------|--------|
| Site / building | `acme` / `vm-bbartling` |
| Poll profile | ~336 GL36 points (VAV + AHU + plant) |
| Historian | `feather_max_gib: 125`, `feather_retention_days: 365` |
| Ollama | `qwen3:4b` on 16 GB tier |

GL36 reference: [Trim & Respond README](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md)

## Boss Pi test bench (`192.168.204.12`)

Same host as `vibe_code_apps_12/ansible/inventory.yml` → `bacnet_pi`.

| Fact | Value |
|------|--------|
| Hostname | `bosspi` |
| SSH | `ben@192.168.204.12` |
| CPU | **armv7l** (Pi 3 B+ 32-bit) |
| RAM | ~**1 GB** (not 8 GB — use `ollama_ram_tier: 8gb` only as config label) |

```bash
./deploy.sh all --limit bacnet_pi --no-ask-pass -v
```

Check-engine: `http://192.168.204.12/` (Caddy → bridge).

**Ollama / tinyllama:** Official Ollama builds are **arm64 or amd64 only**. Pi 3 B+ with 32-bit Raspbian cannot run Ollama; `ollama_bootstrap.yml` fails fast with a clear message. Use bensserver or a Pi 4/5 with 64-bit OS for AI chat testing.

```bash
# Only on arm64/aarch64 or x86 hosts:
ansible-playbook -i inventory.yml ollama_bootstrap.yml --limit bacnet_pi \
  -e enable_ollama=true -e ollama_ram_tier=8gb \
  -e '{"ollama_model_for_tier":{"8gb":"tinyllama"}}'
```

Services use `Restart=always` and `WantedBy=multi-user.target` so they come back after reboot/power cycle.

**Deploy roadblock on this Pi:** Open-FDD needs **pyarrow** (feather store). There is no prebuilt wheel for **Python 3.13 + armv7l**, and source builds fail on ~1 GB RAM. Use **Pi 4/5 64-bit OS** or deploy to **`acme_vm_bbartling`** for ansible dev testing. Partial sync to bosspi succeeded (code + `points.csv` + venv); systemd units were not installed.

| vibe12 | open-fdd |
|--------|----------|
| MQTT → AWS IoT | Local CSV → `POST /ingest/bacnet` → feather |
| `vibe12-bacnet-read` | `openfdd-bacnet-poll` |
| Cloud Lambda dashboard | Edge bridge + optional Caddy |
| `commissioning_web` on bensserver | Bridge `/bacnet` + commission agent |

## Auth

Set in private `host_vars`:

```yaml
ofdd_auth_secret: "long-random"
ofdd_web_user: operator
ofdd_web_password: "..."
```

Or set `caddy_mode: tls` in group_vars for self-signed HTTPS on OT LAN.

Check-engine dashboard (`/` and `/faults`) is **public read-only** — no login required.
Optional bridge auth (`ofdd_auth_secret`) gates Rule Lab, BACnet writes, etc.

## Local dev (bensserver)

```bash
./scripts/build_and_test.sh      # vitest + prod UI + pytest (deploy gate)
./scripts/run_local.sh restart   # prod React build + stack + Caddy (if enabled)
# http://127.0.0.1/  — check-engine dashboard (Caddy default, no port)
# http://127.0.0.1:8765/ — direct bridge if OFDD_CADDY_MODE=off
```

UI flags: `--ui-test` (vitest + build), `--ui-skip` (no npm), `--dev` (optional Vite :5173).
