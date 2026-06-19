---
title: Raspberry Pi edge bootstrap
parent: Quick Start
nav_order: 5
---

# Raspberry Pi edge bootstrap

Open-FDD edge deploy on **Raspberry Pi 4/5 (64-bit)** uses the same bootstrap as x86 Linux. Docker must be installed; the host must be **aarch64 / arm64** (not 32-bit Raspberry Pi OS).

## One-liner

```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh --start
```

## Error: `no matching manifest for linux/arm64/v8`

This means **GHCR does not yet have an ARM64 build** for that image tag (not a Docker install problem).

```text
Error response from daemon: no matching manifest for linux/arm64/v8 in the manifest list entries
```

### Confirm

```bash
cd ~/open-fdd
./scripts/openfdd_check_ghcr_platform.sh
```

Or manually:

```bash
docker buildx imagetools inspect ghcr.io/bbartling/openfdd-bridge:latest | grep -E 'linux/arm64|linux/amd64'
```

You need **`linux/arm64`** on all three: `openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag`.

### Option A — Native ARM64 images (recommended)

Open-FDD publishes **multi-arch** images (`amd64` + `arm64`) from the GitHub **Publish Docker images to GHCR** workflow. After a release that includes ARM64:

```bash
bash /tmp/openfdd_edge_bootstrap.sh --start
```

### Option B — QEMU emulation (lab only, slow)

Use only while waiting for ARM64 publish:

```bash
sudo apt update
sudo apt install -y qemu-user-static binfmt-support
docker run --privileged --rm tonistiigi/binfmt --install amd64

cd ~/open-fdd
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose pull
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d

docker compose ps
curl -sf http://127.0.0.1:8765/health | jq .
```

Expect slower startup and higher CPU use. Not recommended for production BACnet polling.

### Option C — Build on the Pi

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/docker_build.sh
# point compose at local tags — see scripts/docker_build.sh header
```

## OpenClaw / AI agent on Pi

1. Bootstrap must finish with **`docker compose ps`** showing bridge, commission, mcp-rag **Up**.
2. Agent needs **terminal/shell** access on the Pi (not chat-only) to run `docker` and `curl`.
3. Use the [README OpenClaw bootstrap prompt](https://github.com/bbartling/open-fdd/blob/master/README.md#ai-agent-prompt) — it checks `uname -m` and GHCR pull before declaring success.
4. Login: `integrator` / password in `~/open-fdd/workspace/auth.env.local` (never paste passwords into chat).

## Validate

```bash
docker compose ps
curl -sf http://127.0.0.1:8765/health | jq .
grep BACNET_BIND ~/open-fdd/workspace/bacnet/commissioning/commission.env
```

Dashboard: `http://<pi-ip>:8765/` (or Caddy on `:80` when configured).

## Related

- [Edge site lifecycle]({{ "/quick-start/site-lifecycle/" | relative_url }})
- [Run with Docker]({{ "/quick-start/docker/" | relative_url }})
