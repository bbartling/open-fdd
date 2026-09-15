---
title: Railway hub
parent: Quick Start
nav_order: 3
permalink: /quick-start/railway-hub.html
---

# Railway cloud hub bootstrap

Experimental **central + web + mqtt** hub on Railway private networking. Keep **fieldbus on-prem** (ACME / edge) publishing MQTTS into the hub. Not a claim of public-internet production hardening.

## Order

1. Attach persistent volume at central `/workspace`
2. Set unique `OPENFDD_JWT_SECRET`, `OPENFDD_ADMIN_PASSWORD`, `OPENFDD_AGENT_PASSWORD`
3. Deploy **central** → healthy `GET /api/health`
4. Deploy **mqtt** (hub)
5. Deploy **web** with `OPENFDD_CENTRAL_UPSTREAM=openfdd-central…:8080` (no `http://`)

## Pin tip images

Always newest-by-created `sha-*` (never assume `:nightly` is tip):

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt
# then pin OPENFDD_IMAGE_TAG=sha-<7> and recreate
```

Agent ops (CLI): [`openfdd-railway-cli` skill](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md) · full guide in-repo [`docs/operations/RAILWAY_DEPLOYMENT.md`](https://github.com/bbartling/open-fdd/blob/master/docs/operations/RAILWAY_DEPLOYMENT.md).

→ [Local stack](local-stack.html) · [Docker & GHCR](docker-ghcr.html)
