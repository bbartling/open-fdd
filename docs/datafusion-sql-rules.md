# DataFusion SQL rules (optional)

Open-FDD v3 remains **PyArrow-first**. Rules implement `apply_faults_arrow(table, cfg, context=None)` and return a boolean Arrow mask.

The optional **DataFusion SQL** backend (`backend: datafusion_sql`) is a future-Rust-prep seam:

- Input: PyArrow `Table` registered as `telemetry`
- Rule body: a restricted `SELECT` that adds a boolean `fault` column
- Output: the same `ArrowRuleResult` shape as PyArrow rules

Install:

```bash
pip install 'open-fdd[datafusion]'
```

## When to use SQL vs PyArrow

| Use DataFusion SQL | Use PyArrow |
| --- | --- |
| Simple thresholds, `CASE WHEN`, boolean logic | Custom HVAC helpers, rolling windows, ML prep |
| SQL-readable expressions for operators | Complex graph/feature work |
| Proving parity before Rust migration | Primary supported authoring path |

## Rule metadata

```yaml
id: zone_temp_high_sql
name: Zone temperature high — SQL
backend: datafusion_sql
fault_column: fault
sql: |
  SELECT
    *,
    zone_temp > 75.0 AS fault
  FROM telemetry
```

## Safety

SQL rules are **not** a database console. The linter rejects:

- Multiple statements, DDL/DML
- Reads other than `FROM telemetry`
- File paths and external URLs
- Missing or non-boolean `fault` column
- Row counts that differ from input telemetry
- Wrong fault column alias (e.g. `not_fault` when `fault` is required)

Server-side execution only — the Rules Lab browser editor never runs SQL locally.

## Rules Lab

In **Rule Lab**, choose **PyArrow** or **DataFusion SQL**:

- **Validate SQL** — lint + optional server preview on latest historian sample
- **Run Preview** — bounded sample against site telemetry
- **Compare backends** — prove an equivalent SQL rule matches a PyArrow rule mask

See [ADR: DataFusion Rust-ready backend](adr/adr-datafusion-rust-ready-rule-backend.md).
