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

Clone the repo and bring up a recipe. The `fieldbus` service uses host
networking for BACnet/IP, so run the `standalone` recipe for an all-on-Pi edge:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/openfdd_stack_up.sh standalone
```

Pin a release tag:

```bash
OPENFDD_IMAGE_TAG=3.3.0 ./scripts/openfdd_stack_up.sh standalone
```

To attach the Pi as a remote fieldbus edge to a central hub instead, use the
`edge` recipe (see [Build recipes](../operations/build-recipes.md)).

## BACnet on Pi

The `fieldbus` container uses `network_mode: host` for BACnet/IP. Ensure the Pi
NIC is on the OT BACnet subnet and configure `config/fieldbus/` for your site.

## Updates

```bash
# back up workspace/ first (see Site lifecycle)
OPENFDD_IMAGE_TAG=3.3.0 ./scripts/openfdd_stack_up.sh standalone
./scripts/openfdd_health_check.sh
```

See [Site lifecycle](site-lifecycle.html) for backup and restore details.
