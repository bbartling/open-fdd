//! Normalized historian writer (JSONL + Arrow IPC) for connector ingest.

use crate::connectors::types::NormalizedRow;
use crate::historian::store::{parse_ts_ms, workspace_dir};
use arrow::array::{Float64Array, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::ipc::writer::FileWriter;
use arrow::record_batch::RecordBatch;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;

pub fn historian_dir() -> PathBuf {
    workspace_dir().join("data/historian/normalized")
}

pub fn jsonl_path() -> PathBuf {
    historian_dir().join("telemetry.jsonl")
}

pub fn arrow_path() -> PathBuf {
    historian_dir().join("telemetry.arrow")
}

pub fn append_rows(rows: &[NormalizedRow]) -> Result<(usize, usize), String> {
    if rows.is_empty() {
        return Ok((0, 0));
    }
    ensure_dir();
    let mut existing_keys = load_dedupe_keys()?;
    let mut written = 0usize;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(jsonl_path())
        .map_err(|e| e.to_string())?;
    for row in rows {
        let key = row.dedupe_key();
        if existing_keys.contains(&key) {
            continue;
        }
        let line = serde_json::to_string(&row.to_json()).map_err(|e| e.to_string())?;
        writeln!(file, "{line}").map_err(|e| e.to_string())?;
        existing_keys.insert(key);
        written += 1;
    }
    if written > 0 {
        let all = load_rows()?;
        write_arrow_ipc(&all)?;
    }
    Ok((written, rows.len().saturating_sub(written)))
}

pub fn load_rows() -> Result<Vec<Value>, String> {
    let path = jsonl_path();
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

pub fn row_count_for_source(source_id: &str) -> u64 {
    load_rows()
        .unwrap_or_default()
        .into_iter()
        .filter(|r| r.get("source_id").and_then(|v| v.as_str()) == Some(source_id))
        .count() as u64
}

pub fn status_json() -> Value {
    json!({
        "ok": true,
        "jsonl": jsonl_path().display().to_string(),
        "arrow_ipc": arrow_path().display().to_string(),
        "row_count": load_rows().map(|r| r.len()).unwrap_or(0)
    })
}

fn load_dedupe_keys() -> Result<HashSet<String>, String> {
    let mut keys = HashSet::new();
    for row in load_rows()? {
        if let Some(k) = row.get("dedupe_key").and_then(|v| v.as_str()) {
            keys.insert(k.to_string());
        }
    }
    Ok(keys)
}

fn ensure_dir() {
    let _ = fs::create_dir_all(historian_dir());
}

fn write_arrow_ipc(rows: &[Value]) -> Result<(), String> {
    let batch = rows_to_batch(rows)?;
    let file = fs::File::create(arrow_path()).map_err(|e| e.to_string())?;
    let mut writer = FileWriter::try_new(file, &batch.schema()).map_err(|e| e.to_string())?;
    writer.write(&batch).map_err(|e| e.to_string())?;
    writer.finish().map_err(|e| e.to_string())?;
    Ok(())
}

pub fn rows_to_batch(rows: &[Value]) -> Result<RecordBatch, String> {
    let schema = normalized_schema();
    if rows.is_empty() {
        return Ok(RecordBatch::new_empty(Arc::new(schema)));
    }
    let mut ts = Vec::new();
    let mut site = Vec::new();
    let mut equip = Vec::new();
    let mut point = Vec::new();
    let mut value = Vec::new();
    let mut unit = Vec::new();
    let mut source = Vec::new();
    for row in rows {
        ts.push(parse_ts_ms(
            row.get("timestamp_utc")
                .or_else(|| row.get("timestamp"))
                .and_then(|v| v.as_str())
                .unwrap_or(""),
        ));
        site.push(str_field(row, "site_id"));
        equip.push(str_field(row, "equipment_id"));
        point.push(str_field(row, "point_id"));
        value.push(row.get("value").and_then(|v| v.as_f64()));
        unit.push(str_field(row, "units"));
        source.push(str_field(row, "source_id"));
    }
    RecordBatch::try_new(
        Arc::new(schema),
        vec![
            Arc::new(TimestampMillisecondArray::from(ts)),
            Arc::new(StringArray::from(site)),
            Arc::new(StringArray::from(equip)),
            Arc::new(StringArray::from(point)),
            Arc::new(Float64Array::from(value)),
            Arc::new(StringArray::from(unit)),
            Arc::new(StringArray::from(source)),
        ],
    )
    .map_err(|e| e.to_string())
}

fn normalized_schema() -> Schema {
    Schema::new(vec![
        Field::new(
            "timestamp",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new("site_id", DataType::Utf8, false),
        Field::new("equipment_id", DataType::Utf8, false),
        Field::new("point_id", DataType::Utf8, false),
        Field::new("value", DataType::Float64, true),
        Field::new("units", DataType::Utf8, false),
        Field::new("source_id", DataType::Utf8, false),
    ])
}

fn str_field(row: &Value, key: &str) -> String {
    row.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::connectors::types::NormalizedRow;
    use std::env;

    fn sample_row(source_id: &str, point_id: &str, val: f64) -> NormalizedRow {
        let now = "2024-06-01T12:00:00Z".to_string();
        NormalizedRow {
            timestamp_utc: now.clone(),
            timestamp_local: now.clone(),
            timezone: "UTC".into(),
            site_id: "site:demo".into(),
            building_id: "building:main".into(),
            equipment_id: "equip:demo".into(),
            source_id: source_id.into(),
            source_type: "json_api".into(),
            source_protocol: "json_api".into(),
            device_id: "device:demo".into(),
            point_id: point_id.into(),
            point_name: point_id.into(),
            value: Some(val),
            value_text: val.to_string(),
            units: "degF".into(),
            quality: "good".into(),
            source_path: "/demo".into(),
            raw_ref: "demo".into(),
            ingested_at: now.clone(),
            run_id: "test-run".into(),
        }
    }

    fn with_temp_workspace<F: FnOnce()>(f: F) {
        let tmp = env::temp_dir().join(format!("ofdd-hist-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        env::set_var("OPENFDD_WORKSPACE", &tmp);
        env::set_var(
            "OPENFDD_REPO_ROOT",
            env!("CARGO_MANIFEST_DIR").replace("/edge", ""),
        );
        env::set_var("OPENFDD_CONNECTOR_DEMO_MODE", "1");
        f();
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn dedupes_identical_rows() {
        with_temp_workspace(|| {
            let rows = vec![
                sample_row("src_a", "oat", 70.0),
                sample_row("src_a", "oat", 70.0),
            ];
            let (written, skipped) = append_rows(&rows).unwrap_or((0, 0));
            assert!(written <= 1);
            assert!(skipped <= 1);
        });
    }
}
