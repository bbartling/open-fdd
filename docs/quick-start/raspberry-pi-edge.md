---
title: Raspberry Pi edge
parent: Quick Start
nav_order: 2
---

# Raspberry Pi edge

Open-FDD publishes **linux/arm64** images suitable for Raspberry Pi 4/5 with a 64-bit OS.

## Requirements

- Raspberry Pi 4 or 5, 4 GB+ RAM recommended
- 64-bit Raspberry Pi OS or Ubuntu Server
- Docker Engine + Compose plugin

## Install

Use the same bootstrap script as any Linux edge host:

```bash
curl -fsSL -o /tmp/openfdd_rust_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_rust_edge_bootstrap.sh
bash /tmp/openfdd_rust_edge_bootstrap.sh --start --platform linux/arm64
```

Or pin a release tag:

```bash
bash /tmp/openfdd_rust_edge_bootstrap.sh --start --image-tag 3.2.4 --platform linux/arm64
```

## Full edge on Pi

```bash
cd ~/open-fdd
export OPENFDD_COMPOSE_ROOT=$PWD
docker compose -f docker/compose.edge.rust.yml --profile full-edge up -d
./scripts/openfdd_rust_edge_validate.sh
```

## BACnet on Pi

The commission container uses `network_mode: host` for BACnet/IP. Ensure the Pi NIC is on the OT BACnet subnet and configure `workspace/bacnet/commissioning/commission.env` for your site.

## Updates

```bash
./scripts/openfdd_rust_site_backup.sh
NEW_TAG=3.2.4 ./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

See [Site lifecycle](site-lifecycle.html) for backup and restore details.
