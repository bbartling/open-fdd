# Rules service — reference

**Current bridge** (`workspace/api/openfdd_bridge/`):

| Method | Path | Role |
|--------|------|------|
| GET | `/api/rules/saved` | List saved Python rules |
| POST | `/api/rules/save` | Upsert rule (mode `rule` or `script`); writes JSON + `.py` |
| GET | `/api/rules/saved/{id}/source` | Read `.py` source from disk |
| PUT | `/api/rules/saved/{id}/source` | Write `.py` source (Rule Lab save flow) |
| DELETE | `/api/rules/saved/{id}` | Remove rule |
| POST | `/api/rules/batch` | Batch FDD via `fdd_runner.run_batch` |
| POST | `/api/rules/bindings` | Point/equipment/brick bindings (UI: Data Model tab) |

Playground preview (not persisted): `/api/playground/lint`, `test-rule`, `run-script`.

Agent ( **`agent`** role):

| Method | Path | Role |
|--------|------|------|
| GET | `/openfdd-agent/context` | Model summary, `saved_rules`, `tools`, fault codes |
| POST | `/openfdd-agent/tool` | `rules.save`, `rules.run_batch`, model CRUD |
| POST | `/openfdd-agent/chat` | Ollama chat (no auto tool calls) |

## Storage (shared by browser, FDD loop, and AI)

Data root: `OFDD_DESKTOP_DATA_DIR` → default `workspace/data/`.

| Path | Role |
|------|------|
| `rules_store.json` | Metadata index (gitignored) |
| `rules_py/*.py` | **Canonical Python** — read at batch run time |
| `fdd_results.json` | Latest batch output → check-engine |
| `feather_store/` | Timeseries input for rules |

Save path in code: `rule_store.RuleStore.upsert()` → `rule_source.write_source()`.

Run path: `fdd_runner._rule_code()` → `read_source(source_path)` first, JSON `code` fallback.

## Site resolution (`fdd_runner.resolve_site_ids`)

1. Explicit `applies_to.site_ids`
2. Else sites matching `bindings.point_ids` / `equipment_ids` / `brick_types`
3. Else `applies_to.equipment_type` or `brick_type`
4. Else all model sites, then feather sites, then `"demo"`

## Scheduled loop

Local dev (`scripts/run_local.sh`):

```bash
cd workspace/api
python -m openfdd_bridge.fdd_runner --loop --interval-minutes 10 --lookback-hours 1
```

Env: `OFDD_FDD_INTERVAL_MINUTES`, `OFDD_FDD_LOOKBACK_HOURS`, `OFDD_RULE_INTERVAL_HOURS` (legacy hours).

Ansible: `openfdd-fdd-loop.service` runs `--once` on timer.

Bench seed: `python scripts/setup_bench_afdd.py`.

## Operator doc

Human + AI shared editing: [docs/howto/rule_lab_storage.md](../../../docs/howto/rule_lab_storage.md).

Legacy (retired monolith): YAML files under `data/rules/`, `POST /rules/run`, gateway `/rules/*`.
