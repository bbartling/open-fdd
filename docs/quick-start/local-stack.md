---
title: Local stack (Compose)
parent: Quick Start
nav_order: 2
permalink: /quick-start/local-stack.html
---

# Local stack bootstrap

Run the product on a LAN / VPN host with GHCR images (no local Rust image builds on low-RAM machines).

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/openfdd_stack_pull.sh react-ot   # or: react / csv
./scripts/openfdd_stack_up.sh react-ot --no-pull
```

| Check | Command / URL |
|-------|----------------|
| Central health | `GET http://127.0.0.1:8080/api/health` |
| Web UI | `http://127.0.0.1:3000` (or your Caddy LAN URL) |
| Login | admin / operator JWT — see compose env; never commit secrets |

**Unmerged UI:** serve a **local** web bundle — do not demo stale GHCR `openfdd-web`. Use `./scripts/openfdd_demo_gate.sh --local-web` before pasting a login URL.

**Never:** `docker compose down -v`, delete `workspace/`, or expose the API on the public internet.

More detail (repo, not public Ops nav): [`docs/operations/LOCAL_DEPLOYMENT.md`](https://github.com/bbartling/open-fdd/blob/master/docs/operations/LOCAL_DEPLOYMENT.md).

→ Next: [Docker & GHCR](docker-ghcr.html) · [Railway hub](railway-hub.html) · [Site lifecycle](site-lifecycle.html)
