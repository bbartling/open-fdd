use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Result};
use arrow::array::{Array, ArrayRef, Float64Array, StringArray, TimestampNanosecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::record_batch::RecordBatch;
use parquet::arrow::ArrowWriter;
use serde::Serialize;

use fdd_core::{load_column_role_map, validate_building};

use crate::meta::{meta_path_for, source_fingerprint, write_meta, SidecarMeta};

/// Parse `timestamp_utc` to UTC nanoseconds.
///
/// Accepts RFC3339 with `Z` or numeric offsets (`+00:00`). Returns `None` on
/// empty / unparseable input — callers must skip the row (never invent epoch 0).
pub fn parse_timestamp_utc_nanos(raw: &str) -> Option<i64> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    chrono::DateTime::parse_from_rfc3339(trimmed)
        .ok()
        .and_then(|dt| dt.with_timezone(&chrono::Utc).timestamp_nanos_opt())
}

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
    ingest_building_with_batch_hook(data_root, building_id, out_dir, |_, _| Ok(()))
}

/// Same as [`ingest_building`], but invokes `on_batch` once per equipment after the
/// CSV→Arrow batch is built and parquet is written — so callers can dual-write
/// Feather (or other stores) without re-reading parquet.
pub fn ingest_building_with_batch_hook<F>(
    data_root: &Path,
    building_id: &str,
    out_dir: &Path,
    mut on_batch: F,
) -> Result<IngestReport>
where
    F: FnMut(&str, &RecordBatch) -> Result<()>,
{
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
        on_batch(&eq.equipment_id, &batch)?;
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
        let raw_ts = rec.get(ts_idx).unwrap_or("").trim();
        // Never invent epoch-0 / "now" for bad stamps — skip the row.
        let Some(ts) = parse_timestamp_utc_nanos(raw_ts) else {
            continue;
        };
        rows += 1;
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
                num_cols[j].push(parse_numeric_cell(cell));
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

/// Parse a numeric CSV cell, accepting the boolean literals BAS exports use for
/// status/proof points (`True`/`False`, `on`/`off`, `yes`/`no`) as 1.0/0.0.
fn parse_numeric_cell(cell: &str) -> Option<f64> {
    if let Ok(v) = cell.parse::<f64>() {
        return Some(v);
    }
    match cell.to_ascii_lowercase().as_str() {
        "true" | "t" | "yes" | "y" | "on" => Some(1.0),
        "false" | "f" | "no" | "n" | "off" => Some(0.0),
        _ => None,
    }
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

fn weather_has_col(batch: &RecordBatch, name: &str) -> bool {
    batch.schema().index_of(name).is_ok()
}

fn weather_clone_col(batch: &RecordBatch, src: &str, dest: &str) -> Option<(Arc<Field>, ArrayRef)> {
    let i = batch.schema().index_of(src).ok()?;
    let col = batch.column(i).clone();
    Some((
        Arc::new(Field::new(dest, col.data_type().clone(), true)),
        col,
    ))
}

fn weather_f64<'a>(batch: &'a RecordBatch, name: &str) -> Option<&'a Float64Array> {
    let i = batch.schema().index_of(name).ok()?;
    batch.column(i).as_any().downcast_ref::<Float64Array>()
}

fn dewpoint_f_from_db_rh(db_f: f64, rh_pct: f64) -> Option<f64> {
    if !db_f.is_finite() || !rh_pct.is_finite() || rh_pct <= 0.0 {
        return None;
    }
    let t_c = (db_f - 32.0) * 5.0 / 9.0;
    let rh = rh_pct.clamp(0.1, 100.0);
    let a = 17.625_f64;
    let b = 243.04_f64;
    let gamma = (rh / 100.0).ln() + (a * t_c) / (b + t_c);
    if (a - gamma).abs() < 1e-12 {
        return None;
    }
    let dp_c = (b * gamma) / (a - gamma);
    Some(dp_c * 9.0 / 5.0 + 32.0)
}

fn null_f64(n: usize) -> ArrayRef {
    Arc::new(Float64Array::from(vec![None; n])) as ArrayRef
}

/// Pandas `enrich_weather_frame` twin: weather parquet always exposes `oa_t`,
/// `web_oa_t`, and `web_oa_dp` so ECON-3/6/7 can JOIN without schema misses.
fn ensure_weather_web_roles(batch: RecordBatch) -> Result<RecordBatch> {
    let n = batch.num_rows();
    let mut fields: Vec<Arc<Field>> = batch.schema().fields().iter().cloned().collect();
    let mut arrays: Vec<ArrayRef> = batch.columns().to_vec();

    if !weather_has_col(&batch, "web_oa_t") {
        if let Some((f, a)) = weather_clone_col(&batch, "oa_t", "web_oa_t") {
            fields.push(f);
            arrays.push(a);
        } else {
            fields.push(Arc::new(Field::new("web_oa_t", DataType::Float64, true)));
            arrays.push(null_f64(n));
        }
    }
    if !weather_has_col(&batch, "oa_t") {
        if let Some((f, a)) = weather_clone_col(&batch, "web_oa_t", "oa_t") {
            fields.push(f);
            arrays.push(a);
        } else {
            fields.push(Arc::new(Field::new("oa_t", DataType::Float64, true)));
            arrays.push(null_f64(n));
        }
    }
    if !weather_has_col(&batch, "web_oa_dp") {
        if let Some((f, a)) = weather_clone_col(&batch, "oa_dp", "web_oa_dp") {
            fields.push(f);
            arrays.push(a);
        } else {
            let db = weather_f64(&batch, "web_oa_t").or_else(|| weather_f64(&batch, "oa_t"));
            let rh = weather_f64(&batch, "oa_h").or_else(|| weather_f64(&batch, "web_oa_h"));
            let dp = match (db, rh) {
                (Some(db), Some(rh)) => Float64Array::from(
                    (0..n)
                        .map(|i| {
                            if db.is_null(i) || rh.is_null(i) {
                                None
                            } else {
                                dewpoint_f_from_db_rh(db.value(i), rh.value(i))
                            }
                        })
                        .collect::<Vec<_>>(),
                ),
                _ => Float64Array::from(vec![None; n]),
            };
            fields.push(Arc::new(Field::new("web_oa_dp", DataType::Float64, true)));
            arrays.push(Arc::new(dp) as ArrayRef);
        }
    }

    let schema = Schema::new(fields);
    Ok(RecordBatch::try_new(Arc::new(schema), arrays)?)
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
        let batch = ensure_weather_web_roles(batch)?;
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
    fn parse_accepts_z_and_plus00_as_same_utc() {
        let z = parse_timestamp_utc_nanos("2026-05-21T20:20:00Z").unwrap();
        let plus = parse_timestamp_utc_nanos("2026-05-21T20:20:00+00:00").unwrap();
        assert_eq!(z, plus);
        assert!(parse_timestamp_utc_nanos("not-a-timestamp").is_none());
        assert!(parse_timestamp_utc_nanos("").is_none());
        assert!(parse_timestamp_utc_nanos("   ").is_none());
    }

    #[test]
    fn mixed_z_and_offset_suffixes_ingest_without_epoch_zero() {
        use arrow::array::Array;
        let tmp = TempDir::new().unwrap();
        let mut f = std::fs::File::create(tmp.path().join("columns.csv")).unwrap();
        writeln!(f, "col,point_role\noat,outside_air_temp").unwrap();
        let mut h = std::fs::File::create(tmp.path().join("history_wide.csv")).unwrap();
        writeln!(h, "timestamp_utc,oat").unwrap();
        writeln!(h, "2026-05-21T20:20:00Z,70").unwrap();
        writeln!(h, "2026-05-21T20:25:00+00:00,71").unwrap();
        writeln!(h, "bogus,72").unwrap();
        writeln!(h, ",73").unwrap();
        let (batch, rows) = read_csv_batch(
            &tmp.path().join("history_wide.csv"),
            &tmp.path().join("columns.csv"),
        )
        .unwrap();
        assert_eq!(rows, 2, "unparseable rows must be skipped, not epoch-0");
        let ts_idx = batch.schema().index_of("timestamp_utc").unwrap();
        let ts = batch
            .column(ts_idx)
            .as_any()
            .downcast_ref::<TimestampNanosecondArray>()
            .unwrap();
        assert_ne!(ts.value(0), 0);
        assert_ne!(ts.value(1), 0);
        assert!(ts.value(1) > ts.value(0));
    }

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
    fn ingest_weather_tree_aliases_web_oa_roles() {
        let tmp = TempDir::new().unwrap();
        let wx = tmp.path().join("wx_src");
        std::fs::create_dir_all(&wx).unwrap();
        let mut f = std::fs::File::create(wx.join("columns.csv")).unwrap();
        writeln!(
            f,
            "col,point_role\noutside_air_temp_f,outside_air_temp\nrelative_humidity_pct,oa_humidity"
        )
        .unwrap();
        let mut h = std::fs::File::create(wx.join("history_wide.csv")).unwrap();
        writeln!(h, "timestamp_utc,outside_air_temp_f,relative_humidity_pct").unwrap();
        writeln!(h, "2026-01-01T00:00:00Z,65.0,41.0").unwrap();
        let out = tmp.path().join("parquet");
        let n = ingest_weather_tree(&wx, &out).unwrap();
        assert_eq!(n, 1);
        let pq = out.join("weather/history.parquet");
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
        assert!(names.iter().any(|n| n == "web_oa_t"), "fields: {names:?}");
        assert!(names.iter().any(|n| n == "web_oa_dp"), "fields: {names:?}");
        let dp_idx = batch.schema().index_of("web_oa_dp").unwrap();
        let dp = batch
            .column(dp_idx)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap();
        assert!(dp.value(0).is_finite(), "magnus dewpoint {}", dp.value(0));
    }

    #[test]
    fn boolean_status_cells_become_numeric() {
        use arrow::array::Array;
        let tmp = TempDir::new().unwrap();
        let mut f = std::fs::File::create(tmp.path().join("columns.csv")).unwrap();
        writeln!(f, "col,point_role\nload_sat,building_zone_load_satisfied").unwrap();
        let mut h = std::fs::File::create(tmp.path().join("history_wide.csv")).unwrap();
        writeln!(h, "timestamp_utc,load_sat").unwrap();
        writeln!(h, "2026-01-01T00:00:00Z,True").unwrap();
        writeln!(h, "2026-01-01T00:05:00Z,False").unwrap();
        writeln!(h, "2026-01-01T00:10:00Z,").unwrap();
        let (batch, rows) = read_csv_batch(
            &tmp.path().join("history_wide.csv"),
            &tmp.path().join("columns.csv"),
        )
        .unwrap();
        assert_eq!(rows, 3);
        let idx = batch
            .schema()
            .index_of("building_zone_load_satisfied")
            .unwrap();
        let col = batch
            .column(idx)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap();
        assert_eq!(col.value(0), 1.0);
        assert_eq!(col.value(1), 0.0);
        assert!(col.is_null(2));
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
    fn ingest_b100_style_picks_mad_c_not_fan_enable() {
        let tmp = TempDir::new().unwrap();
        let mut f = std::fs::File::create(tmp.path().join("columns.csv")).unwrap();
        writeln!(
            f,
            "column,role\n\
             mad_c,oa_damper_pct\n\
             ex_dmpr_pos_fan_enable_pct,\n\
             oa_minimum_position_pct,\n\
             outside_air_temp_f,oa_t"
        )
        .unwrap();
        let mut h = std::fs::File::create(tmp.path().join("history_wide.csv")).unwrap();
        writeln!(
            h,
            "timestamp_utc,mad_c,ex_dmpr_pos_fan_enable_pct,oa_minimum_position_pct,outside_air_temp_f"
        )
        .unwrap();
        writeln!(h, "2026-01-01T00:00:00Z,20,100,20,70").unwrap();
        let (batch, rows) = read_csv_batch(
            &tmp.path().join("history_wide.csv"),
            &tmp.path().join("columns.csv"),
        )
        .unwrap();
        assert_eq!(rows, 1);
        let idx = batch.schema().index_of("oa_damper_pct").unwrap();
        let col = batch
            .column(idx)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap();
        assert_eq!(col.value(0), 20.0);
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
