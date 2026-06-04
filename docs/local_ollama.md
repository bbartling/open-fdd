---
title: Local Ollama (check-engine)
nav_order: 4
---

# Local Ollama (check-engine)

On the edge, **Ollama is not your commissioning copilot**. It powers the **building check-engine light** narrative: short GREEN/YELLOW/RED explanations and optional insight lines on the home dashboard — using a **fixed fault catalog** the model cannot invent.

**Deployment AI** (Cursor, Claude, MCP, agent shell on your laptop) owns repo edits, Ansible, BACnet modeling, and Rule Lab drafts. See [Getting started — two AIs](getting_started#4-ai-assisted-deployment--what-works--what-does-not).

---

## What local Ollama can access

| Source | Used for |
|--------|----------|
| `GET /api/faults/status` | Check-engine color + active codes |
| `GET /api/faults/catalog` | Allowed codes only (reject unknown in APIs) |
| Building insight / zone temps | Cached summaries for dashboard copy |
| Trend snippets | Recent feather series (bounded context) |
| MCP RAG (optional) | Project docs — lighter than full repo checkout |

Routes: `GET /openfdd-agent/ollama/health`, `POST /openfdd-agent/chat`, `GET /openfdd-agent/building-insight`, `GET /openfdd-agent/operational-brief`, `GET /openfdd-agent/zone-temps`, `GET /openfdd-agent/device-poll-health`. Home insight uses a **14-day** feather window (`OFDD_ANALYTICS_LOOKBACK_DAYS`) for zone day/night averages, fan-on recovery °F/min, **zone energy research** (setback + sensor cross-check), and per-equipment poll online/flaky (BLD-D alerts when all points on a device are stale/FDD). When recovery is ~0°F/min and day/night temps are flat, the LLM is prompted to investigate missing setback and energy savings — after validating poll/FDD sensor health. See **[operational_analytics.md](operational_analytics.md)**. BRICK interlink: `brick_model_context.py` feeds building insight + Agent chat; operators can run read-only tools (`model.graph`, `timeseries.snapshot`, `faults.lookup`) via `POST /openfdd-agent/tool`. Implementation: `building_insight.py`, `zone_temp_analytics.py`, `zone_energy_research.py`, `device_poll_health.py`, `agent_tools.py`, `brick_model_context.py`.

---

## What it does not do

- Replace Rule Lab execution (Python rules + `fdd_runner` batch)
- Discover BACnet or edit `commission.env` bind
- Push Ansible or rebuild Docker images
- Author new fault codes (catalog is fixed: performance, simultaneous heat/cool, sensor, I/O)

Concept: [Building check-engine light](concepts/check_engine_light).

---

## Where Ollama runs

| Setup | Typical host | Bridge env |
|-------|--------------|------------|
| **GPU VM (Acme)** | Host systemd Ollama | `http://host.docker.internal:11434` |
| **Compose sidecar** | `ollama/ollama` service | `http://ollama:11434` |
| **Disabled** | — | Check-engine still works; AI copy falls back |

Ansible: `deploy.sh ai` (host binary) vs `openfdd_docker_ollama: true`. Variables in `infra/ansible/group_vars/`.

```bash
# Dev — Ollama in compose (Linux; avoids host.docker.internal timeouts)
docker compose -f docker/compose.dev.yml -f docker/compose.ollama-smoke.yml --profile ai up -d
```

More hardware notes: [Ollama on the edge (deploy)](howto/ollama_edge_deploy).

---

## Checklist (local AI)

- [ ] Ollama health (requires auth unless dev bypass):

```bash
# Production / strict auth — login first, then:
TOKEN=$(curl -s -X POST http://127.0.0.1:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_USER","password":"YOUR_PASSWORD"}' | jq -r .access_token)
curl -s http://127.0.0.1:8765/openfdd-agent/ollama/health \
  -H "Authorization: Bearer ${TOKEN}"

# Local dev only: unauthenticated curl works when OFDD_AUTH_DISABLED=1 on trusted localhost
```

- [ ] Model reachable (JSON shows `"ok": true`)
- [ ] Fault catalog page loads; codes are letter suffix (e.g. `VAV-C`) per `fault_catalog.py`
- [ ] Building insight / Agent context mention active `fault_code` values from FDD, not equipment names
- [ ] At least one Rule Lab rule has `fault_code` + enabled binding
- [ ] `POST /api/rules/batch` ran after rule edits
- [ ] Dashboard check-engine matches `GET /api/faults/status`
- [ ] Do **not** point production Ollama at the open internet without auth on bridge

---

## Maintenance

```bash
ollama pull <model>                    # host
docker compose exec ollama ollama pull <model>
journalctl -u ollama -f                # host GPU path
```

Upgrade: bump `ollama_version` in Ansible group_vars and re-run `deploy.sh ai`, or `docker pull ollama/ollama:<tag>`.
