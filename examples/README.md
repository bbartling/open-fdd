# Open-FDD PyPI examples (Arrow-native)

These examples use **`pip install open-fdd`** — the embeddable FDD runtime. They do **not** require Docker, BACnet, or the Operator Bridge.

| Example | Purpose |
|---------|---------|
| [arrow_minimal/](arrow_minimal/) | Smallest `apply_faults_arrow` + `run_arrow_rule` |
| [feather_rule_run/](feather_rule_run/) | Run a rule against a Feather file |
| [cloud_pipeline/generic_iot_pipeline/](cloud_pipeline/generic_iot_pipeline/) | IoT rows → Arrow → FDD → fake fault sink |

**Rule contract:** rules define `apply_faults_arrow(table, cfg, context=None)` and return a PyArrow boolean mask (or documented `ArrowRuleResult` from `run_arrow_rule`).

**Not included here:** pandas/YAML `RuleRunner` notebooks — archived under `_archive/examples_pandas_yaml/`.

**Full edge stack:** GHCR images `openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag` — see [Run with Docker images](https://bbartling.github.io/open-fdd/quick-start/docker/).
