//! After CSV execute, materialize a building package and ingest to OPENFDD_PARQUET_ROOT
//! so `/api/fdd/run` registry mode can run immediately on uploaded data.

use crate::csv_ingest::plan::OutputRow;
use crate::historian::store::workspace_dir;
use serde_json::{json, Value};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

fn parquet_out_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(p);
    }
    let candidates = [
        PathBuf::from(".cache/parquet"),
        workspace_dir().join(".cache/parquet"),
        PathBuf::from("/var/openfdd/workspace/.cache/parquet"),
    ];
    for c in candidates {
        if c.is_dir() {
            return c;
        }
    }
    workspace_dir().join(".cache/parquet")
}

fn sanitize_id(id: &str) -> String {
    let s: String = id
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect();
    if s.is_empty() {
        "csv_job".into()
    } else {
        s
    }
}

/// Write building package under `workspace/data/csv_buildings/<id>/` and run ingest.
pub fn ingest_rows_to_parquet(dataset_id: &str, rows: &[OutputRow]) -> Value {
    if rows.is_empty() {
        return json!({"ok": false, "error": "no rows to ingest to parquet"});
    }
    let building_id = sanitize_id(dataset_id);
    let equip_id = building_id.clone();
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let building_root = data_root.join(&building_id);
    let equip_dir = building_root.join(&equip_id);
    if let Err(e) = fs::create_dir_all(&equip_dir) {
        return json!({"ok": false, "error": format!("mkdir {}: {e}", equip_dir.display())});
    }

    let mut value_keys: Vec<String> = rows.iter().flat_map(|r| r.values.keys().cloned()).collect();
    value_keys.sort();
    value_keys.dedup();

    let grid_minutes = infer_grid_minutes(rows).unwrap_or(5);
    let manifest = json!({
        "grid_minutes": grid_minutes,
        "export_metadata": {
            "source": "csv_import",
            "dataset_id": dataset_id,
            "inferred_grid_minutes": grid_minutes,
        }
    });
    if let Err(e) = fs::write(
        building_root.join("manifest.json"),
        serde_json::to_string_pretty(&manifest).unwrap_or_default(),
    ) {
        return json!({"ok": false, "error": format!("manifest write: {e}")});
    }

    if let Err(e) = write_history_wide(&equip_dir.join("history_wide.csv"), rows, &value_keys) {
        return json!({"ok": false, "error": e});
    }
    if let Err(e) = write_columns_csv(&equip_dir.join("columns.csv"), &value_keys) {
        return json!({"ok": false, "error": e});
    }

    let out_dir = parquet_out_dir();
    match fdd_store::ingest_building(&data_root, &building_id, &out_dir) {
        Ok(report) => json!({
            "ok": true,
            "building_id": report.building_id,
            "out_dir": report.out_dir,
            "equipment_written": report.equipment_written,
            "total_rows": report.total_rows,
            "total_ms": report.total_ms,
            "grid_minutes": grid_minutes,
            "package_root": building_root.display().to_string(),
        }),
        Err(e) => json!({
            "ok": false,
            "error": format!("parquet ingest failed: {e:#}"),
            "package_root": building_root.display().to_string(),
            "out_dir": out_dir.display().to_string(),
        }),
    }
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
    rows: &[OutputRow],
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
        // Role left blank; fdd_core::infer_role_from_column_name maps identity
        // cookbook names (fan_cmd, duct_static, …) at parquet ingest (#525).
        writeln!(f, "{k},").map_err(|e| e.to_string())?;
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
        assert_eq!(out.get("grid_minutes"), Some(&json!(1)), "{out}");
        let pq = tmp.join(".cache/parquet/building=fc1_job/equipment=fc1_job/history.parquet");
        assert!(pq.is_file(), "missing {}", pq.display());
        let cols =
            fs::read_to_string(tmp.join("data/csv_buildings/fc1_job/fc1_job/columns.csv")).unwrap();
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
}
