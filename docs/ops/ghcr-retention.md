---
title: GHCR image retention
parent: Operations
nav_order: 6
---

# GHCR image retention

Open-FDD publishes edge images to **GHCR** (`ghcr.io/bbartling/openfdd-*`). During rapid development, old package versions accumulate. This retention system prunes **noise** while protecting rollback tags for **Acme**, our live validation building.

## Policy (conservative)

**Always keep:**

- `latest` and `edge`
- Latest **5** SemVer release tags per image (configurable)
- Tags listed in `scripts/ghcr-retention-protected-tags.txt`
- Current Acme deployed tag (workflow input or `--current-acme-tag`)
- Previous Acme known-good tag (`--previous-acme-tag`)

**Delete candidates (only with `--confirm-delete`):**

- Untagged versions older than **7** days
- SHA-only tags older than **30** days
- Feature/dev-style tags older than **30** days
- SemVer releases beyond the latest N window (unless protected)

Images are defined in `docker/images.yaml`:

- `openfdd-bridge`
- `openfdd-commission`
- `openfdd-mcp-rag`
- `openfdd-cloud-exporter`

## Dry-run first

The script defaults to **dry-run**. It prints a keep/delete table and optional JSON/Markdown reports. Nothing is deleted until you pass **`--confirm-delete`**.

There is **no scheduled automatic deletion** yet — only manual runs locally or via GitHub Actions `workflow_dispatch`.

## Protect Acme rollback tags

Before cleanup, edit `scripts/ghcr-retention-protected-tags.txt`:

```text
latest
edge
v3.0.31
v3.0.30
```

Or pass tags at runtime:

```bash
./scripts/ghcr_prune_packages.sh --all-images --dry-run \
  --current-acme-tag v3.0.31 \
  --previous-acme-tag v3.0.30
```

## Run locally

```bash
gh auth login   # needs read:packages + delete:packages for confirm-delete

./scripts/ghcr_prune_packages.sh --all-images --dry-run
./scripts/ghcr_prune_packages.sh --image openfdd-bridge --dry-run \
  --json-out reports/ghcr-prune-plan.json \
  --markdown-out reports/ghcr-prune-plan.md

# After reviewing the plan:
./scripts/ghcr_prune_packages.sh --all-images --confirm-delete \
  --current-acme-tag v3.0.31 --previous-acme-tag v3.0.30
```

## GitHub Actions workflow

Workflow: **Prune old GHCR images** (`.github/workflows/ghcr-prune.yml`)

1. Actions → **Prune old GHCR images** → **Run workflow**
2. Leave **Dry run only** = `true` for the first run
3. Download the `ghcr-prune-report` artifact
4. Re-run with **Dry run only** = `false` only after reviewing the plan
5. Set **Current Acme deployed tag** and **Previous Acme rollback tag** when known

## Permissions

Deleting package versions requires:

- Local: `gh auth login` with `delete:packages` (and `read:packages`)
- Actions: `permissions.packages: write` on the workflow (already set)

If deletion fails, the script prints:

> Deleting GHCR package versions requires package delete permissions…

## Verify images still pull

After pruning:

```bash
docker pull ghcr.io/bbartling/openfdd-bridge:latest
docker pull ghcr.io/bbartling/openfdd-commission:latest
```

On Acme:

```bash
export OPENFDD_IMAGE_TAG=v3.0.31
./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --quick
```

## Rollback example

```bash
export OPENFDD_IMAGE_TAG=v3.0.30
./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
```

## Related issues

Track open Acme/deploy blockers in [GitHub issue #276](https://github.com/bbartling/open-fdd/issues/276).
