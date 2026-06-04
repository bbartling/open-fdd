---
title: Getting Started
nav_order: 3
---

# Getting started

Use this page as a **deployment checklist** for a building edge (Acme-style VM or lab host). For library-only pandas/YAML work, jump to [Fault rules (engine)](rules/) at the end.

---

## 1. Clone, test, run locally

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/build_and_test.sh          # UI + pytest (workspace bridge tests)
./scripts/docker_build.sh
./scripts/openfdd_stack.sh up        # or: docker compose -f docker/compose.dev.yml up -d
./scripts/stack_health_check.sh
```

| Check | Command / URL |
|-------|----------------|
| Bridge up | `curl -s http://127.0.0.1:8765/health` |
| Stack probe | `./scripts/stack_health_check.sh` |
| Dashboard | `http://127.0.0.1/` (with Caddy) or `:8765` |
| Auth | Copy `workspace/auth.env.local.example` → `auth.env.local` |

---

## 2. Docker containers (four apps)

| Container | You need it when… |
|-----------|-------------------|
| **bridge** | Always — UI, API, Rule Lab, model, faults |
| **commission** | BACnet discover/read/write on OT LAN |
| **bacnet-poll** | Continuous historian (host network) |
| **mcp-rag** | Deployment AI doc search (optional) |

Details: [System overview](overview). Production push: [Edge deploy (Docker)](edge_deploy_docker).

**Production (GHCR — default):** publish a tag in GitHub Actions, then:

```bash
cd infra/ansible
OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh docker --limit acme_vm_bbartling
OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh ops --limit acme_vm_bbartling
```

See [Publish Docker addons](howto/publish_docker_addons.md) and [GitHub branches / release](howto/github_branches_and_release.md).

**Lab / air-gap (tar):**

```bash
OPENFDD_DOCKER_PULL_FROM_GHCR=0 OPENFDD_IMAGE_TAG=local ./scripts/docker_build.sh --save
OPENFDD_DOCKER_PULL_FROM_GHCR=0 ./deploy.sh docker --limit acme_vm_bbartling
```

---

## 3. BACnet lab bind (see devices on OT NIC)

Commission and poll use **BACpypes** with a bind address from env. For bensserver MSTP bench, copy/adjust:

`workspace/bacnet/commissioning/commission.env`:

```bash
BACNET_BIND=192.168.204.18/24:47808   # your OT interface IP + UDP 47808
BACNET_INSTANCE=599999
DISCOVER_LOW=5007
DISCOVER_HIGH=5007
DISCOVER_TIMEOUT=30
```

Bring up bench overlay:

```bash
docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml up -d
./scripts/setup_local_testbench.sh     # discover → model → seed rules
```

**Test discovery from bridge** (auth token required in prod): `POST /api/bacnet/whois`, `POST /api/bacnet/discover`, then `POST /api/bacnet/import-to-model`. Wrong `BACNET_BIND` → zero I-Am responses (fix NIC/IP before blaming rules).

Field Acme uses Ansible `commission.env.j2` — do not copy lab `commission.env` to production.

---

## 4. AI-assisted deployment — what works / what does not

Use **Cursor**, **Claude**, or `openfdd-agent-shell` with repo `skills/` and `AGENTS.md`. Treat the model as a **commissioning partner**, not an autonomous operator.

### AI can help with

| Area | Examples |
|------|----------|
| **Repo / CI** | `pytest`, `build_and_test.sh`, Dockerfile fixes, Ansible playbook edits |
| **BACnet discovery** | Who-Is interpretation, `points.csv` cleanup, bind troubleshooting *when* OT network is reachable from the edge host |
| **BRICK modeling** | Import rows → equipment/points, `fdd_input` suggestions, SPARQL tree sanity |
| **Rule Lab (Python)** | Draft `evaluate()` rules, flatline/spread/OOB patterns, `fault_code` from catalog |
| **FDD tuning** | Threshold params in rule `config`, explain spread episodes from feather samples |
| **Deploy** | `deploy.sh docker`, `stack_health_check.sh`, journal/compose log triage |
| **Docs / skills** | Keep `skills/*.md` aligned with working paths in `workspace/` |

### AI cannot replace

| Area | Why |
|------|-----|
| **Physical OT access** | VLANs, BBMD, router MSTP port, firewall 47808 — must be correct on site |
| **Safety sign-off** | Writes to live plant, overrides, interlocks — human + RBAC |
| **Secrets** | `auth.env.local`, SSH, API keys — never commit; model must not invent credentials |
| **Guaranteed discovery** | If bind/NIC is wrong, no amount of prompting finds devices |
| **Regulatory compliance** | Your AHJ / customer MOP for overrides and alarms |

### Two different AIs

| | **Deployment AI** (Cursor / Claude / MCP) | **Local Ollama** (on edge) |
|--|-------------------------------------------|----------------------------|
| **Purpose** | Build, deploy, model, write rules, debug stack | **Check-engine light** copy + short building insight |
| **Reach** | Full repo, Ansible, tests, many bridge tools via MCP | Curated context: faults, trends, catalog codes — [Local Ollama](local_ollama) |
| **Runs where** | Your laptop / CI | Acme GPU host or compose sidecar |

---

## 5. Operator workflow (after stack is healthy)

1. **Commission** BACnet → `points.csv` / inventory APIs.
2. **Import model** → BRICK TTL + `model.json`; `POST /api/model/sync-ttl`.
3. **Bind rules** — `fdd_input` per point; save Python in Rule Lab → `rules_py/`.
4. **Run batch** — `POST /api/rules/batch` or host timer; watch **Faults** / check-engine.
5. **Tune** — adjust `config` thresholds; re-test in Rule Lab playground.

Guides: [Operator dashboard](howto/operator_dashboard), [Rule Lab storage](howto/rule_lab_storage), [Skills and agent shell](howto/skills_and_agent).

---

## 6. Expression / rule references

| Style | Where |
|-------|--------|
| **Python** (production edge) | [Expression cookbook (Python / Rule Lab)](expression_rule_cookbook_python) |
| **YAML** (PyPI engine / CSV) | [Expression cookbook (YAML / pandas)](expression_rule_cookbook_yaml) |

---

## PyPI engine only (back of the book)

```bash
pip install "open-fdd[engine]"
pytest open_fdd/tests/engine
```

- [Rules overview](rules/overview)
- [Engine API](api/engine)
- [Standalone CSV + pandas](standalone_csv_pandas)

---

## Where to read next

- [System overview](overview)
- [Docker edge deploy](edge_deploy_docker)
- [BACnet driver capabilities](bacnet/capabilities)
- [Local Ollama](local_ollama)
- [Security hardening](security_hardening)
- [Bridge HTTP API](appendix/bridge_api)
