---
title: Publish Docker addons (GHCR) — deferred
nav_exclude: true
---

# Publish Docker addons to GHCR (when ready)

**Status:** Edge deploy defaults to **`docker compose pull`** from **`ghcr.io/bbartling/`** after you publish a tag. Tar load remains for lab/air-gap (`OPENFDD_DOCKER_PULL_FROM_GHCR=0`).

**For AI agents:** Run this only when the operator explicitly asks to publish images or cut an edge release tag. Do not publish on every PR merge.

## Prerequisites

- Images defined in `docker/images.yaml` and `supervisor/manifest.yaml`
- `OPENFDD_IMAGE_TAG` must **not** be `local` (release version only)
- GHCR packages under `ghcr.io/bbartling/` (org in `docker/images.yaml`)

## Option A — GitHub Actions (preferred)

1. Merge workflow `.github/workflows/docker-publish.yml` to default branch (or run from branch that contains it).
2. GitHub → **Actions** → **Publish Docker addons** → **Run workflow**.
3. Input **image_tag**, e.g. `2026.06.01-edge`.
4. Workflow builds four addons, runs `scripts/validate_supervisor_manifest.sh`, pushes (set `PUBLISH_LATEST=1` in the workflow env only when you also want `:latest` tags):
   - `ghcr.io/bbartling/openfdd-bridge:<tag>`
   - `ghcr.io/bbartling/openfdd-commission:<tag>`
   - `ghcr.io/bbartling/openfdd-bacnet-poll:<tag>`
   - `ghcr.io/bbartling/openfdd-mcp-rag:<tag>`
5. After first publish: set GHCR package visibility (public or grant edge host read) if pulls are needed.

Uses `GITHUB_TOKEN` with `packages: write` — no extra secret for same-repo publish.

## Option B — Local (control machine)

```bash
cd ~/open-fdd
OPENFDD_IMAGE_TAG=2026.06.01-edge ./scripts/docker_build.sh
docker login ghcr.io
OPENFDD_IMAGE_TAG=2026.06.01-edge ./scripts/docker_publish.sh
```

## After publish — deploy Acme (GHCR pull)

1. GitHub Actions **Publish Docker addons** finishes with your tag (e.g. `2026.06.04-edge`).
2. Set the same tag in `host_vars/acme_vm_bbartling.yml` (`openfdd_docker_image_tag`) or pass `-e` / `OPENFDD_IMAGE_TAG`.
3. GHCR packages must be **public**, or set `openfdd_ghcr_token` in host_vars for `docker login` on the edge.

```bash
cd infra/ansible
export SSHPASS='…'   # or secrets/acme.env.local
OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh docker --limit acme_vm_bbartling
```

Ansible renders `docker-compose.yml` with `ghcr.io/bbartling/openfdd-*:<tag>`, runs **`docker compose pull`**, then **`up -d`**.

Legacy tar (no registry):

```bash
OPENFDD_DOCKER_PULL_FROM_GHCR=0 OPENFDD_IMAGE_TAG=2026.06.04-edge ./scripts/docker_build.sh --save
OPENFDD_DOCKER_PULL_FROM_GHCR=0 ./deploy.sh docker --limit <host>
```

## Related files

| File | Role |
|------|------|
| `scripts/docker_build.sh` | Build all Dockerfile targets |
| `scripts/docker_publish.sh` | Tag + push to GHCR |
| `scripts/validate_supervisor_manifest.sh` | CI + pre-publish check |
| `.github/workflows/docker-publish.yml` | Manual `workflow_dispatch` only |
| `.github/workflows/docker-supervisor-check.yml` | PR validation (no publish) |

## Operator checklist (release day)

- [ ] `./scripts/build_and_test.sh` green
- [ ] Choose `OPENFDD_IMAGE_TAG` (semver or date-edge)
- [ ] Run Actions workflow or local publish
- [ ] Smoke one host with tar path OR registry pull (when wired)
- [ ] Note tag in PR / release notes
