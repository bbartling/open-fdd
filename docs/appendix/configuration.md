---
title: Configuration reference
parent: Appendix
nav_order: 3
---

# Configuration reference

## Bridge / auth

| Variable | Default | Notes |
|----------|---------|-------|
| `OFDD_BRIDGE_HOST` | `127.0.0.1` | `0.0.0.0` for LAN |
| `OFDD_AUTH_SECRET` | — | Required for LAN |
| `OFDD_AUTH_DISABLED` | `0` | Localhost dev only |
| `OFDD_INSECURE_LAN_DEV` | `0` | Lab only with auth disabled |

## BACnet

| Variable | Notes |
|----------|-------|
| `BACNET_BIND` | `ip/mask:47808` in `commission.env` |
| `OFDD_BACNET_WRITE_ENABLED` | Default off — site-specific name may vary |

## Docker edge

| Variable | Notes |
|----------|-------|
| `OPENFDD_IMAGE_TAG` | GHCR tag for Ansible deploy |
| `openfdd_docker_pull_from_ghcr` | Ansible host_var |

Full schema for YAML engine rules: `docs/config_schema.json`.
