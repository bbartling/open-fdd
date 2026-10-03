---
title: Raspberry Pi edge
parent: Quick Start
nav_order: 2
---

# Raspberry Pi edge

**Recipe 2 on arm64.** Protocol images already publish `linux/arm64`. Central + web multi-arch is in flight — treat a full Pi Recipe 2 boot as **Soft-OPEN** until `docker manifest inspect` shows both arches for the tip you pin and a Pi boots central+web+protocol without a local broker.

## Requirements

- Raspberry Pi 4 or 5, 4 GB+ RAM recommended (Pi 3 is fieldbus-only / not a full soak host)
- 64-bit Raspberry Pi OS or Ubuntu Server
- Docker Engine + Compose plugin

## Install

Prefer broker-free Recipe 2 (`csv` / local-fieldbus) when the tip has arm64 central+web. `standalone` still works for all-in-one OT when you want a local broker:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
# Confirm tip arches first:
docker manifest inspect ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:-nightly}
./scripts/openfdd_stack_up.sh csv          # Recipe 2 shape (no mqtt)
# or protocol on-box:
./scripts/openfdd_stack_up.sh standalone
```

Pin a reproducible tip:

```bash
OPENFDD_IMAGE_TAG=sha-<7> ./scripts/openfdd_stack_up.sh csv
```

Optional: attach the Pi as a remote fieldbus publisher to a Recipe 1 hub with the
`edge` recipe (see [Build recipes](../operations/build-recipes.md)). MQTTS publish is optional and off by default.

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
