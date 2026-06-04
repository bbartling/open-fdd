---
title: Publish Docker addons (GHCR)
nav_order: 11
---

# Publish Docker addons to GHCR

Production edges (Acme, Pi) **pull** images from **`ghcr.io/bbartling/`** after you publish a tag. Ansible runs `docker compose pull` on the host — no image tar over SSH unless you opt into the legacy path.

**For AI agents:** Publish only when the operator asks to cut an edge release tag. Do not publish on every PR merge.

Branch hygiene and bot PRs: [GitHub branches and release automation](github_branches_and_release.md).

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
2. Pin the same tag in `infra/ansible/host_vars/acme_vm_bbartling.yml` (`openfdd_docker_image_tag`) and/or pass `OPENFDD_IMAGE_TAG` on the command line.
3. Ensure `openfdd_docker_pull_from_ghcr: true` (default via `./deploy.sh docker`).
4. GHCR packages must be **public**, or set `openfdd_ghcr_token` in host_vars for `docker login` on the edge.

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_ollama=false
```

Ansible renders `docker-compose.yml` with `ghcr.io/bbartling/openfdd-*:<tag>`, runs **`docker compose pull`**, then **`up -d`**. Workspace/API files and env still sync from the control machine; only **images** come from GHCR.

**Ops pass** (TTL sync, probes, feather check): same tag — `OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh ops --limit acme_vm_bbartling`.

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
- [ ] Smoke one host with `OPENFDD_IMAGE_TAG=… ./deploy.sh docker` (GHCR pull)
- [ ] Note tag in PR / release notes
