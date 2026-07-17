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

    let manifest = json!({
        "grid_minutes": 5,
        "export_metadata": {
            "source": "csv_import",
            "dataset_id": dataset_id,
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
        let tmp = std::env::temp_dir().join(format!("openfdd_pq_test_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.join(".cache/parquet"));

        let mut values = BTreeMap::new();
        values.insert("sat".into(), "55.0".into());
        values.insert("oa_t".into(), "70.0".into());
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
        let out = ingest_rows_to_parquet("fc1_job", &rows);
        assert_eq!(out.get("ok"), Some(&json!(true)), "{out}");
        let pq = tmp.join(".cache/parquet/building=fc1_job/equipment=fc1_job/history.parquet");
        assert!(pq.is_file(), "missing {}", pq.display());
        let _ = fs::remove_dir_all(&tmp);
    }
}
