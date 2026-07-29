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

pub async fn run_sql(ctx: &SessionContext, sql: &str) -> Result<QueryResult> {
    let started = std::time::Instant::now();
    let df = ctx.sql(sql).await?;
    let batches = df.collect().await?;
    let mut rows = Vec::new();
    let mut columns = Vec::new();
    for batch in &batches {
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
    Ok(QueryResult {
        row_count: rows.len(),
        columns,
        rows,
        elapsed_ms: started.elapsed().as_millis(),
    })
}

pub async fn run_sql_file(ctx: &SessionContext, path: &Path) -> Result<QueryResult> {
    let sql = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    run_sql(ctx, &sql).await
}

fn format_cell(col: &datafusion::arrow::array::ArrayRef, idx: usize) -> serde_json::Value {
    use datafusion::arrow::array::*;
    if col.is_null(idx) {
        return serde_json::Value::Null;
    }
    match col.data_type() {
        datafusion::arrow::datatypes::DataType::Utf8 => {
            let a = col.as_any().downcast_ref::<StringArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        datafusion::arrow::datatypes::DataType::Utf8View => {
            let a = col.as_any().downcast_ref::<StringViewArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        datafusion::arrow::datatypes::DataType::LargeUtf8 => {
            let a = col.as_any().downcast_ref::<LargeStringArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        datafusion::arrow::datatypes::DataType::Float64 => {
            let a = col.as_any().downcast_ref::<Float64Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        datafusion::arrow::datatypes::DataType::Int64 => {
            let a = col.as_any().downcast_ref::<Int64Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        datafusion::arrow::datatypes::DataType::Boolean => {
            let a = col.as_any().downcast_ref::<BooleanArray>().unwrap();
            serde_json::json!(a.value(idx))
        }
        _ => serde_json::Value::String(format!("{:?}", col.slice(idx, 1))),
    }
}
