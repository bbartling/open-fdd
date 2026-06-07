---
title: Operations
nav_order: 9
has_children: true
---

# Operations

Runbooks for live edge hosts after the initial deploy.

| Page | When to use |
|------|-------------|
| [Logging and audit](logging) | Audit JSONL, auth trail, rotation defaults, Docker log caps, SIEM export |
| [Live site update (SSH)](live_site_update) | Minimal `~/open-fdd/` folder on a VM — pull new GHCR tags, preserve `workspace/` |
| [Acme GL36 FDD](acme-gl36-fdd) | vm-bbartling poll scope, example Arrow rules, AI modeling workflow |

For first-time deploy from a control machine, see [Quick Start — Docker](../quick-start/docker).
