//! Dataset registry and Arrow IPC persistence.

use crate::csv_ingest::plan::OutputRow;
use arrow::array::{BooleanArray, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::ipc::writer::FileWriter;
use arrow::record_batch::RecordBatch;
use chrono::Utc;
use datafusion::prelude::*;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
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
    let _row_count = rows.len();

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

    let historian_sync = sync_output_rows_to_historian(&id, rows);

    Ok(json!({
        "ok": true,
        "dataset": metadata,
        "validation_report": validation_report,
        "historian_sync": historian_sync,
        "plot_url": historian_sync.get("plot_url").cloned().unwrap_or(json!(null)),
        "model_url": historian_sync.get("model_url").cloned().unwrap_or(json!(null)),
    }))
}

/// Push merged CSV rows into historian pivot + refresh Haystack so Plot tab works.
pub fn sync_output_rows_to_historian(dataset_id: &str, rows: &[OutputRow]) -> Value {
    use crate::historian::store;
    use crate::model::csv_import::{apply_pivot_aliases, column_slug, ids_from_filename};

    let filename = format!("{dataset_id}.csv");
    let (default_site, default_equip, _, _) = ids_from_filename(&filename);
    let source_tag = format!("csv:{dataset_id}");
    let mut new_rows: Vec<Value> = Vec::new();
    for r in rows {
        let ts = r
            .ts_utc
            .map(|u| u.to_rfc3339())
            .unwrap_or_else(|| r.ts_local.clone());
        if ts.trim().is_empty() {
            continue;
        }
        let row_equip = r
            .values
            .get("equipment_id")
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .unwrap_or(default_equip.as_str());
        let row_site = r
            .values
            .get("site_id")
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .unwrap_or(default_site.as_str());
        let mut row = json!({
            "timestamp": ts,
            "equipment_id": row_equip,
            "site_id": row_site,
            "source": source_tag,
            "source_driver": "csv",
            "is_simulated": false
        });
        for (k, v) in &r.values {
            let lk = k.to_ascii_lowercase();
            if lk == "equipment_id" || lk == "site_id" {
                continue;
            }
            if v.trim().is_empty() {
                continue;
            }
            if let Ok(n) = v.parse::<f64>() {
                let slug = column_slug(k);
                row[slug.clone()] = json!(n);
                apply_pivot_aliases(&mut row, &slug, n);
            }
        }
        if row.as_object().map(|o| o.len()).unwrap_or(0) > 5 {
            new_rows.push(row);
        }
    }
    if new_rows.is_empty() {
        return json!({
            "ok": false,
            "error": "no numeric rows synced to historian",
            "site_id": default_site,
            "equipment_id": default_equip
        });
    }
    let mut all = store::load_pivot_rows().unwrap_or_default();
    all.retain(|r| {
        r.get("source")
            .and_then(|v| v.as_str())
            .is_none_or(|s| s != source_tag.as_str())
    });
    all.extend(new_rows.clone());
    match store::rewrite_all(&all) {
        Ok(()) => {
            let sync_site = new_rows
                .first()
                .and_then(|r| r.get("site_id").and_then(|v| v.as_str()))
                .unwrap_or(default_site.as_str());
            let sync_equip = new_rows
                .first()
                .and_then(|r| r.get("equipment_id").and_then(|v| v.as_str()))
                .unwrap_or(default_equip.as_str());
            json!({
                "ok": true,
                "rows_synced": new_rows.len(),
                "historian_total": all.len(),
                "site_id": sync_site,
                "equipment_id": sync_equip,
                "source_id": source_tag,
                "plot_url": format!("/plot?site={sync_site}&device={sync_equip}&hours=8760"),
                "model_url": format!("/model?site={sync_site}")
            })
        }
        Err(e) => json!({"ok": false, "error": e, "site_id": default_site}),
    }
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
            let a = col
                .as_any()
                .downcast_ref::<arrow::array::Float64Array>()
                .unwrap();
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
    // Package / Haystack building cleanup: csv_buildings, feather, parquet partition.
    let ws = crate::historian::store::workspace_dir();
    let csv_buildings = ws.join("data").join("csv_buildings").join(&id);
    // Collect equipment ids before wiping the package tree so session_config can be trimmed.
    let equipment_ids = list_equipment_dirs(&csv_buildings);
    crate::fdd::session_config::strip_site_from_session_config(&id, &equipment_ids)?;
    if csv_buildings.exists() {
        let _ = fs::remove_dir_all(&csv_buildings);
    }
    let _ = crate::historian::feather_store::remove_site("package", &id);
    let _ = crate::historian::feather_store::remove_site("csv", &id);
    let _ = crate::historian::feather_store::remove_site("mqtt", &id);
    let _ = crate::historian::feather_store::remove_site("modbus", &id);
    let parquet_roots = [
        std::env::var("OPENFDD_PARQUET_ROOT")
            .ok()
            .map(PathBuf::from),
        Some(ws.join(".cache/parquet")),
        Some(PathBuf::from(".cache/parquet")),
    ];
    for root in parquet_roots.into_iter().flatten() {
        let part = root.join(format!("building={id}"));
        if part.exists() {
            let _ = fs::remove_dir_all(&part);
        }
    }
    // OFDD-073: purge scoped FDD rule_results so DELETE site leaves no ghost FAULTs.
    let rule_results_roots = [
        std::env::var("OPENFDD_RULE_RESULTS_DIR")
            .ok()
            .map(PathBuf::from),
        Some(ws.join(".cache/rule_results")),
        Some(PathBuf::from(".cache/rule_results")),
    ];
    for root in rule_results_roots.into_iter().flatten() {
        let part = root.join(format!("building={id}"));
        if part.exists() {
            let _ = fs::remove_dir_all(&part);
        }
    }
    Ok(())
}

/// Best-effort equipment folder names under a materialized package building root.
fn list_equipment_dirs(building_root: &Path) -> Vec<String> {
    let mut ids = Vec::new();
    if !building_root.is_dir() {
        return ids;
    }
    for e in walkdir::WalkDir::new(building_root)
        .min_depth(1)
        .max_depth(3)
        .into_iter()
        .flatten()
    {
        if e.file_type().is_dir()
            && (e.path().join("history_wide.csv").is_file()
                || e.path().join("columns.csv").is_file())
        {
            if let Some(name) = e.file_name().to_str() {
                if name != "weather" {
                    ids.push(name.to_string());
                }
            }
        }
    }
    ids.sort();
    ids.dedup();
    ids
}

/// Register a package building id in the dataset registry (for Delete site by Haystack name).
pub fn register_package_dataset(
    building_id: &str,
    row_count: u64,
    equipment_count: usize,
    extra: &Value,
) -> Result<(), String> {
    let id = sanitize_id(building_id);
    if id.is_empty() {
        return Err("invalid building id".into());
    }
    let metadata = json!({
        "id": id,
        "row_count": row_count,
        "equipment_count": equipment_count,
        "source": "openfdd_package_v1",
        "created_at": Utc::now().to_rfc3339(),
        "extra": extra,
    });
    let mut reg = load_registry();
    let datasets = reg
        .as_object_mut()
        .and_then(|o| o.get_mut("datasets"))
        .and_then(|d| d.as_array_mut())
        .ok_or("registry corrupt")?;
    datasets.retain(|d| d.get("id").and_then(|v| v.as_str()) != Some(id.as_str()));
    datasets.push(metadata);
    save_registry(&reg)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    #[test]
    fn delete_dataset_purges_rule_results_building_partition() {
        let tmp = TempDir::new().unwrap();
        // isolate workspace + CWD-relative rule_results roots used by delete_dataset
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        let prev_cwd = std::env::current_dir().ok();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.path());
        std::env::set_current_dir(tmp.path()).unwrap();

        let id = "BUILDING_50";
        let results = tmp
            .path()
            .join(".cache/rule_results")
            .join(format!("building={id}"));
        fs::create_dir_all(&results).unwrap();
        let mut f = fs::File::create(results.join("SV-STALE.json")).unwrap();
        writeln!(f, "{{\"fault_hours\": 1.0}}").unwrap();

        let pq = tmp
            .path()
            .join(".cache/parquet")
            .join(format!("building={id}"));
        fs::create_dir_all(&pq).unwrap();
        fs::write(pq.join("marker"), b"x").unwrap();

        // also leave a sibling building so we prove scoped purge
        let keep = tmp
            .path()
            .join(".cache/rule_results")
            .join("building=BUILDING_100");
        fs::create_dir_all(&keep).unwrap();
        fs::write(keep.join("keep.json"), b"{}").unwrap();

        delete_dataset(id).expect("delete ok");
        assert!(!results.exists(), "BUILDING_50 rule_results must be purged");
        assert!(!pq.exists(), "BUILDING_50 parquet partition must be purged");
        assert!(keep.exists(), "BUILDING_100 rule_results must remain");

        if let Some(ws) = prev_ws {
            std::env::set_var("OPENFDD_WORKSPACE", ws);
        } else {
            std::env::remove_var("OPENFDD_WORKSPACE");
        }
        if let Some(cwd) = prev_cwd {
            let _ = std::env::set_current_dir(cwd);
        }
    }

    #[test]
    fn delete_dataset_purges_mqtt_and_modbus_feathers() {
        let tmp = TempDir::new().unwrap();
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.path());

        let id = "SITE_MQTT";
        for source in ["mqtt", "modbus", "package"] {
            let dir = crate::historian::feather_store::site_dir(source, id);
            fs::create_dir_all(&dir).unwrap();
            fs::write(dir.join("marker.feather"), b"x").unwrap();
            assert!(dir.exists());
        }

        delete_dataset(id).expect("delete ok");

        for source in ["mqtt", "modbus", "package"] {
            let dir = crate::historian::feather_store::site_dir(source, id);
            assert!(!dir.exists(), "{source} feather site dir must be purged");
        }

        if let Some(ws) = prev_ws {
            std::env::set_var("OPENFDD_WORKSPACE", ws);
        } else {
            std::env::remove_var("OPENFDD_WORKSPACE");
        }
    }
}
