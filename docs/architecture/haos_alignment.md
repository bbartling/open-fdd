---
title: HA OS alignment
nav_order: 4
parent: Getting Started
---

# Home Assistant OS alignment

Open-FDD edge deploys follow the same **three-layer** model as [Home Assistant Operating System](https://github.com/home-assistant/operating-system):

```text
┌─────────────────────────────────────────────────────────┐
│  OS (future Buildroot)     Docker engine, network, RAUC   │
├─────────────────────────────────────────────────────────┤
│  Supervisor                manifest + compose + health  │
├─────────────────────────────────────────────────────────┤
│  Apps (containers)         bridge, commission, poll, …  │
└─────────────────────────────────────────────────────────┘
         ▲ bind-mount
    workspace/  (feather, rules, model, points.csv)
```

## Layer mapping

| Layer | HA | Open-FDD directory | Today |
|-------|-----|-------------------|--------|
| **OS** | Buildroot image, RAUC | [`os/`](../../os/) | Ubuntu 24.04 + Docker CE |
| **Supervisor** | Manages addons | [`supervisor/`](../../supervisor/) | Ansible + `deploy.sh docker` |
| **Apps** | Container images | [`docker/`](../../docker/) | Multi-target Dockerfile |

Host **Caddy** (:80) is like HA’s ingress: provided by the OS layer, not inside the app containers.

The **bridge** core addon includes the compiled operator SPA (same pattern as HA Core). See [ADR 001 — Core addon serves compiled SPA](adr-001-core-addon-spa.md) for why a separate frontend container is deferred.

## Monorepo workflow

1. **Develop apps** — change `workspace/`, `open_fdd/`, `bacnet_toolshed/`; build images with `./scripts/docker_build.sh`
2. **Supervisor** — addon list in `supervisor/manifest.yaml`; dev stack `docker/compose.dev.yml`
3. **Publish** — GHCR when operator is ready ([publish howto](../howto/publish_docker_addons.md); **deferred**, manual Actions only)
4. **Deploy edge** — `./scripts/docker_build.sh --save` + `infra/ansible/deploy.sh docker`
5. **Future OS** — flash `os/` Buildroot artifact; supervisor pulls pinned images (no Ansible)

## Commands

| Goal | Command |
|------|---------|
| Local supervisor stack | `./scripts/openfdd_stack.sh up` |
| Build all addons | `./scripts/docker_build.sh` |
| Edge bundle (Tailscale) | `./scripts/docker_build.sh --save` |
| Publish images (later) | Actions → **Publish Docker addons**, or [publish howto](../howto/publish_docker_addons.md) |
| Acme deploy | See [Docker edge deploy](../edge_deploy_docker.md) |

## Why this matters

- **Thin OS** — field hosts only run Docker + state; no editable app Python on disk in the target end state
- **Versioned apps** — images are the unit of release (like HA add-ons)
- **One git repo** — OS, supervisor, apps, and Ansible live together until OTA replaces tar-over-SSH

Roadmap: [os/Documentation/roadmap.md](../../os/Documentation/roadmap.md)
