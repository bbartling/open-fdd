---
name: rules-crud-and-batch-run
description: "Manages saved Python FDD rules from Rule Lab and runs batched jobs against feather timeseries. Use when operators save rules via API or dashboard and execute FDD on stored metrics."
---

# Rules CRUD and batch run

## When to use / When not to use

Use when operators author Python rules in Rule Lab, persist them, and run scheduled or on-demand batch FDD.

Arrow-native rules use `apply_faults_arrow` via the operator bridge Rule Lab — see [openfdd-rule-authoring-agent](../openfdd-rule-authoring-agent/SKILL.md).

## Prerequisites

- [feather-local-storage](../feather-local-storage/SKILL.md)
- Bridge playground sandbox (`openfdd_bridge.playground`)

## Quick start

| Endpoint | Purpose |
|----------|---------|
| `GET /api/rules/saved` | List saved rules (`rules_store.json`) |
| `POST /api/rules/save` | Create/update rule metadata + inline code |
| `GET/PUT /api/rules/saved/{id}/source` | Read/write `.py` on disk under `data/rules_py/` |
| `POST /api/rules/batch` | Run all enabled rules against modeled sites |
| `POST /api/playground/test-rule` | Preview per-row `evaluate()` on a frame |
| `POST /api/playground/run-script` | Preview DataFrame script mode |
| `POST /openfdd-agent/tool` | Agent role: `rules.save`, `rules.run_batch` (same files as UI) |

Scheduled loop (from `workspace/api/`):

```bash
python -m openfdd_bridge.fdd_runner --loop --interval-minutes 10
```

Local stack: `./scripts/run_local.sh start` starts the FDD loop in the background. Ansible: `openfdd-fdd-loop.timer`.

**Shared storage doc:** [docs/howto/rule_lab_storage.md](../../docs/howto/rule_lab_storage.md).

## Verification

```bash
pytest tests/workspace_bridge/test_rules_and_fdd.py -q
```

## Gotchas

- Rules execute **server-side** only; the browser sends source text to the bridge, which writes **`rules_py/*.py`**.
- Disk `.py` is canonical at run time; JSON inline `code` is fallback only.
- Set `fault_code` from `GET /api/faults/catalog` when saving — codes are fixed.
- Bindings live on the Data Model tab (`POST /api/rules/bindings`), not Rule Lab.
- Batch runs can be CPU-heavy; cap `limit` per operator policy.
- Ollama chat (`/openfdd-agent/chat`) does not auto-call `rules.save` — use `POST /openfdd-agent/tool` or Rule Lab APIs.

See [references/REFERENCE.md](references/REFERENCE.md).
