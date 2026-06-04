---
title: GitHub branches and release automation
nav_order: 12
---

# GitHub branches and release automation

How **feature branches**, **bot PRs**, and **manual Docker publishes** fit together after GHCR deploy landed on `master`.

## Branch types

| Branch / PR | Who creates it | What to do |
|-------------|----------------|------------|
| **`master`** | You merge feature PRs here | Production docs site, CI, and edge deploy pins |
| **`deploy/*`, `fix/*`, feature branches** | Developers | Open a PR → merge → **delete the branch** (GitHub “Delete branch” or `git push origin --delete <name>`) |
| **`chore/docs-pdf-refresh`** | **Docs PDF** workflow on GitHub (`docs-pdf.yml`) | Bot opens/updates a PR for `pdf/open-fdd-docs.pdf` and `.txt`. **Merge when the PR is current** so the bundle stays in sync with `docs/`. If **Create PR** failed with `stale info`, re-run the workflow or merge the existing open PR. |
| **Tags on GHCR** | **Publish Docker addons** workflow (manual dispatch) | Not a git branch — image tag e.g. `2026.06.04-edge`. Pin the same tag in `host_vars` / `OPENFDD_IMAGE_TAG`. |

Merged examples (delete if still on disk): `deploy/ghcr-pull-acme` (PR #190), `fault-codes-updates` (PR #188).

## Typical release flow (Acme / production edge)

1. **Code on `master`** — feature PRs merged; CI green.
2. **Publish images** — Actions → **Publish Docker addons** → input tag (e.g. `2026.06.04-edge`). Wait for success.
3. **Deploy edge** — `OPENFDD_IMAGE_TAG=<same-tag> ./deploy.sh docker --limit acme_vm_bbartling` (see [Publish Docker addons](publish_docker_addons.md)).
4. **Docs PDF (optional same day)** — If **Docs PDF** opened PR #189-style branch, merge the bot PR so `pdf/open-fdd-docs.pdf` / `.txt` match `docs/`.
5. **Cleanup** — Delete merged feature branches locally and on `origin`.

## Docs PDF workflow notes

- Triggers on pushes to `master`/`main` that touch `docs/**`, `scripts/build_docs_pdf.py`, or the workflow file.
- Uses `peter-evans/create-pull-request` with branch `chore/docs-pdf-refresh`.
- If **Create PR** fails with `stale info` on `git push --force-with-lease`, another run may have updated the branch first — check for an **open PR** and merge it, or re-run **Docs PDF** from Actions.
- Protected `master` cannot take direct bot pushes; the PR is required.

## Docker publish workflow notes

- **Manual only** (`workflow_dispatch`) — does not run on every merge.
- Requires `workspace/mcp_rag` in git (tracked for `openfdd-mcp-rag` image).
- First publish after adding an image: set GHCR package **visibility** (public or token on edge).

## Starting new work

After release cleanup:

```bash
git checkout master && git pull
git checkout -b fix/your-topic    # or feat/…
```

Use one branch per PR; avoid long-lived `deploy/*` branches after merge.

## Related

- [Publish Docker addons (GHCR)](publish_docker_addons.md)
- [Docker edge deploy](../edge_deploy_docker.md)
- [Contributing](../contributing.md)
