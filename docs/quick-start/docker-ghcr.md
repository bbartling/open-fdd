---
title: Docker & GHCR
parent: Quick Start
nav_order: 1
---

# Docker & GHCR bootstrap

The stack runs from compose recipes in the repo. Clone once, then bring up a
recipe with `scripts/openfdd_stack_up.sh` (it pulls the GHCR images and waits
on health).

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/openfdd_stack_up.sh standalone
```

`workspace/` holds site state. See [Build recipes](../operations/build-recipes.md)
for the full recipe/env matrix.

## Image channels

```yaml
image: ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:-nightly}
```

| Channel | Tag | Use |
|---------|-----|-----|
| Nightly | `nightly` | Default for dev and new installs |
| Beta | `beta` or `3.3.0-beta.N` | After maintainer promotion |
| Stable | `latest` or `3.3.0` | Production (when published) |

`OPENFDD_IMAGE_TAG` applies to every stack image at once. See
[Release channels](../operations/release-channels.html).

**Arch:** `openfdd-central` + `openfdd-web` (+ protocol/fieldbus) publish `linux/amd64` and `linux/arm64`. Hub `openfdd-mqtt` stays **amd64** (Recipe 1). Confirm before a Pi boot:

```bash
docker manifest inspect ghcr.io/bbartling/openfdd-central:nightly
docker manifest inspect ghcr.io/bbartling/openfdd-web:nightly
```

## Recipes

Named product recipes (see [Build recipes](../operations/build-recipes.md)):

| Named recipe | Compose helpers | Services | Arch |
|--------------|-----------------|----------|------|
| **Recipe 1 — cloud hub** | `central`, Railway hub | mqtt + central + web | amd64 |
| **Recipe 2 — OT edge** | `csv` / `react` + protocol, or `standalone` | central + web + protocol (mqtt optional) | amd64 + arm64 |

| Compose helper | Command | Services |
|----------------|---------|----------|
| standalone | `./scripts/openfdd_stack_up.sh standalone` | mqtt + central + ui + fieldbus (OT all-in-one) |
| central | `./scripts/openfdd_stack_up.sh central` | mqtt + central + ui (**Recipe 1** shape) |
| edge | `./scripts/openfdd_stack_up.sh edge` | fieldbus only (optional MQTTS to a hub) |
| csv / react | `./scripts/openfdd_stack_up.sh csv` | central + ui (**Recipe 2** without broker) |

Build locally instead of pulling GHCR:

```bash
./scripts/openfdd_stack_up.sh standalone --build
```

## First login & health

```bash
cd ~/open-fdd
./scripts/openfdd_health_check.sh
curl -s http://127.0.0.1:8080/api/health | jq '{version, image_tag}'
```

Open the UI at `http://<host>:3000`. When `OPENFDD_JWT_SECRET` is set, sign in
with the admin/operator/viewer password from `OPENFDD_ADMIN_PASSWORD`.

Reach the UI over Tailscale, VPN, or a reverse proxy — not raw public internet.

{: .warning }
Never run `docker compose down -v`. Never delete `workspace/`.
