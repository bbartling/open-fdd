# Rules service — reference

**Current bridge** (`workspace/api/openfdd_bridge/`):

| Method | Path | Role |
|--------|------|------|
| GET | `/api/rules/saved` | List saved Python rules |
| POST | `/api/rules/save` | Upsert rule (mode `rule` or `script`) |
| GET | `/api/rules/saved/{id}/source` | Read `.py` source |
| PUT | `/api/rules/saved/{id}/source` | Write `.py` source |
| DELETE | `/api/rules/saved/{id}` | Remove rule |
| POST | `/api/rules/batch` | Batch FDD via `fdd_runner.run_batch` |
| POST | `/api/rules/bindings` | Point/equipment bindings for a rule |

Playground preview (not persisted): `/api/playground/lint`, `test-rule`, `run-script`.

Storage:

- `data/rules_store.json` — metadata, config, bindings, `source_path`
- `data/rules_py/*.py` — durable rule sources

Legacy (retired monolith): YAML files under `data/rules/`, `POST /rules/run`, gateway `/rules/*`.
