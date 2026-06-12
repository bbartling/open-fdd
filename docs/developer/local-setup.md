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

## Production-like local stack (Caddy, LAN scans)

Same shape as an Acme edge deploy: **prod React UI**, **Caddy on :80**, bridge on loopback **8765**, auth enabled. Use for OWASP ZAP or nmap from another machine on the LAN.

```bash
./scripts/pentest_production_stack.sh start    # build prod UI + Caddy + auth.pentest.local
./scripts/pentest_production_stack.sh status   # bridge, commission, caddy, mcp-rag
./scripts/pentest_production_stack.sh verify   # LAN IP, /health, ZAP target URL
./scripts/pentest_production_stack.sh stop     # when done
```

Credentials: `workspace/auth.pentest.local` (generated on first start). ZAP target is usually `http://<lan-ip>/` (benserver example: `http://192.168.204.18/`). If LAN clients cannot reach :80, run `sudo ./scripts/open_lan_port.sh 80`.

See also [Health checks (developer)]({{ "/developer/health-check/" | relative_url }}) for probe details and [ZAP baseline expectations]({{ "/security/zap-baseline/" | relative_url }}) for accepted Medium/Low findings.

## Docs preview

```bash
cd docs && bundle install && bundle exec jekyll serve
# http://127.0.0.1:4000/open-fdd/
```
