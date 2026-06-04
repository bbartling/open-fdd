---
title: Verification
parent: How-to Guides
nav_order: 18
---

# Verification

Practical checks when authoring or shipping **`open-fdd`** rules.

---

## 1. Unit tests (CI)

From the repo root with dev dependencies (includes **`[engine]`** libraries):

```bash
pip install -e ".[dev]"
pytest open_fdd/tests/engine
```

Expression cookbook regressions live in **`open_fdd/tests/engine/test_expression_cookbook.py`**.

### Agent shell (optional checkout)

When using **`packages/openfdd-agent-shell`**:

```bash
pip install -e "packages/openfdd-agent-shell[dev]"
pytest packages/openfdd-agent-shell -q
```

Covers manifest loading, memory truncation, cron schedules, wake lock behavior, and REPL slash commands (hermetic `tmp_path` workspaces in tests).

### Operator bridge (git checkout)

```bash
./scripts/build_and_test.sh          # vitest + prod UI + pytest tests/workspace_bridge
./scripts/openfdd_stack.sh up              # Docker stack (recommended)
# or: ./scripts/run_local.sh restart --ui-skip   # legacy systemd
curl -sf http://127.0.0.1/health    # Caddy when enabled
curl -sf http://127.0.0.1:8765/health
```

See [Operator dashboard](operator_dashboard).

---

## 2. Operator Rule Lab (Python)

Storage: `workspace/data/rules_store.json` + `workspace/data/rules_py/*.py` — see [Rule Lab storage](rule_lab_storage).

- Lint sample rule: `POST /api/playground/lint` with a minimal `evaluate()` body.
- Preview on demo/feather frame: `POST /api/playground/test-rule` with `code`, `config`, optional `site_id`.
- Save: `POST /api/rules/save` (or `PUT …/source` + `POST …/save` for updates); confirm `.py` exists on disk.
- Batch: `POST /api/rules/batch` or check `workspace/.local-run/fdd_loop.log`; confirm `GET /api/building/status` reflects flagged runs.
- Agent write (optional): `POST /openfdd-agent/tool` with `{ "tool": "rules.save", "args": { … } }` (**agent** role).

---

## 3. Library YAML rules (optional `pip install "open-fdd[engine]"`)

For notebooks or IoT pipelines outside the operator stack:

- Load each file with **`load_rule()`** or point **`RuleRunner(rules_path=...)`** at the directory.
- Confirm every **`inputs`** key has a matching entry in **`column_map`** (or manifest) before calling **`run()`**.

---

## 4. Small DataFrame smoke test (library)

```python
from pathlib import Path
import pandas as pd
from open_fdd.engine.runner import RuleRunner

df = pd.read_csv("your_sample.csv", parse_dates=["timestamp"]).set_index("timestamp")
runner = RuleRunner(rules_path=Path("path/to/rules"))
out = runner.run(df, timestamp_col="timestamp", column_map={"Supply_Air_Temperature_Sensor": "SAT"})
assert any(c.endswith("_flag") for c in out.columns)
```

---

## 5. Post-deploy check (edge / Acme)

After Ansible docker deploy:

```bash
./scripts/post_deploy_check.sh --limit acme_vm_bbartling
```

Uses `infra/ansible/scripts/http_probes.py` (BACnet tree, model SPARQL, agent context). **Ollama is required only** when inventory has in-stack Ollama (`enable_ollama` + `openfdd_docker_ollama: true`) or `post_check_require_ollama: true`. Deploys with `-e openfdd_docker_ollama=false` should set `openfdd_docker_ollama: false` in host vars so post-check does not fail on missing Ollama.

PyPI rule parity (no HTTP):

```bash
PYTHONPATH=. python scripts/validate_acme_rules_pypi.py
pytest open_fdd/tests/playground -q
```
