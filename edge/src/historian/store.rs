//! Append-only bench historian backed by JSONL + Arrow IPC snapshot.
//!
//! Production direction: Feather/Parquet files under `workspace/data/historian/`.

use arrow::array::{Float64Array, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::ipc::writer::FileWriter;
use arrow::record_batch::RecordBatch;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;

pub fn historian_subdir() -> String {
    std::env::var("OPENFDD_HISTORIAN_SUBDIR")
        .unwrap_or_else(|_| crate::validation::profile::active_profile().historian_subdir)
}

pub fn bench_dir() -> PathBuf {
    workspace_dir()
        .join("data/historian")
        .join(historian_subdir())
}

pub fn pivot_jsonl_path() -> PathBuf {
    bench_dir().join("telemetry_pivot.jsonl")
}

pub fn arrow_ipc_path() -> PathBuf {
    bench_dir().join("telemetry_pivot.arrow")
}

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn ensure_dir() {
    let _ = fs::create_dir_all(bench_dir());
}

pub fn append_pivot_row(row: &Value) -> Result<(), String> {
    ensure_dir();
    let path = pivot_jsonl_path();
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    let line = serde_json::to_string(row).map_err(|e| e.to_string())?;
    writeln!(file, "{line}").map_err(|e| e.to_string())?;
    if let Ok(rows) = load_pivot_rows() {
        let _ = write_arrow_ipc(&rows);
    }
    Ok(())
}

pub fn load_pivot_rows() -> Result<Vec<Value>, String> {
    let path = pivot_jsonl_path();
    if !path.exists() {
        return Ok(Vec::new());
    }
    let text = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut rows = Vec::new();
    for line in text.lines() {
        if line.trim().is_empty() {
            continue;
        }
        if let Ok(v) = serde_json::from_str::<Value>(line) {
            rows.push(v);
        }
    }
    Ok(rows)
}

pub fn row_count() -> usize {
    load_pivot_rows().map(|r| r.len()).unwrap_or(0)
}

pub fn last_sample_at() -> Option<String> {
    load_pivot_rows()
        .ok()
        .and_then(|rows| rows.last().cloned())
        .and_then(|r| {
            r.get("timestamp")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
}

pub fn clear_rows_with_source_prefix(prefix: &str) -> Result<usize, String> {
    let rows = load_pivot_rows()?;
    let before = rows.len();
    let kept: Vec<Value> = rows
        .into_iter()
        .filter(|r| {
            r.get("source")
                .and_then(|v| v.as_str())
                .map(|s| !s.starts_with(prefix))
                .unwrap_or(true)
        })
        .collect();
    let removed = before.saturating_sub(kept.len());
    rewrite_all(&kept)?;
    Ok(removed)
}

pub fn rewrite_all(rows: &[Value]) -> Result<(), String> {
    ensure_dir();
    let path = pivot_jsonl_path();
    if rows.is_empty() {
        if path.exists() {
            fs::remove_file(&path).map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    for row in rows {
        let line = serde_json::to_string(row).map_err(|e| e.to_string())?;
        writeln!(file, "{line}").map_err(|e| e.to_string())?;
    }
    write_arrow_ipc(rows)?;
    Ok(())
}

pub fn write_arrow_ipc(rows: &[Value]) -> Result<(), String> {
    let batch = pivot_rows_to_batch(rows)?;
    let path = arrow_ipc_path();
    let file = fs::File::create(&path).map_err(|e| e.to_string())?;
    let mut writer = FileWriter::try_new(file, &batch.schema()).map_err(|e| e.to_string())?;
    writer.write(&batch).map_err(|e| e.to_string())?;
    writer.finish().map_err(|e| e.to_string())?;
    Ok(())
}

pub fn pivot_rows_to_batch(rows: &[Value]) -> Result<RecordBatch, String> {
    let schema = pivot_schema();
    if rows.is_empty() {
        return Ok(RecordBatch::new_empty(Arc::new(schema)));
    }
    let mut ts = Vec::new();
    let mut equip = Vec::new();
    let mut oat = Vec::new();
    let mut oah = Vec::new();
    let mut duct = Vec::new();
    let mut zn = Vec::new();
    for row in rows {
        ts.push(parse_ts_ms(
            row.get("timestamp").and_then(|v| v.as_str()).unwrap_or(""),
        ));
        equip.push(
            row.get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("5007")
                .to_string(),
        );
        oat.push(row.get("oa_t").and_then(|v| v.as_f64()));
        oah.push(row.get("oa_h").and_then(|v| v.as_f64()));
        duct.push(row.get("duct_t").and_then(|v| v.as_f64()));
        zn.push(row.get("zn_t").and_then(|v| v.as_f64()));
    }
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(TimestampMillisecondArray::from(ts)),
            Arc::new(StringArray::from(equip)),
            Arc::new(Float64Array::from(oat)),
            Arc::new(Float64Array::from(oah)),
            Arc::new(Float64Array::from(vec![None; rows.len()])),
            Arc::new(Float64Array::from(duct)),
            Arc::new(Float64Array::from(zn)),
            Arc::new(Float64Array::from(vec![None; rows.len()])),
            Arc::new(Float64Array::from(vec![Some(1.0); rows.len()])),
            Arc::new(Float64Array::from(vec![None; rows.len()])),
        ],
    )
    .map_err(|e| e.to_string())
}

fn pivot_schema() -> Schema {
    Schema::new(vec![
        Field::new(
            "timestamp",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new("equipment_id", DataType::Utf8, false),
        Field::new("oa_t", DataType::Float64, true),
        Field::new("oa_h", DataType::Float64, true),
        Field::new("sat", DataType::Float64, true),
        Field::new("duct_t", DataType::Float64, true),
        Field::new("zn_t", DataType::Float64, true),
        Field::new("sat_sp", DataType::Float64, true),
        Field::new("fan_cmd", DataType::Float64, true),
        Field::new("occ", DataType::Float64, true),
    ])
}

pub fn parse_ts_ms(s: &str) -> i64 {
    DateTime::parse_from_rfc3339(s)
        .map(|dt| dt.with_timezone(&Utc).timestamp_millis())
        .unwrap_or_else(|_| Utc::now().timestamp_millis())
}

pub fn make_pivot_row(
    timestamp: &str,
    equipment_id: &str,
    oa_t: f64,
    oa_h: f64,
    duct_t: f64,
    zn_t: f64,
    source: &str,
    source_driver: &str,
    is_simulated: bool,
) -> Value {
    json!({
        "timestamp": timestamp,
        "equipment_id": equipment_id,
        "oa_t": oa_t,
        "oa_h": oa_h,
        "duct_t": duct_t,
        "zn_t": zn_t,
        "source": source,
        "source_driver": source_driver,
        "is_simulated": is_simulated
    })
}

pub fn status_json() -> Value {
    json!({
        "ok": true,
        "historian_path": bench_dir().display().to_string(),
        "jsonl": pivot_jsonl_path().display().to_string(),
        "arrow_ipc": arrow_ipc_path().display().to_string(),
        "row_count": row_count(),
        "last_sample_at": last_sample_at()
    })
}
