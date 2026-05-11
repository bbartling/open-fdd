---
name: ansible-linux-bench-deploy
description: "Deploys a Linux bench over SSH with Open-FDD stack, Caddy, systemd, and optional easy-aso and DIY BACnet sidecars. Use when deploy=ansible_bench or WSL-driven remote bench setup."
---

# Ansible Linux bench deploy

## Playbook order

`site.yml` roles: `common` → `openfdd_stack` → `easyaso` → `diy_bacnet` → `caddy_gateway` → `systemd_services` → `verify`.

## openfdd_stack (legacy)

Clone to `/opt/open-fdd`, venv, `pip install -e ".[desktop,optimization]"`, `npm ci` in dashboard, build MCP index.

For engine-first repo: clone repo, install engine + generate workspace stack per manifest instead of shipping monolith.

## WSL operator flow

Ansible from WSL against SSH bench host; inventory `inventory.ini` from `inventory.example.ini`.

See [references/REFERENCE.md](references/REFERENCE.md).
