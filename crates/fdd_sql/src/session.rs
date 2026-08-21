use std::path::Path;

use anyhow::{Context, Result};
use datafusion::prelude::*;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct QueryResult {
    pub row_count: usize,
    pub columns: Vec<String>,
    pub rows: Vec<serde_json::Value>,
    pub elapsed_ms: u128,
}

pub async fn register_parquet_tree(ctx: &SessionContext, parquet_root: &Path) -> Result<usize> {
    let glob = parquet_root.join("**/*.parquet");
    let glob_str = glob.to_string_lossy().to_string();
    ctx.register_parquet("history", glob_str.as_str(), ParquetReadOptions::default())
        .await
        .with_context(|| format!("register history from {}", glob_str))?;
    Ok(1)
}

/// Register a `weather` table for weather-referencing rules (e.g. OAT-METEO).
///
/// Preference order (OFDD-068):
/// 1. `parquet_root/weather/**/*.parquet` sidecar, when present.
/// 2. Fallback SQL view over `history` rows whose `equipment_id` looks like a
///    weather station (`ILIKE '%weather%'`/`'%meteo%'`/`'%oat%'`) — Liberty CSV
///    packages land weather as `equipment=weather` in history rather than a
///    sidecar, so without this the rule 413/crashes instead of running.
///
/// Returns `true` when a `weather` relation was registered by either path.
pub async fn register_weather_if_present(
    ctx: &SessionContext,
    parquet_root: &Path,
) -> Result<bool> {
    let weather_dir = parquet_root.join("weather");
    if weather_dir.is_dir() {
        let glob = weather_dir.join("**/*.parquet");
        let glob_str = glob.to_string_lossy().to_string();
        if ctx
            .register_parquet("weather", glob_str.as_str(), ParquetReadOptions::default())
            .await
            .is_ok()
        {
            return Ok(true);
        }
    }
    register_weather_view_from_history(ctx).await
}

/// Register a `weather` view from `history` weather-station rows. No-op (returns
/// `false`) when `history` is unregistered or holds no weather-like equipment.
async fn register_weather_view_from_history(ctx: &SessionContext) -> Result<bool> {
    if ctx.table("history").await.is_err() {
        return Ok(false);
    }
    let probe = "SELECT 1 FROM history \
        WHERE equipment_id ILIKE '%weather%' \
           OR equipment_id ILIKE '%meteo%' \
           OR equipment_id ILIKE '%oat%' \
        LIMIT 1";
    let has_weather = match ctx.sql(probe).await {
        Ok(df) => match df.collect().await {
            Ok(batches) => batches.iter().any(|b| b.num_rows() > 0),
            Err(_) => false,
        },
        Err(_) => false,
    };
    if !has_weather {
        return Ok(false);
    }
    let create = "CREATE OR REPLACE VIEW weather AS \
        SELECT * FROM history \
        WHERE equipment_id ILIKE '%weather%' \
           OR equipment_id ILIKE '%meteo%' \
           OR equipment_id ILIKE '%oat%'";
    match ctx.sql(create).await {
        Ok(df) => {
            let _ = df.collect().await;
            Ok(ctx.table("weather").await.is_ok())
        }
        Err(_) => Ok(false),
    }
}

/// Execute SQL and materialize the complete result for compatibility callers.
/// Interactive callers should prefer [`run_sql_bounded`] or the Arrow streaming
/// helpers in `crate::query`.
pub async fn run_sql(ctx: &SessionContext, sql: &str) -> Result<QueryResult> {
    let started = std::time::Instant::now();
    let df = ctx.sql(sql).await?;
    let batches = df.collect().await?;
    Ok(query_result_from_batches(&batches, started))
}

/// Execute SQL with a hard materialized-row limit for interactive callers.
pub async fn run_sql_bounded(
    ctx: &SessionContext,
    sql: &str,
    max_rows: usize,
) -> Result<QueryResult> {
    let started = std::time::Instant::now();
    let batches = crate::query::collect_sql_bounded(ctx, sql, max_rows).await?;
    Ok(query_result_from_batches(&batches, started))
}

/// Read a SQL file and execute it through the compatibility unbounded path.
pub async fn run_sql_file(ctx: &SessionContext, path: &Path) -> Result<QueryResult> {
    let sql = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    run_sql(ctx, &sql).await
}

/// Read a SQL file and execute it with a hard materialized-row limit.
pub async fn run_sql_file_bounded(
    ctx: &SessionContext,
    path: &Path,
    max_rows: usize,
) -> Result<QueryResult> {
    let sql = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    run_sql_bounded(ctx, &sql, max_rows).await
}

/// Convert collected Arrow batches into the stable JSON-facing query result.
fn query_result_from_batches(
    batches: &[datafusion::arrow::record_batch::RecordBatch],
    started: std::time::Instant,
) -> QueryResult {
    let mut rows = Vec::new();
    let mut columns = Vec::new();
    for batch in batches {
        let schema = batch.schema();
        if columns.is_empty() {
            columns = schema.fields().iter().map(|f| f.name().clone()).collect();
        }
        for row_idx in 0..batch.num_rows() {
            let mut obj = serde_json::Map::new();
            for (col_idx, field) in schema.fields().iter().enumerate() {
                let col = batch.column(col_idx);
                let val = format_cell(col, row_idx);
                obj.insert(field.name().clone(), val);
            }
            rows.push(serde_json::Value::Object(obj));
        }
    }
    QueryResult {
        row_count: rows.len(),
        columns,
        rows,
        elapsed_ms: started.elapsed().as_millis(),
    }
}

fn format_cell(col: &datafusion::arrow::array::ArrayRef, idx: usize) -> serde_json::Value {
    use chrono::{TimeZone, Utc};
    use datafusion::arrow::array::*;
    use datafusion::arrow::datatypes::{DataType, TimeUnit};
    if col.is_null(idx) {
        return serde_json::Value::Null;
    }
    match col.data_type() {
        DataType::Utf8 => {
            let a = col.as_any().downcast_ref::<StringArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        DataType::Utf8View => {
            let a = col.as_any().downcast_ref::<StringViewArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        DataType::LargeUtf8 => {
            let a = col.as_any().downcast_ref::<LargeStringArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        DataType::Float64 => {
            let a = col.as_any().downcast_ref::<Float64Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Float32 => {
            let a = col.as_any().downcast_ref::<Float32Array>().unwrap();
            serde_json::json!(a.value(idx) as f64)
        }
        DataType::Int64 => {
            let a = col.as_any().downcast_ref::<Int64Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Int32 => {
            let a = col.as_any().downcast_ref::<Int32Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Boolean => {
            let a = col.as_any().downcast_ref::<BooleanArray>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Timestamp(unit, _) => {
            let nanos: i64 = match unit {
                TimeUnit::Second => col
                    .as_any()
                    .downcast_ref::<TimestampSecondArray>()
                    .map(|a| a.value(idx).saturating_mul(1_000_000_000))
                    .unwrap_or(0),
                TimeUnit::Millisecond => col
                    .as_any()
                    .downcast_ref::<TimestampMillisecondArray>()
                    .map(|a| a.value(idx).saturating_mul(1_000_000))
                    .unwrap_or(0),
                TimeUnit::Microsecond => col
                    .as_any()
                    .downcast_ref::<TimestampMicrosecondArray>()
                    .map(|a| a.value(idx).saturating_mul(1_000))
                    .unwrap_or(0),
                TimeUnit::Nanosecond => col
                    .as_any()
                    .downcast_ref::<TimestampNanosecondArray>()
                    .map(|a| a.value(idx))
                    .unwrap_or(0),
            };
            let secs = nanos.div_euclid(1_000_000_000);
            let nsec = nanos.rem_euclid(1_000_000_000) as u32;
            let dt = Utc
                .timestamp_opt(secs, nsec)
                .single()
                .unwrap_or_else(|| Utc.timestamp_opt(0, 0).unwrap());
            serde_json::Value::String(dt.to_rfc3339())
        }
        DataType::Date32 => {
            let a = col.as_any().downcast_ref::<Date32Array>().unwrap();
            let days = i64::from(a.value(idx));
            let dt = Utc
                .timestamp_opt(days.saturating_mul(86_400), 0)
                .single()
                .unwrap_or_else(|| Utc.timestamp_opt(0, 0).unwrap());
            serde_json::Value::String(dt.date_naive().to_string())
        }
        _ => {
            // Last resort: avoid Arrow Debug dumps (e.g. PrimitiveArray<…>) in JSON.
            serde_json::Value::Null
        }
    }
}