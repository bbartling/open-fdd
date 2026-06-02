---
title: Publish Docker addons (GHCR) — deferred
nav_exclude: true
---

# Publish Docker addons to GHCR (when ready)

**Status:** Deferred. Edge deploy today uses **`./scripts/docker_build.sh --save`** + Ansible tar load. Registry publish is wired but not required until edges can `docker pull`.

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

## After publish (future edge path)

Not implemented yet on Acme:

1. Pin tag in `supervisor/manifest.yaml` / host_vars (`openfdd_docker_image_tag`).
2. Replace tar load in Ansible with `docker compose pull` + `up`.
3. See [HA OS alignment](../architecture/haos_alignment.md) and `os/Documentation/roadmap.md`.

Until then, keep:

```bash
./scripts/docker_build.sh --save
cd infra/ansible && ./deploy.sh docker --limit <host>
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
