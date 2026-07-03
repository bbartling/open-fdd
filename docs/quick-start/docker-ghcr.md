---
title: Docker & GHCR
parent: Quick Start
nav_order: 1
---

# Docker & GHCR bootstrap

## One-liner (no git clone on device)

```bash
curl -fsSL -o /tmp/openfdd_rust_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_rust_edge_bootstrap.sh
OPENFDD_IMAGE_TAG=nightly bash /tmp/openfdd_rust_edge_bootstrap.sh --start
```

This creates `~/open-fdd/` with compose, scripts, and `workspace/` for site state.

## Image channels

```yaml
image: ghcr.io/bbartling/openfdd-edge-rust:${OPENFDD_IMAGE_TAG:-nightly}
```

| Channel | Tag | Use |
|---------|-----|-----|
| Nightly | `nightly` | Default for dev and new installs |
| Beta | `beta` or `3.3.0-beta.N` | After maintainer promotion |
| Stable | `latest` or `3.3.0` | Production (when published) |

See [Release channels](../operations/release-channels.html).

Multi-arch: `linux/amd64` and `linux/arm64`. Optional platform check:

```bash
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_rust_check_ghcr_platform.sh
```

## Compose profiles

From `docker/compose.edge.rust.yml`:

| Profile | Use |
|---------|-----|
| `desktop-json-csv` | Bridge only — CSV/JSON workflows on a workstation |
| `full-edge` | Bridge + BACnet commission + Haystack gateway |
| `caddy-http` / `caddy-tls` | Reverse proxy in front of the bridge |
| `mcp-sidecar` | Optional `openfdd-mcp` stdio sidecar for external agents |

Examples:

```bash
# Full OT edge
export OPENFDD_COMPOSE_ROOT=~/open-fdd
export OPENFDD_IMAGE_TAG=nightly
docker compose -f docker/compose.edge.rust.yml --profile full-edge up -d

# Desktop CSV / JSON mode
docker compose -f docker/compose.edge.rust.yml --profile desktop-json-csv up -d
```

## Bootstrap flags

| Flag | Purpose |
|------|---------|
| `--start` | Pull image and start compose |
| `--image-tag TAG` | Pin GHCR tag (`nightly`, `beta`, semver, `sha-*`) |
| `--platform auto\|linux/amd64\|linux/arm64` | Pull platform |
| `--root PATH` | Install root (default `~/open-fdd`) |
| `--restart` | `compose up -d --force-recreate` |

## Layout after bootstrap

```text
~/open-fdd/
  docker-compose.yml
  workspace/
    auth.env.local       # integrator password — chmod 600, never commit
    data.env.local
    bacnet/commissioning/commission.env
    data/historian/      # Arrow / Feather partitions
    data/drivers/
  scripts/
    openfdd_rust_site_backup.sh
    openfdd_rust_site_update.sh
    openfdd_rust_edge_validate.sh
```

## First login & health

```bash
cd ~/open-fdd
./scripts/openfdd_rust_edge_validate.sh
curl -s http://127.0.0.1:8080/api/health | jq '{version, image_tag}'
```

Open `http://127.0.0.1:8080` — sign in with the integrator user from `workspace/auth.env.local`.

Default bind is **127.0.0.1:8080**. Reach the UI over Tailscale, VPN, or a reverse proxy — not raw public internet.

{: .warning }
Never run `docker compose down -v`. Never delete `workspace/`.
