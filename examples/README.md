# Open-FDD PyPI examples (Arrow-native)

These examples use **`pip install open-fdd`** — the embeddable FDD runtime. They do **not** require Docker, BACnet, or the Operator Bridge.

| Example | Purpose |
|---------|---------|
| [arrow_minimal/](arrow_minimal/) | Smallest `apply_faults_arrow` + `run_arrow_rule` |
| [datafusion_sql_rule/](datafusion_sql_rule/) | Optional DataFusion SQL backend (`pip install open-fdd[datafusion]`) |
| [feather_rule_run/](feather_rule_run/) | Run a rule against a Feather file |
| [cloud_pipeline/generic_iot_pipeline/](cloud_pipeline/generic_iot_pipeline/) | IoT rows → Arrow → FDD → fake fault sink |

**Rule contract:** rules define `apply_faults_arrow(table, cfg, context=None)` and return a PyArrow boolean mask (or documented `ArrowRuleResult` from `run_arrow_rule`). An optional **DataFusion SQL** backend (`backend: datafusion_sql`) uses the same result shape for simple expression-style rules — see [docs/datafusion-sql-rules.md](../docs/datafusion-sql-rules.md).

**Full edge stack:** GHCR images `openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag` — see [Run with Docker images](https://bbartling.github.io/open-fdd/quick-start/docker/).
