//! Stage a CSV session as a package directory for the Timescale importer.
//!
//! This path does not write Arrow IPC or Parquet history.

use crate::csv_ingest::plan::OutputRow;
use crate::historian::store::workspace_dir;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::Path;

/// Keep an id only when it is already a single storage token.
/// Stripping characters would alias two different ids onto one directory.
fn exact_storage_id(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty()
        || !trimmed
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("invalid id".into());
    }
    Ok(trimmed.to_string())
}

/// Stage rows for Timescale import. Does not write Parquet or Arrow history.
///
/// The directory is `<building_id>.incoming` so the HTTP layer can commit it
/// after the historian write or remove it when the write does not run.
pub fn stage_rows_for_timescale(building_id: &str, rows: &[OutputRow]) -> Result<Value, String> {
    if rows.is_empty() {
        return Err("no rows to stage".into());
    }
    let building_id = exact_storage_id(building_id)?;
    let grouped = group_by_equipment(rows)?;
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let building_root = data_root.join(format!("{building_id}.incoming"));
    if building_root.exists() {
        fs::remove_dir_all(&building_root).map_err(|e| e.to_string())?;
    }
    fs::create_dir_all(&building_root).map_err(|e| e.to_string())?;

    let grid_minutes = infer_grid_minutes(rows).unwrap_or(5);
    let manifest = json!({
        "grid_minutes": grid_minutes,
        "export_metadata": {
            "source": "csv_import",
            "building_id": building_id,
            "inferred_grid_minutes": grid_minutes,
        }
    });
    fs::write(
        building_root.join("manifest.json"),
        serde_json::to_string_pretty(&manifest).unwrap_or_default(),
    )
    .map_err(|e| format!("manifest write: {e}"))?;

    let mut equipment_written = 0usize;
    for (equipment_id, equip_rows) in &grouped {
        let equip_dir = building_root.join(equipment_id);
        fs::create_dir_all(&equip_dir).map_err(|e| e.to_string())?;
        let mut value_keys: Vec<String> = equip_rows
            .iter()
            .flat_map(|r| r.values.keys().cloned())
            .filter(|k| k != "equipment_id")
            .collect();
        value_keys.sort();
        value_keys.dedup();
        write_history_wide(&equip_dir.join("history_wide.csv"), equip_rows, &value_keys)?;
        write_columns_csv(&equip_dir.join("columns.csv"), &value_keys)?;
        equipment_written += 1;
    }

    Ok(json!({
        "ok": true,
        "building_id": building_id,
        "package_root": building_root.display().to_string(),
        "equipment_written": equipment_written,
        "total_rows": rows.len(),
        "grid_minutes": grid_minutes,
        "staged": true,
        "needs_timescale_seed": true,
        "historian": "timescale",
        "arrow": false,
        "parquet": false,
        "parquet_ingest": {"ok": false, "skipped": true, "historian": "timescale"},
    }))
}

/// Historical name. Stages a Timescale package and does not write Parquet.
pub fn ingest_rows_to_parquet(dataset_id: &str, rows: &[OutputRow]) -> Value {
    match stage_rows_for_timescale(dataset_id, rows) {
        Ok(result) => result,
        Err(e) => json!({"ok": false, "error": e, "arrow": false, "parquet": false}),
    }
}

fn group_by_equipment(rows: &[OutputRow]) -> Result<BTreeMap<String, Vec<&OutputRow>>, String> {
    let mut grouped: BTreeMap<String, Vec<&OutputRow>> = BTreeMap::new();
    for row in rows {
        let equipment_id = match row.values.get("equipment_id").map(String::as_str) {
            Some(raw) if !raw.trim().is_empty() => exact_storage_id(raw)?,
            _ => "equipment".to_string(),
        };
        grouped.entry(equipment_id).or_default().push(row);
    }
    if grouped.is_empty() {
        return Err("no rows to stage".into());
    }
    Ok(grouped)
}

/// Median positive Δt between consecutive UTC timestamps, rounded to whole minutes (≥1).
fn infer_grid_minutes(rows: &[OutputRow]) -> Option<u32> {
    let mut ts: Vec<i64> = rows
        .iter()
        .filter_map(|r| r.ts_utc.map(|t| t.timestamp()))
        .collect();
    if ts.len() < 2 {
        return None;
    }
    ts.sort_unstable();
    ts.dedup();
    if ts.len() < 2 {
        return None;
    }
    let mut deltas: Vec<i64> = ts
        .windows(2)
        .map(|w| w[1] - w[0])
        .filter(|d| *d > 0)
        .collect();
    if deltas.is_empty() {
        return None;
    }
    deltas.sort_unstable();
    let median = deltas[deltas.len() / 2];
    let minutes = ((median as f64) / 60.0).round() as i64;
    Some(minutes.clamp(1, 60) as u32)
}

fn write_history_wide(
    path: &Path,
    rows: &[&OutputRow],
    value_keys: &[String],
) -> Result<(), String> {
    let mut f = fs::File::create(path).map_err(|e| e.to_string())?;
    write!(f, "timestamp_utc").map_err(|e| e.to_string())?;
    for k in value_keys {
        write!(f, ",{k}").map_err(|e| e.to_string())?;
    }
    writeln!(f).map_err(|e| e.to_string())?;
    for r in rows {
        let ts = r
            .ts_utc
            .map(|u| u.to_rfc3339())
            .unwrap_or_else(|| r.ts_local.clone());
        if ts.trim().is_empty() {
            continue;
        }
        write!(f, "{ts}").map_err(|e| e.to_string())?;
        for k in value_keys {
            let v = r.values.get(k).map(|s| s.as_str()).unwrap_or("");
            // Escape commas in values
            if v.contains(',') || v.contains('"') {
                let esc = v.replace('"', "\"\"");
                write!(f, ",\"{esc}\"").map_err(|e| e.to_string())?;
            } else {
                write!(f, ",{v}").map_err(|e| e.to_string())?;
            }
        }
        writeln!(f).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn write_columns_csv(path: &Path, value_keys: &[String]) -> Result<(), String> {
    let mut f = fs::File::create(path).map_err(|e| e.to_string())?;
    writeln!(f, "column,role").map_err(|e| e.to_string())?;
    for k in value_keys {
        let role = exact_storage_id(k)?;
        writeln!(f, "{k},{role}").map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use std::collections::BTreeMap;

    #[test]
    fn ingest_rows_writes_parquet_layout() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!("openfdd_pq_test_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::remove_var("OPENFDD_STORAGE_URL");
        std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.join(".cache/parquet"));

        let mut values = BTreeMap::new();
        values.insert("duct_static".into(), "0.5".into());
        values.insert("duct_static_sp".into(), "1.4".into());
        values.insert("fan_cmd".into(), "1.0".into());
        let rows: Vec<OutputRow> = (0..3)
            .map(|i| OutputRow {
                ts_utc: Some(chrono::Utc.with_ymd_and_hms(2024, 1, 1, 12, i, 0).unwrap()),
                ts_local: String::new(),
                timezone: "UTC".into(),
                source_timestamp_raw: String::new(),
                source_timestamp_parse_status: "ok".into(),
                source_timestamp_fold: None,
                source_file: "t.csv".into(),
                source_row_number: i as u64 + 1,
                values: values.clone(),
                fill_created: false,
            })
            .collect();
        let out = ingest_rows_to_parquet("fc1_job", &rows);
        assert_eq!(out.get("ok"), Some(&json!(true)), "{out}");
        assert_eq!(out.get("arrow"), Some(&json!(false)), "{out}");
        assert_eq!(out.get("parquet"), Some(&json!(false)), "{out}");
        assert_eq!(out.get("grid_minutes"), Some(&json!(1)), "{out}");
        assert!(
            !tmp.join(".cache/parquet").exists() || !walk_has_name(&tmp, "history.parquet"),
            "parquet history was written"
        );
        assert!(
            !walk_has_name(&tmp, "data.arrow"),
            "arrow history was written"
        );
        assert!(
            !walk_has_name(&tmp, "history.parquet"),
            "parquet history was written"
        );
        let cols = fs::read_to_string(
            tmp.join("data/csv_buildings/fc1_job.incoming/equipment/columns.csv"),
        )
        .unwrap();
        assert!(cols.contains("fan_cmd"), "{cols}");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn infer_grid_minutes_from_1min_cadence() {
        let rows: Vec<OutputRow> = (0..5)
            .map(|i| OutputRow {
                ts_utc: Some(chrono::Utc.with_ymd_and_hms(2024, 1, 1, 12, i, 0).unwrap()),
                ts_local: String::new(),
                timezone: "UTC".into(),
                source_timestamp_raw: String::new(),
                source_timestamp_parse_status: "ok".into(),
                source_timestamp_fold: None,
                source_file: "t.csv".into(),
                source_row_number: i as u64 + 1,
                values: BTreeMap::new(),
                fill_created: false,
            })
            .collect();
        assert_eq!(infer_grid_minutes(&rows), Some(1));
    }

    #[test]
    fn ingest_rows_honors_storage_url() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!("openfdd_pq_storage_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        let storage = tmp.join("openfdd");
        fs::create_dir_all(&storage).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
        std::env::set_var(
            "OPENFDD_STORAGE_URL",
            format!("file://{}", storage.display()),
        );

        let mut values = BTreeMap::new();
        values.insert("fan_cmd".into(), "1.0".into());
        let rows = vec![OutputRow {
            ts_utc: Some(chrono::Utc.with_ymd_and_hms(2024, 1, 1, 12, 0, 0).unwrap()),
            ts_local: String::new(),
            timezone: "UTC".into(),
            source_timestamp_raw: String::new(),
            source_timestamp_parse_status: "ok".into(),
            source_timestamp_fold: None,
            source_file: "t.csv".into(),
            source_row_number: 1,
            values,
            fill_created: false,
        }];
        let out = ingest_rows_to_parquet("storage_job", &rows);
        assert_eq!(out.get("ok"), Some(&json!(true)), "{out}");
        assert_eq!(out.get("parquet"), Some(&json!(false)), "{out}");
        assert!(
            !walk_has_name(&storage, "history.parquet"),
            "storage url received parquet history"
        );
        assert!(!walk_has_name(&tmp, "data.arrow"));
        assert!(
            tmp.join("data/csv_buildings/storage_job.incoming/equipment/history_wide.csv")
                .is_file(),
            "{out}"
        );
        std::env::remove_var("OPENFDD_STORAGE_URL");
        let _ = fs::remove_dir_all(&tmp);
    }

    fn walk_has_name(root: &Path, name: &str) -> bool {
        let mut stack = vec![root.to_path_buf()];
        while let Some(dir) = stack.pop() {
            let Ok(rd) = fs::read_dir(&dir) else {
                continue;
            };
            for ent in rd.flatten() {
                let path = ent.path();
                if path.is_dir() {
                    stack.push(path);
                } else if path.file_name().and_then(|n| n.to_str()) == Some(name) {
                    return true;
                }
            }
        }
        false
    }
}
