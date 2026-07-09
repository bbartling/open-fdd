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

/// Register weather sidecar Parquet (`parquet_root/weather/**/*.parquet`) when present.
pub async fn register_weather_if_present(
    ctx: &SessionContext,
    parquet_root: &Path,
) -> Result<bool> {
    let weather_dir = parquet_root.join("weather");
    if !weather_dir.is_dir() {
        return Ok(false);
    }
    let glob = weather_dir.join("**/*.parquet");
    let glob_str = glob.to_string_lossy().to_string();
    match ctx
        .register_parquet("weather", glob_str.as_str(), ParquetReadOptions::default())
        .await
    {
        Ok(_) => Ok(true),
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
