//! Dataset registry and Arrow IPC persistence.

use crate::csv_ingest::plan::OutputRow;
use arrow::array::{BooleanArray, Float64Array, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::ipc::writer::FileWriter;
use arrow::record_batch::RecordBatch;
use chrono::Utc;
use datafusion::prelude::*;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

pub fn datasets_root() -> PathBuf {
    crate::historian::store::workspace_dir().join("data/datasets")
}

pub fn registry_path() -> PathBuf {
    datasets_root().join("registry.json")
}

pub fn dataset_dir(id: &str) -> PathBuf {
    datasets_root().join(sanitize_id(id))
}

fn sanitize_id(id: &str) -> String {
    id.chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect()
}

pub fn load_registry() -> Value {
    let path = registry_path();
    if !path.exists() {
        return json!({"ok": true, "datasets": []});
    }
    fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| json!({"ok": true, "datasets": []}))
}

fn save_registry(reg: &Value) -> Result<(), String> {
    fs::create_dir_all(datasets_root()).map_err(|e| e.to_string())?;
    fs::write(
        registry_path(),
        serde_json::to_string_pretty(reg).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

pub fn list_datasets() -> Value {
    let reg = load_registry();
    json!({
        "ok": true,
        "datasets": reg.get("datasets").cloned().unwrap_or(json!([]))
    })
}

pub fn rows_to_batch(rows: &[OutputRow], value_keys: &[String]) -> Result<RecordBatch, String> {
    let mut fields = vec![
        Field::new(
            "ts_utc",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            true,
        ),
        Field::new("ts_local", DataType::Utf8, false),
        Field::new("timezone", DataType::Utf8, false),
        Field::new("source_timestamp_raw", DataType::Utf8, false),
        Field::new("source_timestamp_parse_status", DataType::Utf8, false),
        Field::new("source_timestamp_fold", DataType::Utf8, true),
        Field::new("source_file", DataType::Utf8, false),
        Field::new("source_row_number", DataType::UInt64, false),
        Field::new("fill_created", DataType::Boolean, false),
    ];
    for k in value_keys {
        fields.push(Field::new(k, DataType::Utf8, true));
    }
    let schema = Arc::new(Schema::new(fields));
    let n = rows.len();

    let ts_utc: TimestampMillisecondArray = rows
        .iter()
        .map(|r| r.ts_utc.map(|u| u.timestamp_millis()))
        .collect();
    let ts_local: StringArray = rows.iter().map(|r| Some(r.ts_local.as_str())).collect();
    let timezone: StringArray = rows.iter().map(|r| Some(r.timezone.as_str())).collect();
    let raw: StringArray = rows
        .iter()
        .map(|r| Some(r.source_timestamp_raw.as_str()))
        .collect();
    let status: StringArray = rows
        .iter()
        .map(|r| Some(r.source_timestamp_parse_status.as_str()))
        .collect();
    let fold: StringArray = rows
        .iter()
        .map(|r| r.source_timestamp_fold.as_deref())
        .collect();
    let source_file: StringArray = rows.iter().map(|r| Some(r.source_file.as_str())).collect();
    let source_row: arrow::array::UInt64Array =
        rows.iter().map(|r| Some(r.source_row_number)).collect();
    let fill_created: BooleanArray = rows.iter().map(|r| Some(r.fill_created)).collect();

    let mut arrays: Vec<Arc<dyn arrow::array::Array>> = vec![
        Arc::new(ts_utc),
        Arc::new(ts_local),
        Arc::new(timezone),
        Arc::new(raw),
        Arc::new(status),
        Arc::new(fold),
        Arc::new(source_file),
        Arc::new(source_row),
        Arc::new(fill_created),
    ];
    for k in value_keys {
        let col: StringArray = rows
            .iter()
            .map(|r| r.values.get(k).map(|s| s.as_str()))
            .collect();
        arrays.push(Arc::new(col));
    }

    RecordBatch::try_new(schema, arrays).map_err(|e| e.to_string())
}

pub fn save_dataset(
    dataset_id: &str,
    rows: &[OutputRow],
    validation_report: &Value,
    metadata_extra: &Value,
) -> Result<Value, String> {
    let id = sanitize_id(dataset_id);
    if id.is_empty() {
        return Err("invalid dataset id".into());
    }
    let dir = dataset_dir(&id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;

    let mut value_keys: Vec<String> = rows.iter().flat_map(|r| r.values.keys().cloned()).collect();
    value_keys.sort();
    value_keys.dedup();

    let batch = rows_to_batch(rows, &value_keys)?;
    let arrow_path = dir.join("data.arrow");
    let file = fs::File::create(&arrow_path).map_err(|e| e.to_string())?;
    let mut writer = FileWriter::try_new(file, &batch.schema()).map_err(|e| e.to_string())?;
    writer.write(&batch).map_err(|e| e.to_string())?;
    writer.finish().map_err(|e| e.to_string())?;

    let time_min = rows.iter().filter_map(|r| r.ts_utc).min();
    let time_max = rows.iter().filter_map(|r| r.ts_utc).max();

    let metadata = json!({
        "id": id,
        "row_count": rows.len(),
        "column_names": batch.schema().fields().iter().map(|f| f.name().clone()).collect::<Vec<_>>(),
        "value_columns": value_keys,
        "time_range": {
            "start": time_min.map(|u| u.to_rfc3339()),
            "end": time_max.map(|u| u.to_rfc3339()),
        },
        "arrow_path": arrow_path.display().to_string(),
        "created_at": Utc::now().to_rfc3339(),
        "extra": metadata_extra,
    });
    fs::write(
        dir.join("metadata.json"),
        serde_json::to_string_pretty(&metadata).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())?;
    fs::write(
        dir.join("validation_report.json"),
        serde_json::to_string_pretty(validation_report).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())?;

    let mut reg = load_registry();
    let datasets = reg
        .as_object_mut()
        .and_then(|o| o.get_mut("datasets"))
        .and_then(|d| d.as_array_mut())
        .ok_or("registry corrupt")?;
    datasets.retain(|d| d.get("id").and_then(|v| v.as_str()) != Some(id.as_str()));
    datasets.push(metadata.clone());
    save_registry(&reg)?;

    // Register Haystack model columns from value keys
    register_haystack_from_dataset(&id, &value_keys);

    Ok(json!({
        "ok": true,
        "dataset": metadata,
        "validation_report": validation_report,
    }))
}

fn register_haystack_from_dataset(dataset_id: &str, columns: &[String]) {
    let filename = format!("{dataset_id}.csv");
    let headers: Vec<String> = std::iter::once("timestamp".into())
        .chain(columns.iter().cloned())
        .collect();
    let job_id = format!("dataset-{dataset_id}");
    let _ = crate::model::csv_import::import_from_csv_commit(&headers, &filename, &job_id, None);
}

pub fn preview_dataset(dataset_id: &str, offset: u64, limit: u64) -> Value {
    let id = sanitize_id(dataset_id);
    let meta_path = dataset_dir(&id).join("metadata.json");
    if !meta_path.exists() {
        return json!({"ok": false, "error": "dataset not found"});
    }
    let meta: Value = fs::read_to_string(meta_path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(json!({}));
    let arrow_path = dataset_dir(&id).join("data.arrow");
    match read_arrow_page(&arrow_path, offset, limit) {
        Ok(rows) => json!({
            "ok": true,
            "dataset_id": id,
            "metadata": meta,
            "offset": offset,
            "limit": limit,
            "rows": rows,
        }),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

fn read_arrow_page(path: &PathBuf, offset: u64, limit: u64) -> Result<Vec<Value>, String> {
    use arrow::ipc::reader::FileReader;
    let file = fs::File::open(path).map_err(|e| e.to_string())?;
    let reader = FileReader::try_new(file, None).map_err(|e| e.to_string())?;
    let mut rows = Vec::new();
    let mut idx = 0u64;
    for batch in reader {
        let batch = batch.map_err(|e| e.to_string())?;
        for row_idx in 0..batch.num_rows() {
            if idx < offset {
                idx += 1;
                continue;
            }
            if rows.len() as u64 >= limit {
                return Ok(rows);
            }
            let mut obj = serde_json::Map::new();
            for (col_idx, field) in batch.schema().fields().iter().enumerate() {
                let col = batch.column(col_idx);
                let val = arrow_cell_json(col, row_idx);
                obj.insert(field.name().clone(), val);
            }
            rows.push(Value::Object(obj));
            idx += 1;
        }
    }
    Ok(rows)
}

fn arrow_cell_json(col: &Arc<dyn arrow::array::Array>, row: usize) -> Value {
    use arrow::array::*;
    if col.is_null(row) {
        return Value::Null;
    }
    match col.data_type() {
        DataType::Utf8 => {
            let a = col.as_any().downcast_ref::<StringArray>().unwrap();
            json!(a.value(row))
        }
        DataType::Float64 => {
            let a = col.as_any().downcast_ref::<Float64Array>().unwrap();
            json!(a.value(row))
        }
        DataType::Boolean => {
            let a = col.as_any().downcast_ref::<BooleanArray>().unwrap();
            json!(a.value(row))
        }
        DataType::Timestamp(_, _) => {
            let a = col
                .as_any()
                .downcast_ref::<TimestampMillisecondArray>()
                .unwrap();
            json!(a.value(row))
        }
        _ => json!(null),
    }
}

pub fn query_dataset_sql(dataset_id: &str, sql: &str) -> Value {
    let id = sanitize_id(dataset_id);
    let arrow_path = dataset_dir(&id).join("data.arrow");
    if !arrow_path.exists() {
        return json!({"ok": false, "error": "dataset not found"});
    }
    let rt = tokio::runtime::Runtime::new().expect("tokio");
    match rt.block_on(query_arrow_file(&arrow_path, sql, &id)) {
        Ok(rows) => json!({"ok": true, "rows": rows, "row_count": rows.len()}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

async fn query_arrow_file(path: &PathBuf, sql: &str, table: &str) -> Result<Vec<Value>, String> {
    use arrow::ipc::reader::FileReader;
    let file = fs::File::open(path).map_err(|e| e.to_string())?;
    let reader = FileReader::try_new(file, None).map_err(|e| e.to_string())?;
    let mut batches: Vec<RecordBatch> = Vec::new();
    for b in reader {
        batches.push(b.map_err(|e| e.to_string())?);
    }
    if batches.is_empty() {
        return Ok(Vec::new());
    }
    let ctx = SessionContext::new();
    let schema = batches[0].schema();
    let combined = arrow::compute::concat_batches(&schema, &batches).map_err(|e| e.to_string())?;
    ctx.register_batch(table, combined)
        .map_err(|e| e.to_string())?;
    let df = ctx.sql(sql).await.map_err(|e| e.to_string())?;
    let out = df.collect().await.map_err(|e| e.to_string())?;
    let mut rows = Vec::new();
    for batch in out {
        for row_idx in 0..batch.num_rows() {
            let mut obj = serde_json::Map::new();
            for (col_idx, field) in batch.schema().fields().iter().enumerate() {
                obj.insert(
                    field.name().clone(),
                    arrow_cell_json(batch.column(col_idx), row_idx),
                );
            }
            rows.push(Value::Object(obj));
        }
    }
    Ok(rows)
}

pub fn delete_dataset(dataset_id: &str) -> Result<(), String> {
    let id = sanitize_id(dataset_id);
    let dir = dataset_dir(&id);
    if dir.exists() {
        fs::remove_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mut reg = load_registry();
    if let Some(arr) = reg.get_mut("datasets").and_then(|d| d.as_array_mut()) {
        arr.retain(|d| d.get("id").and_then(|v| v.as_str()) != Some(id.as_str()));
        save_registry(&reg)?;
    }
    Ok(())
}
