//! Bounded and streaming SQL execution helpers for interactive callers.
//!
//! Rule/batch execution keeps its existing compatibility path in `session`.
//! Interactive APIs should either cap materialized rows with
//! [`collect_sql_bounded`] / [`collect_sql_budgeted`] or consume Arrow record
//! batches from [`stream_sql`] rather than calling `DataFrame::collect` on an
//! unbounded result.

use std::env;

use anyhow::{anyhow, bail, Result};
use datafusion::arrow::record_batch::RecordBatch;
use datafusion::physical_plan::SendableRecordBatchStream;
use datafusion::prelude::SessionContext;
use futures::StreamExt;

pub const DEFAULT_INTERACTIVE_MAX_ROWS: usize = 10_000;
/// Default interactive/result materialization byte budget (#1127 P2).
pub const DEFAULT_RESULT_MAX_BYTES: usize = 64 * 1024 * 1024;

/// Resolve `OPENFDD_RESULT_MAX_BYTES` (bytes) with a safe default.
pub fn result_max_bytes_from_env() -> Result<usize> {
    match env::var("OPENFDD_RESULT_MAX_BYTES") {
        Ok(raw) => {
            let n: usize = raw
                .trim()
                .parse()
                .map_err(|_| anyhow!("OPENFDD_RESULT_MAX_BYTES must be a positive integer"))?;
            if n == 0 {
                bail!("OPENFDD_RESULT_MAX_BYTES must be greater than zero");
            }
            Ok(n)
        }
        Err(_) => Ok(DEFAULT_RESULT_MAX_BYTES),
    }
}

/// Per-run materialization ceiling: min(result max, `OPENFDD_QUERY_MEMORY_MB`).
///
/// This enforces the advertised query envelope on retained Arrow output stages
/// (M70-03). DataFusion operator intermediates remain under the shared
/// FairSpillPool; a dedicated per-run pool limiter is still residual.
pub fn query_stage_max_bytes_from_env() -> Result<usize> {
    let result_max = result_max_bytes_from_env()?;
    match env::var("OPENFDD_QUERY_MEMORY_MB") {
        Ok(raw) => {
            let mb: u64 = raw
                .trim()
                .parse()
                .map_err(|_| anyhow!("OPENFDD_QUERY_MEMORY_MB must be a positive integer"))?;
            if mb == 0 {
                bail!("OPENFDD_QUERY_MEMORY_MB must be greater than zero");
            }
            let query_bytes = usize::try_from(mb.saturating_mul(1024 * 1024))
                .map_err(|_| anyhow!("OPENFDD_QUERY_MEMORY_MB exceeds platform address space"))?;
            Ok(result_max.min(query_bytes))
        }
        Err(_) => Ok(result_max),
    }
}

/// Execute SQL as an Arrow record-batch stream without materializing the full
/// result set in Open-FDD.
pub async fn stream_sql(ctx: &SessionContext, sql: &str) -> Result<SendableRecordBatchStream> {
    let df = ctx.sql(sql).await?;
    Ok(df.execute_stream().await?)
}

/// Materialize at most `max_rows` rows for an interactive response.
///
/// The query is wrapped in a DataFusion limit of `max_rows + 1`, allowing the
/// caller to distinguish an exact fit from truncation without collecting an
/// arbitrarily large result. Callers that genuinely need larger results should
/// narrow/aggregate the query or consume [`stream_sql`].
pub async fn collect_sql_bounded(
    ctx: &SessionContext,
    sql: &str,
    max_rows: usize,
) -> Result<Vec<RecordBatch>> {
    let max_bytes = query_stage_max_bytes_from_env()?;
    collect_sql_budgeted(ctx, sql, max_rows, max_bytes).await
}

/// Stream-materialize SQL with hard row **and** Arrow byte budgets.
///
/// Exceeding either budget fails closed (no silent truncation of fault coverage).
pub async fn collect_sql_budgeted(
    ctx: &SessionContext,
    sql: &str,
    max_rows: usize,
    max_bytes: usize,
) -> Result<Vec<RecordBatch>> {
    if max_rows == 0 {
        bail!("SQL row budget must be greater than zero");
    }
    if max_bytes == 0 {
        bail!("SQL byte budget must be greater than zero");
    }
    let probe_limit = max_rows
        .checked_add(1)
        .ok_or_else(|| anyhow!("SQL row budget is too large"))?;
    let df = ctx.sql(sql).await?.limit(0, Some(probe_limit))?;
    let mut stream = df.execute_stream().await?;
    let mut batches = Vec::new();
    let mut rows = 0usize;
    let mut bytes = 0usize;
    while let Some(next) = stream.next().await {
        let batch = next?;
        let batch_rows = batch.num_rows();
        let batch_bytes = batch.get_array_memory_size();
        rows = rows.saturating_add(batch_rows);
        bytes = bytes.saturating_add(batch_bytes);
        if bytes > max_bytes {
            bail!(
                "SQL result exceeds per-run stage byte budget of {max_bytes} (OPENFDD_RESULT_MAX_BYTES / OPENFDD_QUERY_MEMORY_MB); narrow the query — refusing silent truncation"
            );
        }
        if rows > max_rows {
            bail!(
                "SQL result exceeds row limit of {max_rows}; add filters/aggregation or use stream_sql"
            );
        }
        batches.push(batch);
    }
    Ok(batches)
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use datafusion::arrow::array::Int64Array;
    use datafusion::arrow::datatypes::{DataType, Field, Schema};
    use datafusion::arrow::record_batch::RecordBatch;
    use datafusion::prelude::SessionContext;

    use super::*;

    fn register_three_rows(ctx: &SessionContext) {
        let schema = Arc::new(Schema::new(vec![Field::new(
            "value",
            DataType::Int64,
            false,
        )]));
        let batch =
            RecordBatch::try_new(schema, vec![Arc::new(Int64Array::from(vec![1_i64, 2, 3]))])
                .unwrap();
        ctx.register_batch("samples", batch).unwrap();
    }

    #[tokio::test]
    async fn bounded_collection_rejects_results_above_limit() {
        let ctx = SessionContext::new();
        register_three_rows(&ctx);

        let error = collect_sql_bounded(&ctx, "SELECT * FROM samples", 2)
            .await
            .unwrap_err()
            .to_string();
        assert!(
            error.contains("row limit of 2"),
            "unexpected error: {error}"
        );

        let batches = collect_sql_bounded(&ctx, "SELECT * FROM samples", 3)
            .await
            .unwrap();
        assert_eq!(batches.iter().map(RecordBatch::num_rows).sum::<usize>(), 3);
    }

    #[tokio::test]
    async fn streaming_contract_returns_arrow_stream() {
        let ctx = SessionContext::new();
        register_three_rows(&ctx);
        let _stream = stream_sql(&ctx, "SELECT value FROM samples ORDER BY value")
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn byte_budget_fails_closed_without_silent_truncation() {
        let ctx = SessionContext::new();
        register_three_rows(&ctx);
        let err = collect_sql_budgeted(&ctx, "SELECT * FROM samples", 100, 1)
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("byte budget"), "unexpected error: {err}");
    }
}
