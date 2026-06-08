---
title: Health checks (developer)
parent: Developer Guide
nav_order: 5
---

# Health checks (developer)

Extended validation for engineers with a **full git checkout** — CI, compose overlays, and pre-release gates.

IT operators on edge hosts should use [Quick Start — health check](../quick-start/health-check) instead.

## Clone and local stack

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
cp workspace/auth.env.example workspace/auth.env.local   # loopback dev only
./scripts/docker_build.sh                              # or: ./scripts/openfdd_stack.sh prod
./scripts/openfdd_stack.sh up
```

GHCR production pull (no local build):

```bash
OPENFDD_IMAGE_TAG=2026.06.07-edge ./scripts/openfdd_stack.sh prod
```

## Stack health script

```bash
./scripts/stack_health_check.sh
OPENFDD_BASE_URL=http://192.168.204.18:8765 ./scripts/stack_health_check.sh
./scripts/stack_health_check.sh --require-ollama
```

Probes: containers up, `/health`, `/api/model/health`, sites, tree, SPARQL graph (with integrator auth when configured).

## Compose overlays

| Overlay | Use |
|---------|-----|
| `docker/compose.dev.yml` | Local dev bind-mount |
| `docker/compose.bench.yml` | Host-network BACnet lab |
| `docker/compose.prod.yml` | GHCR images instead of local build |
| `docker/compose.edge.yml` | IT edge template (copy to `~/open-fdd/docker-compose.yml`) |

```bash
docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml ps
docker compose -f docker/compose.dev.yml config --images
```

## BACnet poll pipeline

```bash
tail -1 workspace/bacnet/polls/samples.csv
cat workspace/data/bacnet_ingest_state.json
docker compose logs --since 10m commission | grep -i poll
docker compose logs --since 10m bridge | grep -i ingest
```

## pytest (bridge security / BACnet)

```bash
PYTHONPATH=workspace/api pytest tests/workspace_bridge/test_security.py -q
```

## Pentest production stack (LAN ZAP)

```bash
./scripts/pentest_production_stack.sh start
./scripts/pentest_production_stack.sh verify
```

Then from a **LAN workstation**, run the packaged scan:

- Windows: `scripts/security/Run-OpenFddSecurityScan.ps1`
- macOS/Linux: `scripts/security/run_openfdd_security_scan.sh`

See [scripts/security/README.md](../../scripts/security/README.md), [Security — ZAP baseline](../security/zap-baseline), and the full [security testing cycle](security-testing). Host-side notes: `workspace/deploy/PENTEST.md`.

## Post-deploy insurance (inventory hosts)

For automated checks against named inventory hosts, see `infra/ansible/scripts/post_deploy_check.sh` (maintainer tooling — not required for IT docker-pull sites).
