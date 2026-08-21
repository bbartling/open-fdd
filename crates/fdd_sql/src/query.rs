//! Bounded and streaming SQL execution helpers for interactive callers.
//!
//! Rule/batch execution keeps its existing compatibility path in `session`.
//! Interactive APIs should either cap materialized rows with
//! [`collect_sql_bounded`] or consume Arrow record batches from [`stream_sql`]
//! rather than calling `DataFrame::collect` on an unbounded result.

use anyhow::{anyhow, bail, Result};
use datafusion::arrow::record_batch::RecordBatch;
use datafusion::physical_plan::SendableRecordBatchStream;
use datafusion::prelude::SessionContext;

pub const DEFAULT_INTERACTIVE_MAX_ROWS: usize = 10_000;

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
    if max_rows == 0 {
        bail!("interactive SQL row limit must be greater than zero");
    }
    let probe_limit = max_rows
        .checked_add(1)
        .ok_or_else(|| anyhow!("interactive SQL row limit is too large"))?;
    let df = ctx.sql(sql).await?.limit(0, Some(probe_limit))?;
    let batches = df.collect().await?;
    let rows = batches.iter().map(RecordBatch::num_rows).sum::<usize>();
    if rows > max_rows {
        bail!(
            "interactive SQL result exceeds row limit of {max_rows}; add filters/aggregation or use stream_sql"
        );
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
}
