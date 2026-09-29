//! Parquet analytics / RCx / fault result cache.
//!
//! Result tables are Arrow columns under `analytics_results/`, keyed by
//! building, query id, query version, time window, and config hash. This is
//! not an AFDD `{rule_id}.json` envelope dump: scalar fields are typed
//! columns. Provenance (watermark, config hash) lives in Parquet key/value
//! metadata.
//!
//! Layout:
//! ```text
//! {storage}/analytics_results/building_id={id}/query_id={query}/query_version={ver}/window={start}__{end}/config={hash16}/results.parquet
//! ```
//!
//! Schema `analytics-result-parquet-v1`:
//! - `section` (utf8): `rows` | `equipment` | `points` | `skipped` | `warning` | `coverage`
//! - `row_index` (uint32)
//! - one nullable column per scalar field (float64, bool, or utf8)
//!
//! Nested objects and arrays are utf8 JSON cells because Arrow has no single
//! dynamic struct for mixed analytics families. The file is still a columnar
//! table, not one JSON blob column.

use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use arrow::array::{Array, ArrayRef, BooleanArray, Float64Array, StringArray, UInt32Array};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::record_batch::RecordBatch;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use parquet::arrow::ArrowWriter;
use parquet::file::metadata::KeyValue;
use parquet::file::properties::WriterProperties;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::historian::safe_partition_value;

pub const SCHEMA_NAME: &str = "analytics-result-parquet-v1";
pub const RESULTS_DIR: &str = "analytics_results";

const COL_SECTION: &str = "section";
const COL_ROW_INDEX: &str = "row_index";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheFreshness {
    Hit,
    Stale,
    Miss,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StaleAction {
    /// Return the cached table and set `stale` so charts are not silently fresh.
    ServeStale,
    /// Recompute when the historian watermark moved.
    Recompute,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReadPlan {
    pub recompute: bool,
    pub serve_cached: bool,
    pub stale: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalyticsCacheKey {
    pub building_id: String,
    pub query_id: String,
    pub query_version: String,
    pub window_start: String,
    pub window_end: String,
    pub config_hash: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AnalyticsResultTable {
    pub rows: Vec<Value>,
    pub equipment: Vec<Value>,
    pub points: Vec<Value>,
    pub skipped: Vec<Value>,
    pub warnings: Vec<String>,
    pub coverage: Option<Value>,
    pub engine: String,
    pub result_query_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheProvenance {
    pub building_id: String,
    pub query_id: String,
    pub query_version: String,
    pub window_start: String,
    pub window_end: String,
    pub config_hash: String,
    pub watermark_order: u64,
    pub watermark_utc: String,
    pub generated_at: String,
    pub engine: String,
    pub result_query_version: String,
}

pub fn config_hash(material: &str) -> String {
    let digest = Sha256::digest(material.as_bytes());
    hex_encode(&digest)
}

pub fn read_plan(freshness: CacheFreshness, refresh: bool, on_stale: StaleAction) -> ReadPlan {
    if refresh {
        return ReadPlan {
            recompute: true,
            serve_cached: false,
            stale: false,
        };
    }
    match freshness {
        CacheFreshness::Hit => ReadPlan {
            recompute: false,
            serve_cached: true,
            stale: false,
        },
        CacheFreshness::Stale => match on_stale {
            StaleAction::ServeStale => ReadPlan {
                recompute: false,
                serve_cached: true,
                stale: true,
            },
            StaleAction::Recompute => ReadPlan {
                recompute: true,
                serve_cached: false,
                stale: false,
            },
        },
        CacheFreshness::Miss => ReadPlan {
            recompute: true,
            serve_cached: false,
            stale: false,
        },
    }
}

pub fn freshness_for_watermark(cached_order: u64, historian_order: u64) -> CacheFreshness {
    if historian_order > cached_order {
        CacheFreshness::Stale
    } else {
        CacheFreshness::Hit
    }
}

/// Newest historian parquet order key for one building, or 0 when none exist.
///
/// Order keys are `YYYYMMDDHHMMSS` taken from part stamps, else `year=`/`month=`,
/// else file mtime. Analytics result files are not part of the watermark.
pub fn historian_watermark_order(storage_root: &Path, building_id: &str) -> Result<u64> {
    let building_id = safe_partition_value(building_id, "building_id")?;
    let mut best = 0u64;
    let mut stack = vec![storage_root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = fs::read_dir(&dir) else {
            continue;
        };
        for ent in rd.flatten() {
            let path = ent.path();
            let Ok(meta) = ent.metadata() else {
                continue;
            };
            if meta.is_dir() {
                if path_is_analytics_results(&path) {
                    continue;
                }
                stack.push(path);
                continue;
            }
            if !meta.is_file() {
                continue;
            }
            if !path
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| e.eq_ignore_ascii_case("parquet"))
            {
                continue;
            }
            if !path_belongs_to_building(&path, &building_id) {
                continue;
            }
            let mtime = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0);
            best = best.max(crate::disk_budget::order_key_from_path(&path, mtime));
        }
    }
    Ok(best)
}

pub fn order_key_to_rfc3339(key: u64) -> String {
    if key < 10_000_000_000_000 {
        return String::new();
    }
    let year = key / 10_000_000_000;
    let mut rest = key % 10_000_000_000;
    let month = rest / 100_000_000;
    rest %= 100_000_000;
    let day = rest / 1_000_000;
    rest %= 1_000_000;
    let hour = rest / 10_000;
    rest %= 10_000;
    let minute = rest / 100;
    let second = rest % 100;
    if !(1..=12).contains(&month)
        || !(1..=31).contains(&day)
        || hour > 23
        || minute > 59
        || second > 59
    {
        return String::new();
    }
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

pub fn partition_dir(storage_root: &Path, key: &AnalyticsCacheKey) -> Result<PathBuf> {
    let building = safe_partition_value(&key.building_id, "building_id")?;
    let query = safe_partition_value(&key.query_id, "query_id")?;
    let version = safe_partition_value(&key.query_version, "query_version")?;
    let start = safe_window_token(&key.window_start)?;
    let end = safe_window_token(&key.window_end)?;
    let hash = short_hash(&key.config_hash);
    let window = format!("{start}__{end}");
    safe_partition_value(&window, "window")?;
    Ok(storage_root
        .join(RESULTS_DIR)
        .join(format!("building_id={building}"))
        .join(format!("query_id={query}"))
        .join(format!("query_version={version}"))
        .join(format!("window={window}"))
        .join(format!("config={hash}")))
}

pub fn write_result(
    storage_root: &Path,
    key: &AnalyticsCacheKey,
    table: &AnalyticsResultTable,
    provenance: &CacheProvenance,
) -> Result<PathBuf> {
    let dir = partition_dir(storage_root, key)?;
    fs::create_dir_all(&dir).with_context(|| format!("mkdir {}", dir.display()))?;
    let batch = table_to_batch(table)?;
    let kvs = provenance_kvs(provenance);
    let props = WriterProperties::builder()
        .set_key_value_metadata(Some(kvs))
        .build();
    let final_path = dir.join("results.parquet");
    let tmp_path = dir.join("results.parquet.tmp");
    {
        let file =
            File::create(&tmp_path).with_context(|| format!("create {}", tmp_path.display()))?;
        let mut writer = ArrowWriter::try_new(file, batch.schema(), Some(props))?;
        writer.write(&batch)?;
        writer.close()?;
    }
    fs::rename(&tmp_path, &final_path)
        .with_context(|| format!("rename {}", final_path.display()))?;
    Ok(final_path)
}

pub fn read_result(
    storage_root: &Path,
    key: &AnalyticsCacheKey,
) -> Result<Option<(AnalyticsResultTable, CacheProvenance)>> {
    let path = partition_dir(storage_root, key)?.join("results.parquet");
    if !path.is_file() {
        return Ok(None);
    }
    let file = File::open(&path).with_context(|| format!("open {}", path.display()))?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file)?;
    let meta = metadata_map(builder.metadata().file_metadata().key_value_metadata());
    if meta.get("openfdd.schema").map(String::as_str) != Some(SCHEMA_NAME) {
        return Ok(None);
    }
    if meta.get("openfdd.config_hash").map(String::as_str) != Some(key.config_hash.as_str()) {
        return Ok(None);
    }
    if meta.get("openfdd.building_id").map(String::as_str) != Some(key.building_id.as_str()) {
        return Ok(None);
    }
    let schema = builder.schema().clone();
    let reader = builder.build()?;
    let mut batches = Vec::new();
    for batch in reader {
        batches.push(batch?);
    }
    let batch = if batches.is_empty() {
        RecordBatch::new_empty(schema)
    } else if batches.len() == 1 {
        batches.pop().expect("len checked")
    } else {
        arrow::compute::concat_batches(&batches[0].schema(), &batches)?
    };
    let table = batch_to_table(&batch, &meta)?;
    let provenance = provenance_from_meta(&meta)?;
    Ok(Some((table, provenance)))
}

fn provenance_kvs(p: &CacheProvenance) -> Vec<KeyValue> {
    let pairs = [
        ("openfdd.schema", SCHEMA_NAME.to_string()),
        ("openfdd.building_id", p.building_id.clone()),
        ("openfdd.query_id", p.query_id.clone()),
        ("openfdd.query_version", p.query_version.clone()),
        ("openfdd.window_start", p.window_start.clone()),
        ("openfdd.window_end", p.window_end.clone()),
        ("openfdd.config_hash", p.config_hash.clone()),
        ("openfdd.watermark_order", p.watermark_order.to_string()),
        ("openfdd.watermark_utc", p.watermark_utc.clone()),
        ("openfdd.generated_at", p.generated_at.clone()),
        ("openfdd.engine", p.engine.clone()),
        (
            "openfdd.result_query_version",
            p.result_query_version.clone(),
        ),
    ];
    pairs
        .into_iter()
        .map(|(k, v)| KeyValue::new(k.to_string(), Some(v)))
        .collect()
}

fn metadata_map(kvs: Option<&Vec<KeyValue>>) -> HashMap<String, String> {
    let mut out = HashMap::new();
    if let Some(kvs) = kvs {
        for kv in kvs {
            if let Some(value) = kv.value.clone() {
                out.insert(kv.key.clone(), value);
            }
        }
    }
    out
}

fn provenance_from_meta(meta: &HashMap<String, String>) -> Result<CacheProvenance> {
    let order = meta
        .get("openfdd.watermark_order")
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);
    Ok(CacheProvenance {
        building_id: meta.get("openfdd.building_id").cloned().unwrap_or_default(),
        query_id: meta.get("openfdd.query_id").cloned().unwrap_or_default(),
        query_version: meta
            .get("openfdd.query_version")
            .cloned()
            .unwrap_or_default(),
        window_start: meta
            .get("openfdd.window_start")
            .cloned()
            .unwrap_or_default(),
        window_end: meta.get("openfdd.window_end").cloned().unwrap_or_default(),
        config_hash: meta.get("openfdd.config_hash").cloned().unwrap_or_default(),
        watermark_order: order,
        watermark_utc: meta
            .get("openfdd.watermark_utc")
            .cloned()
            .unwrap_or_else(|| order_key_to_rfc3339(order)),
        generated_at: meta
            .get("openfdd.generated_at")
            .cloned()
            .unwrap_or_default(),
        engine: meta.get("openfdd.engine").cloned().unwrap_or_default(),
        result_query_version: meta
            .get("openfdd.result_query_version")
            .cloned()
            .unwrap_or_else(|| {
                meta.get("openfdd.query_version")
                    .cloned()
                    .unwrap_or_default()
            }),
    })
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ColKind {
    Empty,
    Float,
    Bool,
    Utf8,
}

enum Cell {
    Null,
    Float(f64),
    Bool(bool),
    Text(String),
}

struct ColAcc {
    kind: ColKind,
    cells: Vec<Cell>,
}

fn table_to_batch(table: &AnalyticsResultTable) -> Result<RecordBatch> {
    let mut records: Vec<(String, Value)> = Vec::new();
    push_section(&mut records, "rows", &table.rows);
    push_section(&mut records, "equipment", &table.equipment);
    push_section(&mut records, "points", &table.points);
    push_section(&mut records, "skipped", &table.skipped);
    for warning in &table.warnings {
        let mut obj = Map::new();
        obj.insert("message".into(), Value::String(warning.clone()));
        records.push(("warning".into(), Value::Object(obj)));
    }
    if let Some(coverage) = &table.coverage {
        records.push(("coverage".into(), coverage.clone()));
    }

    let mut columns: BTreeMap<String, ColAcc> = BTreeMap::new();
    for (_section, value) in &records {
        let obj = value.as_object();
        if let Some(map) = obj {
            for (k, v) in map {
                if k == COL_SECTION || k == COL_ROW_INDEX {
                    continue;
                }
                let acc = columns.entry(k.clone()).or_insert_with(|| ColAcc {
                    kind: ColKind::Empty,
                    cells: Vec::new(),
                });
                // Pad later; kind is updated when we fill in order below.
                let _ = acc;
                let _ = v;
            }
        }
    }

    // Second pass fills cells in record order so lengths match.
    for (_section, value) in &records {
        let map = value.as_object();
        for (name, acc) in columns.iter_mut() {
            let cell_value = map.and_then(|m| m.get(name));
            push_cell(acc, cell_value);
        }
    }

    let mut fields = vec![
        Field::new(COL_SECTION, DataType::Utf8, false),
        Field::new(COL_ROW_INDEX, DataType::UInt32, false),
    ];
    let mut arrays: Vec<ArrayRef> = vec![
        Arc::new(StringArray::from(
            records
                .iter()
                .map(|(section, _)| section.as_str())
                .collect::<Vec<_>>(),
        )),
        Arc::new(UInt32Array::from(
            records
                .iter()
                .enumerate()
                .map(|(i, _)| i as u32)
                .collect::<Vec<_>>(),
        )),
    ];

    // row_index above is global. Rebuild per-section indexes.
    let mut per_section: HashMap<String, u32> = HashMap::new();
    let indexes: Vec<u32> = records
        .iter()
        .map(|(section, _)| {
            let n = per_section.entry(section.clone()).or_insert(0);
            let cur = *n;
            *n += 1;
            cur
        })
        .collect();
    arrays[1] = Arc::new(UInt32Array::from(indexes));

    for (name, acc) in columns {
        fields.push(Field::new(&name, kind_dtype(acc.kind), true));
        arrays.push(cells_to_array(acc));
    }

    let schema = Arc::new(Schema::new(fields));
    RecordBatch::try_new(schema, arrays).map_err(|e| anyhow!("analytics result batch: {e}"))
}

fn push_section(out: &mut Vec<(String, Value)>, section: &str, rows: &[Value]) {
    for row in rows {
        out.push((section.to_string(), row.clone()));
    }
}

fn push_cell(acc: &mut ColAcc, value: Option<&Value>) {
    let cell = match value {
        None | Some(Value::Null) => Cell::Null,
        Some(Value::Bool(b)) => Cell::Bool(*b),
        Some(Value::Number(n)) => {
            if let Some(f) = n.as_f64() {
                Cell::Float(f)
            } else {
                Cell::Text(n.to_string())
            }
        }
        Some(Value::String(s)) => Cell::Text(s.clone()),
        Some(other) => Cell::Text(other.to_string()),
    };
    acc.kind = promote(acc.kind, &cell);
    acc.cells.push(cell);
    if acc.kind == ColKind::Utf8 {
        coerce_utf8(acc);
    }
}

fn promote(kind: ColKind, cell: &Cell) -> ColKind {
    let incoming = match cell {
        Cell::Null => return kind,
        Cell::Float(_) => ColKind::Float,
        Cell::Bool(_) => ColKind::Bool,
        Cell::Text(_) => ColKind::Utf8,
    };
    match (kind, incoming) {
        (ColKind::Empty, k) => k,
        (k, ColKind::Empty) => k,
        (a, b) if a == b => a,
        _ => ColKind::Utf8,
    }
}

fn coerce_utf8(acc: &mut ColAcc) {
    if acc.kind != ColKind::Utf8 {
        return;
    }
    for cell in &mut acc.cells {
        match cell {
            Cell::Float(f) => *cell = Cell::Text(format_float(*f)),
            Cell::Bool(b) => *cell = Cell::Text(if *b { "true" } else { "false" }.into()),
            Cell::Null | Cell::Text(_) => {}
        }
    }
}

fn format_float(f: f64) -> String {
    if f.is_finite() && f.fract() == 0.0 && f.abs() < 1e15 {
        format!("{}", f as i64)
    } else {
        serde_json::Number::from_f64(f)
            .map(|n| n.to_string())
            .unwrap_or_else(|| f.to_string())
    }
}

fn kind_dtype(kind: ColKind) -> DataType {
    match kind {
        ColKind::Bool => DataType::Boolean,
        ColKind::Float => DataType::Float64,
        ColKind::Empty | ColKind::Utf8 => DataType::Utf8,
    }
}

fn cells_to_array(acc: ColAcc) -> ArrayRef {
    match acc.kind {
        ColKind::Bool => {
            let values = acc
                .cells
                .into_iter()
                .map(|c| match c {
                    Cell::Bool(b) => Some(b),
                    _ => None,
                })
                .collect::<Vec<_>>();
            Arc::new(BooleanArray::from(values))
        }
        ColKind::Float => {
            let values = acc
                .cells
                .into_iter()
                .map(|c| match c {
                    Cell::Float(f) => Some(f),
                    _ => None,
                })
                .collect::<Vec<_>>();
            Arc::new(Float64Array::from(values))
        }
        ColKind::Empty | ColKind::Utf8 => {
            let values = acc
                .cells
                .into_iter()
                .map(|c| match c {
                    Cell::Text(s) => Some(s),
                    Cell::Float(f) => Some(format_float(f)),
                    Cell::Bool(b) => Some(if b { "true" } else { "false" }.into()),
                    Cell::Null => None,
                })
                .collect::<Vec<_>>();
            Arc::new(StringArray::from(values))
        }
    }
}

fn batch_to_table(
    batch: &RecordBatch,
    meta: &HashMap<String, String>,
) -> Result<AnalyticsResultTable> {
    let mut grouped: BTreeMap<(String, u32), Map<String, Value>> = BTreeMap::new();
    let section_col = string_col(batch, COL_SECTION)?;
    let index_col = batch
        .column_by_name(COL_ROW_INDEX)
        .ok_or_else(|| anyhow!("missing row_index"))?
        .as_any()
        .downcast_ref::<UInt32Array>()
        .ok_or_else(|| anyhow!("row_index is not uint32"))?;

    let schema = batch.schema();
    for row in 0..batch.num_rows() {
        let section = section_col.value(row).to_string();
        let idx = index_col.value(row);
        let entry = grouped.entry((section, idx)).or_default();
        for col_idx in 0..batch.num_columns() {
            let name = schema.field(col_idx).name();
            if name == COL_SECTION || name == COL_ROW_INDEX {
                continue;
            }
            if let Some(value) = cell_to_json(batch.column(col_idx).as_ref(), row) {
                entry.insert(name.clone(), value);
            }
        }
    }

    let mut table = AnalyticsResultTable {
        rows: Vec::new(),
        equipment: Vec::new(),
        points: Vec::new(),
        skipped: Vec::new(),
        warnings: Vec::new(),
        coverage: None,
        engine: meta.get("openfdd.engine").cloned().unwrap_or_default(),
        result_query_version: meta
            .get("openfdd.result_query_version")
            .cloned()
            .unwrap_or_default(),
    };
    for ((section, _), map) in grouped {
        match section.as_str() {
            "warning" => {
                if let Some(msg) = map.get("message").and_then(|v| v.as_str()) {
                    table.warnings.push(msg.to_string());
                }
            }
            "coverage" => {
                table.coverage = Some(Value::Object(map));
            }
            "rows" => table.rows.push(Value::Object(map)),
            "equipment" => table.equipment.push(Value::Object(map)),
            "points" => table.points.push(Value::Object(map)),
            "skipped" => table.skipped.push(Value::Object(map)),
            _ => {}
        }
    }
    Ok(table)
}

fn string_col<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a StringArray> {
    batch
        .column_by_name(name)
        .ok_or_else(|| anyhow!("missing {name}"))?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| anyhow!("{name} is not utf8"))
}

fn cell_to_json(array: &dyn Array, row: usize) -> Option<Value> {
    if array.is_null(row) {
        return None;
    }
    if let Some(col) = array.as_any().downcast_ref::<Float64Array>() {
        let n = col.value(row);
        if n.is_finite() && n.fract() == 0.0 && n.abs() < 1e15 {
            return Some(Value::Number((n as i64).into()));
        }
        return serde_json::Number::from_f64(n).map(Value::Number);
    }
    if let Some(col) = array.as_any().downcast_ref::<BooleanArray>() {
        return Some(Value::Bool(col.value(row)));
    }
    if let Some(col) = array.as_any().downcast_ref::<StringArray>() {
        let text = col.value(row);
        if (text.starts_with('{') && text.ends_with('}'))
            || (text.starts_with('[') && text.ends_with(']'))
        {
            if let Ok(parsed) = serde_json::from_str::<Value>(text) {
                if parsed.is_object() || parsed.is_array() {
                    return Some(parsed);
                }
            }
        }
        return Some(Value::String(text.to_string()));
    }
    None
}

fn path_is_analytics_results(path: &Path) -> bool {
    path.file_name()
        .and_then(|n| n.to_str())
        .is_some_and(|n| n == RESULTS_DIR)
}

/// Hive partition match only. `equipment_id=…` text is not a building key.
fn path_belongs_to_building(path: &Path, building_id: &str) -> bool {
    let text = path.to_string_lossy();
    let hive = format!("building_id={building_id}");
    let legacy = format!("building={building_id}");
    text.split(['/', '\\'])
        .any(|seg| seg == hive || seg == legacy)
}

fn safe_window_token(raw: &str) -> Result<String> {
    let token = if raw.trim().is_empty() {
        "open".to_string()
    } else {
        raw.trim().to_string()
    };
    if token.contains('/') || token.contains('\\') || token.contains("..") || token.contains('=') {
        bail!("unsafe window token");
    }
    Ok(token)
}

fn short_hash(full: &str) -> String {
    let hex: String = full
        .chars()
        .filter(|c| c.is_ascii_hexdigit())
        .take(16)
        .collect();
    if hex.len() >= 8 {
        hex
    } else {
        config_hash(full).chars().take(16).collect()
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn key(hash: &str) -> AnalyticsCacheKey {
        AnalyticsCacheKey {
            building_id: "site-a".into(),
            query_id: "runtime".into(),
            query_version: "runtime-v1".into(),
            window_start: "2026-01-01T00:00:00Z".into(),
            window_end: "2026-01-08T00:00:00Z".into(),
            config_hash: hash.into(),
        }
    }

    fn sample_table() -> AnalyticsResultTable {
        AnalyticsResultTable {
            rows: vec![json!({"equipment_id": "AHU_1", "run_hours": 12.5, "on": true})],
            equipment: vec![json!({"equipment_id": "AHU_1", "plant_group": "ahu"})],
            points: vec![],
            skipped: vec![json!({"equipment_id": "VAV_2", "reason": "no fan"})],
            warnings: vec!["thin coverage".into()],
            coverage: Some(json!({"samples": 4})),
            engine: "datafusion".into(),
            result_query_version: "runtime-v1".into(),
        }
    }

    #[test]
    fn parquet_roundtrip_is_columnar_not_json_blob() {
        let tmp = tempfile::tempdir().unwrap();
        let hash = config_hash("comfort=70");
        let key = key(&hash);
        let provenance = CacheProvenance {
            building_id: key.building_id.clone(),
            query_id: key.query_id.clone(),
            query_version: key.query_version.clone(),
            window_start: key.window_start.clone(),
            window_end: key.window_end.clone(),
            config_hash: hash.clone(),
            watermark_order: 20260108000000,
            watermark_utc: order_key_to_rfc3339(20260108000000),
            generated_at: "2026-01-08T00:00:00Z".into(),
            engine: "datafusion".into(),
            result_query_version: "runtime-v1".into(),
        };
        let path = write_result(tmp.path(), &key, &sample_table(), &provenance).unwrap();
        assert!(path.ends_with("results.parquet"));
        assert!(path
            .to_string_lossy()
            .contains("analytics_results/building_id=site-a"));

        let file = File::open(&path).unwrap();
        let builder = ParquetRecordBatchReaderBuilder::try_new(file).unwrap();
        let names: Vec<_> = builder
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect();
        assert!(names.contains(&"equipment_id".to_string()));
        assert!(names.contains(&"run_hours".to_string()));
        assert!(names.contains(&"on".to_string()));
        assert!(!names.iter().any(|n| n == "payload" || n == "envelope_json"));

        let (table, got) = read_result(tmp.path(), &key).unwrap().unwrap();
        assert_eq!(table.rows[0]["equipment_id"], "AHU_1");
        assert_eq!(table.rows[0]["run_hours"], 12.5);
        assert_eq!(table.rows[0]["on"], true);
        assert_eq!(table.equipment[0]["plant_group"], "ahu");
        assert_eq!(table.skipped[0]["reason"], "no fan");
        assert_eq!(table.warnings, vec!["thin coverage".to_string()]);
        assert_eq!(table.coverage.unwrap()["samples"], 4);
        assert_eq!(got.watermark_order, 20260108000000);
        assert_eq!(got.config_hash, hash);
        assert_eq!(table.engine, "datafusion");
    }

    #[test]
    fn config_mismatch_is_a_miss() {
        let tmp = tempfile::tempdir().unwrap();
        let hash = config_hash("a");
        let key = key(&hash);
        let provenance = CacheProvenance {
            building_id: key.building_id.clone(),
            query_id: key.query_id.clone(),
            query_version: key.query_version.clone(),
            window_start: key.window_start.clone(),
            window_end: key.window_end.clone(),
            config_hash: hash,
            watermark_order: 1,
            watermark_utc: String::new(),
            generated_at: "t".into(),
            engine: "datafusion".into(),
            result_query_version: "runtime-v1".into(),
        };
        write_result(tmp.path(), &key, &sample_table(), &provenance).unwrap();
        let mut other = key.clone();
        other.config_hash = config_hash("b");
        assert!(read_result(tmp.path(), &other).unwrap().is_none());
    }

    #[test]
    fn watermark_past_cache_is_stale_and_not_a_fresh_hit() {
        assert_eq!(
            freshness_for_watermark(20260101000000, 20260102000000),
            CacheFreshness::Stale
        );
        assert_eq!(
            freshness_for_watermark(20260102000000, 20260102000000),
            CacheFreshness::Hit
        );
        let stale = read_plan(CacheFreshness::Stale, false, StaleAction::ServeStale);
        assert!(stale.serve_cached && stale.stale && !stale.recompute);
        let refresh = read_plan(CacheFreshness::Hit, true, StaleAction::ServeStale);
        assert!(refresh.recompute && !refresh.stale);
        let recompute = read_plan(CacheFreshness::Stale, false, StaleAction::Recompute);
        assert!(recompute.recompute && !recompute.serve_cached);
    }

    #[test]
    fn query_version_change_is_a_different_partition() {
        let tmp = tempfile::tempdir().unwrap();
        let hash = config_hash("same");
        let key = key(&hash);
        let provenance = CacheProvenance {
            building_id: key.building_id.clone(),
            query_id: key.query_id.clone(),
            query_version: key.query_version.clone(),
            window_start: key.window_start.clone(),
            window_end: key.window_end.clone(),
            config_hash: hash,
            watermark_order: 10,
            watermark_utc: String::new(),
            generated_at: "t".into(),
            engine: "datafusion".into(),
            result_query_version: "runtime-v1".into(),
        };
        write_result(tmp.path(), &key, &sample_table(), &provenance).unwrap();
        let mut next = key.clone();
        next.query_version = "runtime-v2".into();
        assert!(read_result(tmp.path(), &next).unwrap().is_none());
        assert!(read_result(tmp.path(), &key).unwrap().is_some());
    }

    #[test]
    fn historian_watermark_ignores_analytics_results_and_other_buildings() {
        let tmp = tempfile::tempdir().unwrap();
        let mine = tmp
            .path()
            .join("history/building_id=site-a/equipment_id=ahu/year=2026/month=01");
        fs::create_dir_all(&mine).unwrap();
        fs::write(mine.join("part-20260115T120000Z-live.parquet"), b"x").unwrap();
        let other = tmp
            .path()
            .join("history/building_id=site-b/year=2026/month=06");
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("part-20260601T000000Z-live.parquet"), b"x").unwrap();
        let cache = tmp.path().join(
            "analytics_results/building_id=site-a/query_id=runtime/part-20261201T000000Z.parquet",
        );
        fs::create_dir_all(cache.parent().unwrap()).unwrap();
        fs::write(&cache, b"x").unwrap();
        let order = historian_watermark_order(tmp.path(), "site-a").unwrap();
        assert_eq!(order, 20260115120000);
        assert_eq!(order_key_to_rfc3339(order), "2026-01-15T12:00:00Z");
    }

    #[test]
    fn watermark_ignores_equipment_id_text_and_id_prefixes() {
        let tmp = tempfile::tempdir().unwrap();
        let by_equipment = tmp.path().join("history/equipment_id=site-a");
        fs::create_dir_all(&by_equipment).unwrap();
        fs::write(
            by_equipment.join("part-20260301T000000Z-live.parquet"),
            b"x",
        )
        .unwrap();
        let prefix = tmp
            .path()
            .join("history/building_id=site-ab/equipment_id=AHU_1");
        fs::create_dir_all(&prefix).unwrap();
        fs::write(prefix.join("part-20260601T000000Z-live.parquet"), b"x").unwrap();
        assert_eq!(historian_watermark_order(tmp.path(), "site-a").unwrap(), 0);
    }

    #[test]
    fn unsafe_building_id_is_rejected() {
        let mut key = key("abcdabcdabcdabcd");
        key.building_id = "../escape".into();
        assert!(partition_dir(Path::new("/tmp"), &key).is_err());
    }
}
