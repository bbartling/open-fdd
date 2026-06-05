---
title: Local development
parent: Developer Guide
nav_order: 1
---

# Local development

## Clone and auth

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
cp workspace/auth.env.example workspace/auth.env.local
# Edit integrator/operator passwords and OFDD_AUTH_SECRET (32+ chars)
```

## Start stack

```bash
./scripts/build_and_test.sh          # dashboard build + pytest
./scripts/docker_build.sh
./scripts/openfdd_stack.sh up
./scripts/stack_health_check.sh
```

| URL | Service |
|-----|---------|
| `http://127.0.0.1:8765` | Bridge (direct) |
| `http://127.0.0.1:8765/docs` | OpenAPI |

## BACnet bench overlay (optional)

```bash
docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml up -d
# commission.env — set BACNET_BIND to your OT interface
```

## Docs preview

```bash
cd docs && bundle install && bundle exec jekyll serve
# http://127.0.0.1:4000/open-fdd/
```
