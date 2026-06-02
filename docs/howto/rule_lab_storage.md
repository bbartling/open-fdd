---
title: Rule Lab — Python storage & shared editing
parent: How-to guides
nav_order: 7
---

# Rule Lab — Python storage & shared editing

Operator FDD rules are **Python**, not hot-reloaded YAML. Humans edit them in the **Rule Lab** browser tab; the bridge API and scheduled runner read the **same files on disk**. An AI assistant with the **`agent`** role can write the same sources via `POST /openfdd-agent/tool` (`rules.save`).

---

## Where files live

Data root: **`workspace/data/`** (override with `OFDD_DESKTOP_DATA_DIR`).

| Path | What it holds |
|------|----------------|
| `workspace/data/rules_store.json` | Rule **index**: id, name, mode (`rule` \| `script`), `config`, `bindings`, `applies_to`, `fault_code`, severity, enabled, **`source_path`** |
| `workspace/data/rules_py/*.py` | **Canonical Python source** — one file per saved rule (slug from rule name) |
| `workspace/data/fdd_results.json` | Latest batch FDD output → building check-engine light |
| `workspace/data/feather_store/` | Timeseries the rules run against (BACnet poll, CSV, demo) |
| `workspace/data/model.json` | BRICK model — point `fdd_input` keys feed `column_map` at run time |

**Dual-write model:** saving always updates **both** JSON metadata and a `.py` file. At run time, code is read from disk first (`source_path`); inline `code` in JSON is a fallback only.

Implementation: `openfdd_bridge.rule_store`, `openfdd_bridge.rule_source`, `openfdd_bridge.fdd_runner`.

### Git

- `rules_store.json` is **gitignored** (site-specific bindings and enable flags).
- `rules_py/*.py` is **tracked** — commit cookbook/bench templates; operators can version-control rule logic without the JSON index.
- Bench seed: `python scripts/setup_bench_afdd.py` repopulates store + `.py` files for local demos.

---

## Browser (Rule Lab tab)

Route: **`/rule-lab`** (`RuleLabPage.tsx` + `PythonCodeEditor`).

### What you do in the UI

1. **Pick or create** a rule from the saved-rules dropdown.
2. **Edit Python** in the editor (mode **rule**: `evaluate(row, cfg, …)`; mode **script**: DataFrame `out = {"df": …}`).
3. **Lint** (debounced) → `POST /api/playground/lint`.
4. **Test** on live/demo feather data → `POST /api/playground/test-rule` or `POST /api/playground/run-script`.
5. **Save** → writes `.py` + updates `rules_store.json`.
6. **Update all records** → `POST /api/rules/batch` (same as scheduled FDD).
7. The footer shows the on-disk path, e.g. `File: workspace/data/rules_py/bench_oa-t_flatline_1h.py`.

### Save flow (existing rule)

```
PUT  /api/rules/saved/{id}/source   ← editor text → .py file
POST /api/rules/save                ← metadata, config, fault_code, bindings ref
```

New rules use `POST /api/rules/save` only (creates id + `.py` in one step).

### Bindings (not on Rule Lab)

Map rules to BACnet points on **`/data-model`** (Rule mapping board):

- `POST /api/rules/bindings` — point_ids, equipment_ids, brick_types
- At batch run, the bridge merges point `fdd_input` / BRICK keys into `column_map`.

### Auth

| Role | Rule Lab |
|------|----------|
| **integrator** | Full edit, save, batch |
| **agent** | Same + `POST /openfdd-agent/tool` |
| **operator** | Read-only warning — view code, no save |

---

## Scheduled FDD (same Python)

On Docker edges, `openfdd-fdd-loop.timer` runs `fdd_runner` inside the bridge container. Local dev (`./scripts/openfdd_stack.sh up`) uses the commission poll loop; trigger FDD manually with `docker compose exec bridge python -m openfdd_bridge.fdd_runner --once` or `POST /api/rules/batch`.

Legacy local stack (`./scripts/run_local.sh start`) starts a background loop:

```bash
# workspace/api — required working directory
python -m openfdd_bridge.fdd_runner --loop --interval-minutes 10 --lookback-hours 1
```

Env: `OFDD_FDD_INTERVAL_MINUTES`, `OFDD_FDD_LOOKBACK_HOURS`.

Each cycle:

1. `RuleStore().list_rules()` — enabled rules only
2. For each rule × resolved site: load feather frame → `prepare_fdd_rows` → `playground.sweep_rule()` (or script mode)
3. Code from **`read_source(source_path)`** — same `.py` the browser saved
4. `save_results()` → `fdd_results.json` → **`/`** check-engine light

Ansible edge: `openfdd-fdd-loop.timer` runs `--once` on an interval.

Log (local): `workspace/.local-run/fdd_loop.log`

---

## AI agent — same files

Two surfaces; both hit the bridge, not Codex in the browser.

### 1. AI Agent chat tab (`/agent`)

- `POST /openfdd-agent/chat` — Ollama only; **does not auto-call tools**.
- `GET /openfdd-agent/context` — lists `saved_rules`, `fault_codes`, available `tools` for the system prompt.
- To **write** rules from automation, call tools explicitly (see below) or use Rule Lab APIs with integrator/agent auth.

### 2. Agent tools (`agent` role)

`POST /openfdd-agent/tool` with JSON body `{ "tool": "…", "args": { … } }`:

| Tool | Effect |
|------|--------|
| `rules.save` | `RuleStore().upsert()` — **same path as Rule Lab save**; writes JSON + `rules_py/*.py` |
| `rules.run_batch` | Runs `fdd_runner.run_batch()` → updates check-engine |
| `model.add_*` | BRICK model CRUD |
| `app.edit_file` | Edit files under `workspace/` only if `OFDD_AGENT_ALLOW_APP_EDIT=1` |

Read source without a dedicated tool:

- `GET /api/rules/saved/{id}/source` (integrator/agent auth)
- Or read `workspace/data/rules_py/*.py` on the host (Codex shell, SSH, IDE)

**Human and AI see identical `.py` files** because both persist through `RuleStore.upsert()` → `rule_source.write_source()`.

### Codex agent shell (repo checkout)

`openfdd-agent-shell` follows `AGENTS.md` → [rules-crud-and-batch-run skill](../../skills/rules-crud-and-batch-run/SKILL.md). Scratch experiments go in `workspace/scratch/`; promote keepers via `POST /api/rules/save` or `rules.save` tool.

---

## Data pipeline (BACnet → rules)

```
BACnet poll (commission agent, 60s)
  → workspace/bacnet/polls/samples.csv
Bridge poll worker (on CSV mtime)
  → feather_store/bacnet/<site_id>/latest.feather
FDD loop / Rule Lab test / batch
  → reads feather + rules_py/*.py
  → fdd_results.json → check-engine
```

Enable points in `workspace/bacnet/commissioning/points.csv`; poll status: `GET http://127.0.0.1:8767/api/bacnet/poll/status`.

---

## API quick reference

```
GET    /api/rules/saved
GET    /api/rules/saved/{id}/source
PUT    /api/rules/saved/{id}/source
POST   /api/rules/save
DELETE /api/rules/saved/{id}
POST   /api/rules/bindings
POST   /api/rules/batch

POST   /api/playground/lint
POST   /api/playground/test-rule
POST   /api/playground/run-script

GET    /openfdd-agent/context
POST   /openfdd-agent/tool          # agent role
POST   /openfdd-agent/chat
```

---

## See also

- [Operator dashboard (Rule Lab)](operator_dashboard) — stack start, tabs, auth
- [Building check-engine light](../concepts/check_engine_light) — `fault_code` tagging
- [Verification](verification) — lint/save/batch smoke checks
- [Agent & operator playbook](agent_operator_playbook) — MCP + bridge discovery
- Skill: [rules-crud-and-batch-run](../../skills/rules-crud-and-batch-run/SKILL.md)
