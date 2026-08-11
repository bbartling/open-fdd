---
description: Never demo stale GHCR web; pick images by OCI created; gate Caddy URLs
alwaysApply: true
---

# Demo / GHCR — do not test the wrong image

## What the user will see

- **Unmerged frontend** (this branch, dirty `frontend/web`, closed-not-published PR): GHCR `openfdd-web` is **stale by definition**. Serve a **local** bundle. Never send a Caddy link for `ghcr.io/bbartling/openfdd-web:sha-*` / `:nightly`.
- **Merged + published**: pull **newest-by-OCI-`created`**, not tag name. `:nightly` and `sha-*` sort order are not newest.

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
```

Then pin `OPENFDD_IMAGE_TAG=sha-<that>` and recreate. Do not `docker pull …:nightly` and call it tip.

## Gate before any login URL

```bash
./scripts/openfdd_demo_gate.sh --local-web --marker overview-vibe19-oracle
# or, only if the user asked for published GHCR:
./scripts/openfdd_demo_gate.sh --ghcr-web
```

If the gate fails: fix serve. Do **not** paste `http://192.168.204.55/auth` and blame the user.

Say explicitly: **local Overview bundle, not GHCR** — or **GHCR sha-… newest-by-created**.

## Rust vs web

Leave `central` / `mqtt` / `fieldbus` on GHCR `sha-*` (newest-by-created). Local cargo is not the demo path. Unmerged UI = Node build + bind-mount / local web image only.
