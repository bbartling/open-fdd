---
title: Getting Started
nav_order: 3
---

# Getting Started

Install **`open-fdd`**, run the engine test suite, and try **`open_fdd.reports`** in a notebook.

For the **operator stack** (Rule Lab, BACnet, feather historian on a building VM or Pi), start with the architecture below, then [HA OS alignment](architecture/haos_alignment), [Operator dashboard](howto/operator_dashboard), [Edge deploy (secrets layout)](edge_deploy.md), and [Ansible README](https://github.com/bbartling/open-fdd/blob/master/infra/ansible/README.md).

---

## Edge architecture (feather, Python FDD, Ansible)

On a **git checkout**, Open-FDD is more than the PyPI library: each building runs an **edge stack** you install and maintain with **Ansible**. The diagram is the current reference for how pieces connect.

![Open-FDD edge stack — feather historian, Python FDD, Ansible deploy](assets/Open_FDD_Ansible.png)

| Layer | What it is | Where it lives |
|-------|------------|----------------|
| **OS** (future) | Thin Buildroot host + Docker + OTA | `os/` — today Ubuntu + Docker CE |
| **Supervisor** | Addon manifest, compose, health | `supervisor/` — dev: `./scripts/openfdd_stack.sh` |
| **Apps** | Bridge, poll, commission, MCP images | `docker/` — `./scripts/docker_build.sh` |
| **Ansible** | Push images + workspace to field hosts | `infra/ansible/` — `./deploy.sh docker` or `all` |
| **BACnet poll** | RPM scrape → long CSV → feather wide frames | `openfdd-bacnet-poll`, `bacnet_toolshed/` |
| **Feather store** | Site timeseries on disk (pyarrow); retention/GiB cap | `workspace/data/feather_store/` |
| **Bridge API** | Auth, model, Rule Lab, plots, ingest, check-engine | `openfdd-bridge` (:8765, Caddy :80) |
| **Python FDD** | Saved rules in `rules_py/`, batch loop, playground test | `open_fdd` + `workspace/api/openfdd_bridge/` |

**Typical flow:** commission BACnet points → poll writes **samples.csv** → ingest compacts **feather** → operators edit **Python rules** in Rule Lab → scheduled **FDD loop** updates fault records → **Trend plot** reads the same feather data.

**App maintenance (short list):**

1. Build UI locally: `./scripts/build_operator_dashboard.sh prod` (or `build_and_test.sh` before deploy).
2. Deploy to edge: copy `secrets/acme.env.example` → `secrets/acme.env.local` (gitignored), then `cd infra/ansible && ./deploy.sh all --limit <host>` — see [edge_deploy.md](edge_deploy.md). Components: `ui`, `backend`, `drivers`, `commission` (`deploy.sh help`).
3. Logs: `journalctl -u openfdd-bridge -u openfdd-bacnet-poll -f` on the host.
4. Health: `curl -s http://127.0.0.1:8765/health` on the edge (poll status when commission agent is up).

Details: [Rule Lab storage](howto/rule_lab_storage), [Operator dashboard](howto/operator_dashboard), [infra/ansible/README.md](https://github.com/bbartling/open-fdd/blob/master/infra/ansible/README.md).

---

## Install from PyPI

```bash
pip install "open-fdd[engine]"
pip install "open-fdd[reports]"   # optional: matplotlib for plots
pip install python-docx           # optional: Word reports only
```

Bare wheel (pandas only):

```bash
pip install open-fdd
```

Python **3.10+** is required.

---

## Develop from a git checkout

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
python -c "from open_fdd.engine import RuleRunner; from open_fdd import reports; print('OK')"
pytest open_fdd/tests/engine
```

Optional **agent shell** (not on PyPI): `pip install -e packages/openfdd-agent-shell`, copy `openfdd.toml.example` → `openfdd.toml`, then see **[Skills and agent shell](howto/skills_and_agent)**.

---

## Minimal engine + reports

```python
from open_fdd.engine import RuleRunner
from open_fdd.reports import summarize_fault, get_fault_events

runner = RuleRunner(rules_path="path/to/rules")
df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})

flag = "my_rule_flag"
events = get_fault_events(df_out, flag_col=flag)
summary = summarize_fault(df_out, flag_col=flag, timestamp_col="timestamp")
```

Use any **`column_map`** keys you choose; example rules under **`examples/`** may use optional **`brick:`** fields — see [Column map resolvers](column_map_resolvers).

---

## Examples

See **`examples/README.md`** for CSV demos and notebooks.

---

## Where to read next

- [Expression rule cookbook](expression_rule_cookbook)
- [Engine API](api/engine)
- [Reports API](api/reports)
- [Rules overview](rules/overview)
- [Column map resolvers](column_map_resolvers)
- [How-to: engine-only IoT](howto/engine_only_iot)
- [Operator dashboard](howto/operator_dashboard) — `./scripts/run_local.sh restart`, production React + Caddy
- [Skills and agent shell](howto/skills_and_agent) — `openfdd.toml`, workspace, Codex (checkout only)
- [BACnet toolshed](bacnet/index) — discovery and polling CLI (`bacnet_toolshed/`)
- [Verification](howto/verification)
- [Contributing](contributing)
