use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result};
use arrow::array::{Float64Array, StringArray, TimestampNanosecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::record_batch::RecordBatch;
use parquet::arrow::ArrowWriter;
use serde::Serialize;

use fdd_core::{load_column_role_map, validate_building};

use crate::meta::{meta_path_for, source_fingerprint, write_meta, SidecarMeta};

#[derive(Debug, Clone, Serialize)]
pub struct IngestTiming {
    pub equipment_id: String,
    pub read_ms: u128,
    pub write_ms: u128,
    pub rows: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct IngestReport {
    pub building_id: String,
    pub out_dir: String,
    pub equipment_written: usize,
    pub total_rows: u64,
    pub timings: Vec<IngestTiming>,
    pub total_ms: u128,
    pub weather_ingested: bool,
    pub weather_rows: Option<usize>,
    pub weather_error: Option<String>,
}

pub fn ingest_building(
    data_root: &Path,
    building_id: &str,
    out_dir: &Path,
) -> Result<IngestReport> {
    let started = Instant::now();
    std::fs::create_dir_all(out_dir)?;
    let validation = validate_building(data_root, building_id)?;
    let mut timings = Vec::new();
    let mut total_rows = 0u64;

    for eq in &validation.equipment {
        let t0 = Instant::now();
        let (batch, rows) =
            read_csv_batch(Path::new(&eq.history_path), Path::new(&eq.columns_path))?;
        let read_ms = t0.elapsed().as_millis();

        let dest = out_dir
            .join(format!("building={}", building_id))
            .join(format!("equipment={}", eq.equipment_id));
        std::fs::create_dir_all(&dest)?;
        let parquet_path = dest.join("history.parquet");

        let t1 = Instant::now();
        write_parquet(&parquet_path, &batch)?;
        let write_ms = t1.elapsed().as_millis();

        let src = Path::new(&eq.history_path);
        let (size, mtime, hash) = source_fingerprint(src)?;
        let meta = SidecarMeta {
            building_id: building_id.to_string(),
            equipment_id: eq.equipment_id.clone(),
            source_csv: src.display().to_string(),
            source_size_bytes: size,
            source_modified_unix: mtime,
            source_sha256: hash,
            parquet_path: parquet_path.display().to_string(),
            row_count: rows,
            generated_at: chrono::Utc::now().to_rfc3339(),
        };
        write_meta(&meta_path_for(&parquet_path), &meta)?;

        total_rows += rows;
        timings.push(IngestTiming {
            equipment_id: eq.equipment_id.clone(),
            read_ms,
            write_ms,
            rows,
        });
    }

    let manifest_sidecar = serde_json::json!({
        "building_id": building_id,
        "grid_minutes": validation.grid_minutes,
        "effective_poll_seconds": validation.effective_poll_seconds,
    });
    std::fs::write(
        out_dir.join("manifest.json"),
        serde_json::to_string_pretty(&manifest_sidecar)?,
    )?;

    let staged = out_dir.parent().unwrap_or(out_dir).join("weather_staging");
    let weather_root = if staged.join("history_wide.csv").is_file() {
        staged
    } else {
        data_root.join("weather")
    };
    let (weather_ingested, weather_rows, weather_error) =
        match ingest_weather_tree(&weather_root, out_dir) {
            Ok(n) => (n > 0, Some(n), None),
            Err(e) => (false, None, Some(e.to_string())),
        };

    Ok(IngestReport {
        building_id: building_id.to_string(),
        out_dir: out_dir.display().to_string(),
        equipment_written: timings.len(),
        total_rows,
        timings,
        total_ms: started.elapsed().as_millis(),
        weather_ingested,
        weather_rows,
        weather_error,
    })
}

fn read_csv_batch(path: &Path, columns_path: &Path) -> Result<(RecordBatch, u64)> {
    let role_map = load_column_role_map(columns_path).unwrap_or_default();
    let mut rdr = csv::Reader::from_path(path).context("csv open")?;
    let headers: Vec<String> = rdr.headers()?.iter().map(|s| s.to_string()).collect();
    let ts_idx = headers
        .iter()
        .position(|h| h == "timestamp_utc" || h == "timestamp")
        .context("timestamp column")?;

    let mut ts_vals: Vec<i64> = Vec::new();
    let mut by_role: std::collections::HashMap<String, Vec<(usize, String)>> =
        std::collections::HashMap::new();
    for (i, h) in headers.iter().enumerate() {
        if i == ts_idx {
            continue;
        }
        let Some(role) = role_map.get(h) else {
            continue;
        };
        by_role
            .entry(role.clone())
            .or_default()
            .push((i, h.clone()));
    }
    let mut included: Vec<(usize, String)> = Vec::new();
    for (role, candidates) in by_role {
        let (idx, _) = pick_best_column(&role, &candidates);
        included.push((idx, role));
    }
    included.sort_by_key(|(idx, _)| *idx);
    // Most FDD roles are numeric; a few categorical schedule/mode roles must stay Utf8
    // so SQL like LOWER(occ_mode)='unoccupied' works (#550 / SCHED-*).
    let mut num_cols: Vec<Vec<Option<f64>>> = Vec::new();
    let mut str_cols: Vec<Vec<Option<String>>> = Vec::new();
    let mut col_kind: Vec<bool> = Vec::new(); // true => Utf8
    for (_, role) in &included {
        if is_utf8_role(role) {
            col_kind.push(true);
            str_cols.push(Vec::new());
            num_cols.push(Vec::new());
        } else {
            col_kind.push(false);
            str_cols.push(Vec::new());
            num_cols.push(Vec::new());
        }
    }
    let mut rows = 0u64;

    for rec in rdr.records() {
        let rec = rec?;
        rows += 1;
        let raw_ts = rec.get(ts_idx).unwrap_or("");
        let ts: i64 = chrono::DateTime::parse_from_rfc3339(raw_ts)
            .map(|dt| {
                dt.with_timezone(&chrono::Utc)
                    .timestamp_nanos_opt()
                    .unwrap_or(0)
            })
            .unwrap_or(0);
        ts_vals.push(ts);
        for (j, (i, _)) in included.iter().enumerate() {
            let cell = rec.get(*i).unwrap_or("").trim();
            if col_kind[j] {
                if cell.is_empty() {
                    str_cols[j].push(None);
                } else {
                    str_cols[j].push(Some(cell.to_string()));
                }
            } else {
                num_cols[j].push(cell.parse::<f64>().ok());
            }
        }
    }

    let mut fields = vec![Field::new(
        "timestamp_utc",
        DataType::Timestamp(TimeUnit::Nanosecond, None),
        false,
    )];
    let mut arrays: Vec<arrow::array::ArrayRef> =
        vec![std::sync::Arc::new(TimestampNanosecondArray::from(ts_vals)) as _];

    for (j, (_, role)) in included.iter().enumerate() {
        if col_kind[j] {
            fields.push(Field::new(role, DataType::Utf8, true));
            let arr = StringArray::from(str_cols[j].clone());
            arrays.push(std::sync::Arc::new(arr) as _);
        } else {
            fields.push(Field::new(role, DataType::Float64, true));
            let arr = Float64Array::from(num_cols[j].clone());
            arrays.push(std::sync::Arc::new(arr) as _);
        }
    }

    // equipment_id column for SQL joins
    fields.push(Field::new("equipment_id", DataType::Utf8, false));
    let eq_id = path
        .parent()
        .and_then(|p| p.file_name())
        .and_then(|s| s.to_str())
        .unwrap_or("unknown");
    let eq_arr = StringArray::from(vec![eq_id; rows as usize]);
    arrays.push(std::sync::Arc::new(eq_arr) as _);

    let schema = Schema::new(fields);
    let batch = RecordBatch::try_new(std::sync::Arc::new(schema), arrays)?;
    Ok((batch, rows))
}

fn is_utf8_role(role: &str) -> bool {
    matches!(
        role,
        "occ_mode" | "occupancy" | "schedule" | "mode" | "equip_mode"
    )
}

/// When multiple CSV columns map to the same role, pick the oracle-preferred column.
fn pick_best_column(role: &str, candidates: &[(usize, String)]) -> (usize, String) {
    candidates
        .iter()
        .max_by_key(|(_, name)| fdd_core::score_column_for_role(role, name))
        .cloned()
        .unwrap_or_else(|| candidates[0].clone())
}

fn write_parquet(path: &Path, batch: &RecordBatch) -> Result<()> {
    let file = std::fs::File::create(path)?;
    let mut writer = ArrowWriter::try_new(file, batch.schema(), None)?;
    writer.write(batch)?;
    writer.close()?;
    Ok(())
}

/// Ingest Open-Meteo / weather historian CSV tree into `out_dir/weather/`.
pub fn ingest_weather_tree(weather_root: &Path, out_dir: &Path) -> Result<usize> {
    let mut written = 0usize;
    if !weather_root.is_dir() {
        return Ok(0);
    }
    let mut bundles: Vec<(PathBuf, PathBuf)> = Vec::new();
    let root_cols = weather_root.join("columns.csv");
    let root_hist = weather_root.join("history_wide.csv");
    if root_cols.is_file() && root_hist.is_file() {
        bundles.push((root_hist, root_cols));
    }
    for entry in std::fs::read_dir(weather_root)? {
        let entry = entry?;
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let columns = path.join("columns.csv");
        let history = path.join("history_wide.csv");
        if columns.is_file() && history.is_file() {
            bundles.push((history, columns));
        }
    }
    if bundles.is_empty() {
        return Ok(0);
    }
    let dest = out_dir.join("weather");
    std::fs::create_dir_all(&dest)?;
    if let Some((history, columns)) = bundles.into_iter().next() {
        let (batch, _rows) = read_csv_batch(&history, &columns)?;
        let parquet_path = dest.join("history.parquet");
        write_parquet(&parquet_path, &batch)?;
        written += 1;
    }
    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    #[test]
    fn weather_flat_csv_maps_oa_t() {
        let tmp = TempDir::new().unwrap();
        let mut f = std::fs::File::create(tmp.path().join("columns.csv")).unwrap();
        writeln!(
            f,
            "col,point_role\noutside_air_temp_f,outside_air_temp\nrelative_humidity_pct,oa_humidity"
        )
        .unwrap();
        let mut h = std::fs::File::create(tmp.path().join("history_wide.csv")).unwrap();
        writeln!(h, "timestamp_utc,outside_air_temp_f,relative_humidity_pct").unwrap();
        writeln!(h, "2026-01-01T00:00:00Z,65.0,41.0").unwrap();
        let (batch, rows) = read_csv_batch(
            &tmp.path().join("history_wide.csv"),
            &tmp.path().join("columns.csv"),
        )
        .unwrap();
        assert_eq!(rows, 1);
        let names: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect();
        assert!(names.iter().any(|n| n == "oa_t"), "fields: {names:?}");
    }

    #[test]
    fn real_weather_staging_if_present() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.cache/weather_staging");
        if !root.join("history_wide.csv").is_file() {
            return;
        }
        let (batch, rows) =
            read_csv_batch(&root.join("history_wide.csv"), &root.join("columns.csv")).unwrap();
        assert!(rows > 1000, "rows={rows}");
        let names: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect();
        assert!(names.iter().any(|n| n == "oa_t"), "fields: {names:?}");
    }

    #[test]
    fn ingest_weather_tree_writes_oa_t() {
        let staging = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.cache/weather_staging");
        if !staging.join("history_wide.csv").is_file() {
            return;
        }
        let tmp = TempDir::new().unwrap();
        let n = ingest_weather_tree(&staging, tmp.path()).unwrap();
        assert_eq!(n, 1);
        let pq = tmp.path().join("weather/history.parquet");
        assert!(pq.is_file());
        let file = std::fs::File::open(&pq).unwrap();
        let reader = parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder::try_new(file)
            .unwrap()
            .build()
            .unwrap();
        let batch = reader.into_iter().next().unwrap().unwrap();
        let names: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect();
        assert!(names.iter().any(|n| n == "oa_t"), "fields: {names:?}");
    }

    #[test]
    fn vav7_zone_t_prefers_physical_space_temp() {
        let data_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../data/hvac_systems_CLEANED");
        let cols = data_root.join("BUILDING_100/VAV/VAV_7/columns.csv");
        let hist = data_root.join("BUILDING_100/VAV/VAV_7/history_wide.csv");
        if !cols.is_file() || !hist.is_file() {
            return;
        }
        let (batch, _) = read_csv_batch(&hist, &cols).unwrap();
        let sat_idx = batch
            .schema()
            .fields()
            .iter()
            .position(|f| f.name() == "zone_t")
            .expect("zone_t column");
        let col = batch
            .column(sat_idx)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap();
        let min = col.iter().flatten().fold(f64::INFINITY, f64::min);
        let max = col.iter().flatten().fold(f64::NEG_INFINITY, f64::max);
        assert!(min > 60.0 && max < 90.0, "zone_t range {min}..{max}");
    }

    #[test]
    fn occ_mode_ingested_as_utf8() {
        let tmp = TempDir::new().unwrap();
        let data = tmp.path().join("BUILDING_100");
        std::fs::create_dir_all(&data).unwrap();
        std::fs::write(data.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = data.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nocc_col,occ_mode\nfan_col,fan_status\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,occ_col,fan_col").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,unoccupied,1").unwrap();

        let out = tmp.path().join("parquet");
        ingest_building(tmp.path(), "BUILDING_100", &out).unwrap();
        let pq = out.join("building=BUILDING_100/equipment=AHU_1/history.parquet");
        let file = std::fs::File::open(&pq).unwrap();
        let reader = parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder::try_new(file)
            .unwrap()
            .build()
            .unwrap();
        let batch = reader.into_iter().next().unwrap().unwrap();
        let occ = batch
            .schema()
            .fields()
            .iter()
            .position(|f| f.name() == "occ_mode")
            .expect("occ_mode");
        assert_eq!(batch.schema().field(occ).data_type(), &DataType::Utf8);
        let arr = batch
            .column(occ)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(arr.value(0), "unoccupied");
    }

    #[test]
    fn ingest_writes_parquet_and_meta() {
        let tmp = TempDir::new().unwrap();
        let data = tmp.path().join("BUILDING_100");
        std::fs::create_dir_all(&data).unwrap();
        std::fs::write(data.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = data.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_speed_pct,fan_cmd\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_speed_pct").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,1.0").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,2.0").unwrap();

        let out = tmp.path().join("parquet");
        let report = ingest_building(tmp.path(), "BUILDING_100", &out).unwrap();
        assert_eq!(report.equipment_written, 1);
        assert_eq!(report.total_rows, 2);
        let pq = out.join("building=BUILDING_100/equipment=AHU_1/history.parquet");
        assert!(pq.is_file());
        assert!(meta_path_for(&pq).is_file());
    }

    #[test]
    fn ingest_records_weather_error_when_path_missing() {
        let tmp = TempDir::new().unwrap();
        let data = tmp.path().join("BUILDING_100");
        std::fs::create_dir_all(&data).unwrap();
        std::fs::write(data.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = data.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_speed_pct,fan_cmd\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_speed_pct").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,1.0").unwrap();
        let out = tmp.path().join("parquet");
        let report = ingest_building(tmp.path(), "BUILDING_100", &out).unwrap();
        assert!(!report.weather_ingested);
        assert_eq!(report.weather_rows, Some(0));
        assert!(report.weather_error.is_none());
    }
}
