# Docker edge deploy (Open-FDD)

Run the bridge, BACnet commission, MCP RAG, and (optionally) BACnet poll as **containers**.  
**Caddy** stays on the host (systemd) for LAN :80 → `127.0.0.1:8765` — same as the legacy playbook.

Legacy **systemd + pip + rsync** deploy remains available via `./deploy.sh all`.

## Images

| Image | Role |
|-------|------|
| `openfdd-bridge` | FastAPI + compiled React SPA |
| `openfdd-commission` | BACnet commission HTTP agent |
| `openfdd-bacnet-poll` | RPM poll driver (`network_mode: host`) |
| `openfdd-mcp-rag` | Doc search sidecar (:8090) |
| `ollama/ollama` | Optional — official image, not built in-tree |

State (feather, rules, model, `points.csv`) lives on the host under **`workspace/`**, bind-mounted into containers.

## Local dev (bensserver)

```bash
cd ~/open-fdd
./scripts/docker_build.sh
docker compose -f docker/compose.dev.yml up -d
curl -s http://127.0.0.1:8765/health | jq .

# BACnet poll (host network — needs real OT NIC or lab bind)
docker compose -f docker/compose.dev.yml --profile bacnet up -d

# Ollama in compose (or use host Ollama — bridge uses host.docker.internal:11434)
docker compose -f docker/compose.dev.yml --profile ai up -d
```

Stop: `docker compose -f docker/compose.dev.yml down`

## Acme / edge deploy

### One-time: Caddy on host

If the VM has never had Caddy from Ansible:

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
./deploy.sh caddy --limit acme_vm_bbartling
```

### Build images + bundle on bensserver

```bash
cd ~/open-fdd
./scripts/build_and_test.sh          # or build_operator_dashboard.sh prod
./scripts/docker_build.sh --save     # writes docker/dist/openfdd-images-local.tar.gz
```

### Push to Acme via Ansible

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
./deploy.sh docker --limit acme_vm_bbartling
```

Optional tag:

```bash
OPENFDD_IMAGE_TAG=2026.06.01 ./scripts/docker_build.sh --save
./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_image_tag=2026.06.01
```

### BACnet poll on Acme

Set in `host_vars/acme_vm_bbartling.yml`:

```yaml
enable_bacnet_poll_driver: true
```

Re-run `./deploy.sh docker …` — poll container uses **`network_mode: host`** and reads `workspace/bacnet/commissioning/commission.env` (OT bind e.g. `10.200.200.185/24:47808`).

## Variables (`group_vars` / `-e`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `openfdd_docker_image_tag` | `local` | Image tag in compose |
| `openfdd_docker_disable_systemd` | `true` | Stop legacy bridge/mcp/poll units |
| `openfdd_docker_ollama` | `true` | Include `ollama/ollama` service when `enable_ollama` |

## What stays systemd

- **Caddy** — TLS/HTTP front door (recommended)
- **openfdd-fdd-loop.timer** — scheduled FDD batch (for now)
- **openfdd-feather-retention.timer** — historian trim
- **Host Ollama** — if you prefer `ollama_bootstrap.yml` over compose Ollama

## Files

```
docker/Dockerfile              multi-target build
docker/compose.dev.yml         local bind-mount stack
scripts/docker_build.sh        build + optional tar export
infra/ansible/deploy_docker.yml
infra/ansible/templates/docker-compose.edge.yml.j2
```

## Next steps (registry)

Replace `docker save` / `copy` / `load` with a private registry pull when you have many sites:

```bash
docker tag openfdd-bridge:local registry.example/openfdd-bridge:1.2.3
docker push registry.example/openfdd-bridge:1.2.3
```

Ansible then runs `docker compose pull` instead of loading a tar.
