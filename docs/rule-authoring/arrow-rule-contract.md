---
title: Arrow rule contract (v1)
parent: Rule authoring (v1)
nav_order: 2
---

# Arrow rule contract (v1)

Stable v1 batch FDD, Rule Lab preview, and validation smokes share one execution contract.

## Entrypoint

```python
def apply_faults_arrow(table: pa.Table, cfg: dict | None = None, context: dict | None = None):
    ...
```

| Parameter | Type | Notes |
|-----------|------|-------|
| `table` | `pyarrow.Table` | Historian telemetry for one site/window |
| `cfg` | `dict` | Rule thresholds, column names, confirmation settings |
| `context` | `dict` \| `None` | Optional bridge metadata (`site_id`, equipment hints) |

## Return type (authoring)

`apply_faults_arrow` must return a **boolean** `pyarrow.Array` or `pyarrow.ChunkedArray`:

- Length **must equal** `table.num_rows`
- `True` = raw fault sample (before confirmation)
- Non-boolean returns are cast to bool by the backend
- Null slots in the mask are counted; prefer explicit `False` for missing inputs

The backend normalizes via `open_fdd.arrow_runtime.backend.normalize_fault_mask`.

## Runtime result (`ArrowRuleResult`)

After execution, `run_arrow_rule()` produces `ArrowRuleResult`:

| Field | Meaning |
|-------|---------|
| `rule_id` | Saved rule id |
| `backend` | `"arrow"` or `"datafusion_sql"` |
| `row_count` | Input table rows |
| `true_count` / `false_count` / `null_count` | Mask statistics |
| `duration_ms` | Wall time |
| `fault_mask` | **Confirmed** boolean mask (see below) |
| `warnings` / `errors` | Lint/runtime messages |
| `summary` | Execution evidence, site id, backend path |
| `preview` | Sample fault rows for Rule Lab UI |

Use `.as_dict()` for API JSON. Both PyArrow and DataFusion SQL backends normalize to this shape.

## Raw mask vs confirmation

1. Rule returns **raw** boolean mask (`apply_faults_arrow` or SQL `fault` column).
2. Backend applies **fault confirmation** when `cfg` includes `min_true_rows` and/or `min_elapsed_minutes` (see [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }})).
3. `ArrowRuleResult.fault_mask` is the **post-confirmation** mask used for batch counts and dashboard alerts.

Confirmation is backend-owned — rules should not implement debounce logic unless documenting a special case.

## DataFusion SQL rules

SQL modules still expose `apply_faults_arrow`; the body delegates to `open_fdd.arrow_runtime.datafusion_backend`. Metadata:

```yaml
backend: datafusion_sql
fault_column: fault
sql: |
  SELECT *, "stat_zn-t" > 76.0 AS fault FROM telemetry
```

Same `ArrowRuleResult` after SQL execution and confirmation.

## Lint & forbidden imports

Edge fault rules allow: `pyarrow`, `pyarrow.compute`, `open_fdd.arrow_runtime.*`, `datetime`, `math`.

Forbidden in production fault rules: `pandas`, `numpy` (for rule logic), file I/O, network calls.

See `lint_arrow_rule()` in `open_fdd.arrow_runtime.backend`.

## Chunked execution

Large tables may run via `run_arrow_rule_chunked()` — masks are concatenated; contract unchanged.

## Related

- [Data types & units]({{ "/rule-authoring/data-types-and-units/" | relative_url }})
- [ADR: Rust-ready Arrow FDD contract]({{ "/adr/adr-rust-ready-arrow-fdd-contract/" | relative_url }})
- [Developer: Arrow-native runtime]({{ "/developer/arrow-native-runtime/" | relative_url }})
