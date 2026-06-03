---
title: Home
nav_order: 1
description: "Deploy Open-FDD on a building edge — Docker, Ansible, BACnet, Rule Lab, local check-engine AI."
---

# Open-FDD

Deploy a **building operator stack** on an edge VM or lab host (Acme, bensserver, field Pi): BACnet commission → feather historian → **Python Rule Lab** FDD → dashboard with a **check-engine light**.

The same repo also ships **`open-fdd` on PyPI** — a pandas YAML rules engine for offline CSV/notebook work. That library is documented in the back of this site under [Fault rules (engine)](rules/).

---

## Start here

| Step | Doc |
|------|-----|
| 1 | [Getting started](getting_started) — deploy checklist, **what AI can / cannot do**, BACnet NIC bind |
| 2 | [System overview](overview) — containers, data flow, Acme-style topology |
| 3 | [Docker edge deploy](edge_deploy_docker) — build images, Ansible `deploy.sh docker`, health |
| 4 | [Local Ollama (check-engine)](local_ollama) — on-box AI vs your deployment AI |
| 5 | [Operator dashboard](howto/operator_dashboard) — Rule Lab, trends, faults |
| 6 | [BACnet driver capabilities](bacnet/capabilities) — discover, read, write, poll, mapping |
| 7 | [Arrow data plane](architecture/arrow_data_plane) — Feather/Arrow historian: what is and is not columnar |
| 8 | [Bridge HTTP API](appendix/bridge_api) — REST reference for integrators |

**Quick local stack:**

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
./scripts/docker_build.sh
./scripts/openfdd_stack.sh up
./scripts/stack_health_check.sh
```

Open `http://<host>/` (Caddy :80 → bridge :8765). Auth: `workspace/auth.env.local` (see [Security hardening](security_hardening)).

---

## AI-assisted bootstrap

Works well with **Cursor**, **Claude Code**, or the repo **agent shell** (`openfdd.toml`, `skills/`, `AGENTS.md`). A deployment assistant can:

- Run tests, build images, and drive Ansible from your laptop
- Discover BACnet (Who-Is, point reads) when the OT NIC is bound correctly
- Import inventory → **BRICK** `model.json`, wire `fdd_input` bindings, draft Rule Lab Python
- Tune thresholds and explain fault episodes from feather + `fdd_results.json`

It should **not** be treated as a substitute for locked-down production credentials, unchecked BACnet writes on live plant, or sign-off on life-safety interlocks. See the full checklist in [Getting started](getting_started).

---

## Distribution

| Channel | Status |
|---------|--------|
| **Git + Docker tar** | Today — `./scripts/docker_build.sh --save`, Ansible load on edge |
| **PyPI** `open-fdd` | Coming soon |
| **GHCR images** | Coming soon — [Publish Docker addons](howto/publish_docker_addons) |

---

## Inspiration

Open-FDD’s packaging (supervisor, versioned container images, bind-mounted `workspace/` state on a thin host) is **inspired by** the [Home Assistant](https://www.home-assistant.io/) project and [Home Assistant OS](https://github.com/home-assistant/operating-system). This is an independent BACnet/FDD operator product, not a Home Assistant add-on.

---

## License

MIT — repository `LICENSE`.
