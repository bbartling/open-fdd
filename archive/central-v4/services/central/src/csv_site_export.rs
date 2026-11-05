//! Read-only site history export.
//!
//! Authorized Timescale rows (`sample` joined to `authorized_series`) are the
//! source. A package `history_wide.csv` tree is used only when that read is
//! empty, and each file is mapped by its own header. The zip entry is
//! `site_history.csv`. This module does not write telemetry.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use csv::WriterBuilder;
use futures_util::TryStreamExt;
use serde_json::Value;
use sqlx::Row;
use zip::write::SimpleFileOptions;
use zip::ZipWriter;

use crate::durable_storage;
use crate::jobs::JobError;

pub const CSV_BUNDLE_SCHEMA: &str = "openfdd_site_csv_v1";
const SITE_CSV_NAME: &str = "site_history.csv";

const DEFAULT_MAX_ROWS: usize = 50_000;
const DEFAULT_MAX_BYTES: usize = 16 * 1024 * 1024;
const DEFAULT_MAX_SPAN_SECS: i64 = 7 * 24 * 60 * 60;

const TIMESTAMP_HEADERS: &[&str] = &["timestamp_utc", "timestamp", "ts"];

const AUTHORIZED_MAX_TS_SQL: &str = "\
SELECT max(s.ts) AS max_ts
FROM sample s
INNER JOIN authorized_series a
  ON a.site_id = s.site_id
 AND a.openfdd_key = s.openfdd_key
WHERE s.site_id = $1";

const AUTHORIZED_ROWS_SQL: &str = "\
SELECT s.ts AS ts,
       a.equipment_id AS equipment_id,
       s.openfdd_key AS point,
       a.role AS role,
       COALESCE(NULLIF(s.unit, ''), a.unit) AS unit,
       s.val AS val
FROM sample s
INNER JOIN authorized_series a
  ON a.site_id = s.site_id
 AND a.openfdd_key = s.openfdd_key
WHERE s.site_id = $1
  AND s.ts >= $2
  AND s.ts <= $3
ORDER BY s.ts ASC, a.equipment_id ASC, s.openfdd_key ASC
LIMIT $4";

const LONG_HEADERS: &[&str] = &[
    "timestamp_utc",
    "equipment_id",
    "point",
    "role",
    "unit",
    "value",
];

/// Download name for the zip whose only history entry is `site_history.csv`.
pub fn site_history_zip_filename(building_id: &str) -> String {
    format!("site_history_{building_id}.zip")
}

#[derive(Debug, Clone)]
struct ExportBudget {
    max_rows: usize,
    max_bytes: usize,
    max_span_secs: i64,
}

impl ExportBudget {
    #[cfg(test)]
    fn standard() -> Self {
        Self {
            max_rows: DEFAULT_MAX_ROWS,
            max_bytes: DEFAULT_MAX_BYTES,
            max_span_secs: DEFAULT_MAX_SPAN_SECS,
        }
    }

    fn from_env() -> Self {
        Self {
            max_rows: env_usize("OPENFDD_CSV_EXPORT_MAX_ROWS", DEFAULT_MAX_ROWS),
            max_bytes: env_usize("OPENFDD_CSV_EXPORT_MAX_BYTES", DEFAULT_MAX_BYTES),
            max_span_secs: env_i64("OPENFDD_CSV_EXPORT_MAX_SPAN_SECS", DEFAULT_MAX_SPAN_SECS),
        }
    }
}

fn env_usize(name: &str, default: usize) -> usize {
    match std::env::var(name) {
        Ok(raw) => match raw.trim().parse::<usize>() {
            Ok(value) if value > 0 => value,
            _ => default,
        },
        Err(_) => default,
    }
}

fn env_i64(name: &str, default: i64) -> i64 {
    match std::env::var(name) {
        Ok(raw) => match raw.trim().parse::<i64>() {
            Ok(value) if value > 0 => value,
            _ => default,
        },
        Err(_) => default,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct LongRow {
    timestamp_utc: String,
    equipment_id: String,
    point: String,
    role: String,
    unit: String,
    value: String,
}

struct RowSet {
    rows: BTreeMap<(String, String, String), LongRow>,
    max_rows: usize,
}

impl RowSet {
    fn new(max_rows: usize) -> Self {
        Self {
            rows: BTreeMap::new(),
            max_rows,
        }
    }

    fn insert(&mut self, row: LongRow) -> Result<(), JobError> {
        let key = (
            row.timestamp_utc.clone(),
            row.equipment_id.clone(),
            row.point.clone(),
        );
        if !self.rows.contains_key(&key) && self.rows.len() >= self.max_rows {
            return Err(JobError::Invalid(format!(
                "export exceeds row budget ({}); narrow the time range",
                self.max_rows
            )));
        }
        self.rows.insert(key, row);
        Ok(())
    }

    fn into_vec(self) -> Vec<LongRow> {
        self.rows.into_values().collect()
    }
}

/// Newest-sample window. The end is the newest authorized timestamp and the
/// start is one span budget earlier, so an export cannot scan an open range.
fn bounded_window(max_ts: DateTime<Utc>, budget: &ExportBudget) -> (DateTime<Utc>, DateTime<Utc>) {
    let span = Duration::seconds(budget.max_span_secs.max(0));
    let start = max_ts.checked_sub_signed(span).unwrap_or(max_ts);
    (start, max_ts)
}

pub async fn build_csv_zip(
    building_id: &str,
    include_faults: bool,
    zip_path: &Path,
) -> Result<u64, JobError> {
    let budget = ExportBudget::from_env();
    let rows = load_history_rows(building_id, &budget).await?;
    let building = building_id.to_string();
    let zip_path = zip_path.to_path_buf();
    tokio::task::spawn_blocking(move || {
        let index = if include_faults {
            load_confirmed_fault_index(&building)
        } else {
            HashMap::new()
        };
        let bytes = render_csv(&rows, include_faults, &index, &budget)?;
        write_single_file_zip(&zip_path, SITE_CSV_NAME, &bytes)
    })
    .await
    .map_err(|err| JobError::Io(format!("site history export stopped: {err}")))?
}

async fn load_history_rows(
    building_id: &str,
    budget: &ExportBudget,
) -> Result<Vec<LongRow>, JobError> {
    let timescale_rows = if crate::timescale_historian::historian_is_timescale() {
        read_authorized_samples(building_id, budget).await?
    } else {
        Vec::new()
    };
    if !timescale_rows.is_empty() {
        return Ok(rows_for_export(timescale_rows, Vec::new()));
    }
    let building_id = building_id.to_string();
    let budget = budget.clone();
    let package = tokio::task::spawn_blocking(move || package_rows(&building_id, &budget))
        .await
        .map_err(|err| JobError::Io(format!("package history read: {err}")))??;
    Ok(rows_for_export(timescale_rows, package))
}

/// Timescale rows replace the package fallback. An empty package (an NF site
/// with no `history_wide.csv`) keeps the authorized rows. Both empty is an
/// empty export, not a not-found error.
fn rows_for_export(timescale_rows: Vec<LongRow>, package_rows: Vec<LongRow>) -> Vec<LongRow> {
    if timescale_rows.is_empty() {
        package_rows
    } else {
        timescale_rows
    }
}

async fn read_authorized_samples(
    building_id: &str,
    budget: &ExportBudget,
) -> Result<Vec<LongRow>, JobError> {
    let tsdb = fdd_tsdb::Tsdb::connect_from_env()
        .await
        .map_err(|err| JobError::Io(err.to_string()))?;
    let bounds = sqlx::query(AUTHORIZED_MAX_TS_SQL)
        .bind(building_id)
        .fetch_one(tsdb.pool())
        .await
        .map_err(|err| JobError::Io(err.to_string()))?;
    let max_ts: Option<DateTime<Utc>> = bounds
        .try_get("max_ts")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let Some(max_ts) = max_ts else {
        return Ok(Vec::new());
    };
    let (start, end) = bounded_window(max_ts, budget);
    let limit = i64::try_from(budget.max_rows.saturating_add(1))
        .map_err(|_| JobError::Invalid("row budget does not fit a SQL limit".into()))?;
    let mut stream = sqlx::query(AUTHORIZED_ROWS_SQL)
        .bind(building_id)
        .bind(start)
        .bind(end)
        .bind(limit)
        .fetch(tsdb.pool());
    let mut rows = RowSet::new(budget.max_rows);
    while let Some(record) = stream
        .try_next()
        .await
        .map_err(|err| JobError::Io(err.to_string()))?
    {
        rows.insert(sample_to_row(&record)?)?;
    }
    Ok(rows.into_vec())
}

fn sample_to_row(record: &sqlx::postgres::PgRow) -> Result<LongRow, JobError> {
    let ts: DateTime<Utc> = record
        .try_get("ts")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let equipment_id: String = record
        .try_get("equipment_id")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let point: String = record
        .try_get("point")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let role: String = record
        .try_get("role")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let unit: Option<String> = record
        .try_get("unit")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let val: Option<f64> = record
        .try_get("val")
        .map_err(|err| JobError::Io(err.to_string()))?;
    Ok(LongRow {
        timestamp_utc: format_utc(ts),
        equipment_id,
        point,
        role,
        unit: unit.unwrap_or_default(),
        value: format_sample_value(val),
    })
}

fn format_sample_value(val: Option<f64>) -> String {
    match val {
        Some(value) if value.is_finite() => format!("{value}"),
        _ => String::new(),
    }
}

fn format_utc(ts: DateTime<Utc>) -> String {
    ts.to_rfc3339_opts(SecondsFormat::AutoSi, true)
}

fn package_rows(building_id: &str, budget: &ExportBudget) -> Result<Vec<LongRow>, JobError> {
    let package = match super::engineering_bundle::package_root(building_id) {
        Ok(path) => path,
        Err(JobError::NotFound(_)) => return Ok(Vec::new()),
        Err(err) => return Err(err),
    };
    let mut files = Vec::new();
    collect_history_wide(&package, &package, budget, &mut files)?;
    files.sort_by(|left, right| left.1.cmp(&right.1));
    let mut rows = RowSet::new(budget.max_rows);
    for (equip_hint, path) in files {
        ingest_history_file(&path, &equip_hint, budget, &mut rows)?;
    }
    Ok(rows.into_vec())
}

fn collect_history_wide(
    root: &Path,
    dir: &Path,
    budget: &ExportBudget,
    out: &mut Vec<(String, PathBuf)>,
) -> Result<(), JobError> {
    let hist = dir.join("history_wide.csv");
    if hist.is_file() {
        if out.len() >= budget.max_rows {
            return Err(JobError::Invalid(format!(
                "export exceeds row budget ({}); narrow the time range",
                budget.max_rows
            )));
        }
        let equip = equipment_hint(root, dir);
        out.push((equip, hist));
        return Ok(());
    }
    if !dir.is_dir() {
        return Ok(());
    }
    let mut children = Vec::new();
    for entry in fs::read_dir(dir).map_err(|err| JobError::Io(err.to_string()))? {
        let entry = entry.map_err(|err| JobError::Io(err.to_string()))?;
        children.push(entry);
    }
    children.sort_by_key(|entry| entry.file_name());
    for entry in children {
        let path = entry.path();
        if path.is_dir() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name != "utilities" {
                collect_history_wide(root, &path, budget, out)?;
            }
        }
    }
    Ok(())
}

fn equipment_hint(root: &Path, dir: &Path) -> String {
    dir.strip_prefix(root)
        .ok()
        .and_then(|rel| rel.components().next())
        .and_then(|component| component.as_os_str().to_str())
        .filter(|name| *name != "utilities" && *name != "weather")
        .map(str::to_string)
        .or_else(|| {
            dir.file_name()
                .and_then(|name| name.to_str())
                .map(str::to_string)
        })
        .unwrap_or_else(|| "equipment".to_string())
}

fn ingest_history_file(
    path: &Path,
    equip_hint: &str,
    budget: &ExportBudget,
    rows: &mut RowSet,
) -> Result<(), JobError> {
    let text = read_capped(path, budget)?;
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .has_headers(true)
        .from_reader(text.as_bytes());
    let headers = reader
        .headers()
        .map_err(|err| JobError::Io(err.to_string()))?;
    let headers: Vec<String> = headers
        .iter()
        .enumerate()
        .map(|(index, header)| normalize_header(index, header))
        .collect();
    let ts_idx = header_position(&headers, TIMESTAMP_HEADERS).ok_or_else(|| {
        JobError::Invalid(format!(
            "history file missing timestamp column: {}",
            path.display()
        ))
    })?;
    let equip_idx = header_position(&headers, &["equipment_id"]);
    for record in reader.records() {
        let record = record.map_err(|err| JobError::Io(err.to_string()))?;
        ingest_wide_record(&headers, &record, equip_hint, ts_idx, equip_idx, rows)?;
    }
    Ok(())
}

fn ingest_wide_record(
    headers: &[String],
    record: &csv::StringRecord,
    equip_hint: &str,
    ts_idx: usize,
    equip_idx: Option<usize>,
    rows: &mut RowSet,
) -> Result<(), JobError> {
    let raw_ts = record.get(ts_idx).unwrap_or("");
    let Some(timestamp_utc) = normalize_timestamp(raw_ts) else {
        return Ok(());
    };
    let from_column = equip_idx
        .and_then(|index| record.get(index))
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let equipment_id = from_column.unwrap_or(equip_hint).to_string();
    if equipment_id.is_empty() {
        return Ok(());
    }
    for (index, header) in headers.iter().enumerate() {
        if index == ts_idx || Some(index) == equip_idx || is_identity_column(header) {
            continue;
        }
        let point = header.trim();
        if point.is_empty() {
            continue;
        }
        let value = record.get(index).unwrap_or("").trim();
        if value.is_empty() {
            continue;
        }
        rows.insert(LongRow {
            timestamp_utc: timestamp_utc.clone(),
            equipment_id: equipment_id.clone(),
            point: point.to_string(),
            role: point.to_string(),
            unit: String::new(),
            value: value.to_string(),
        })?;
    }
    Ok(())
}

fn read_capped(path: &Path, budget: &ExportBudget) -> Result<String, JobError> {
    let meta = fs::metadata(path).map_err(|err| JobError::Io(err.to_string()))?;
    let max_bytes = u64::try_from(budget.max_bytes)
        .map_err(|_| JobError::Invalid("byte budget does not fit a file size".into()))?;
    if meta.len() > max_bytes {
        return Err(JobError::Invalid(format!(
            "history file exceeds output budget ({} bytes)",
            budget.max_bytes
        )));
    }
    fs::read_to_string(path).map_err(|err| JobError::Io(err.to_string()))
}

fn normalize_header(index: usize, raw: &str) -> String {
    let trimmed = raw.trim();
    if index == 0 {
        trimmed.trim_start_matches('\u{feff}').trim().to_string()
    } else {
        trimmed.to_string()
    }
}

fn header_position(headers: &[String], names: &[&str]) -> Option<usize> {
    headers
        .iter()
        .position(|header| names.iter().any(|name| header.eq_ignore_ascii_case(name)))
}

fn is_identity_column(name: &str) -> bool {
    TIMESTAMP_HEADERS
        .iter()
        .any(|header| name.eq_ignore_ascii_case(header))
        || name.eq_ignore_ascii_case("equipment_id")
        || name.eq_ignore_ascii_case("fault")
        || name.eq_ignore_ascii_case("fault_rules")
}

fn normalize_timestamp(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    let candidate = if trimmed.len() > 10 && trimmed.as_bytes().get(10) == Some(&b' ') {
        format!("{}T{}", &trimmed[..10], &trimmed[11..])
    } else {
        trimmed.to_string()
    };
    DateTime::parse_from_rfc3339(&candidate)
        .ok()
        .map(|ts| format_utc(ts.with_timezone(&Utc)))
}

fn render_csv(
    rows: &[LongRow],
    include_faults: bool,
    fault_index: &HashMap<(String, String), Vec<String>>,
    budget: &ExportBudget,
) -> Result<Vec<u8>, JobError> {
    if rows.len() > budget.max_rows {
        return Err(JobError::Invalid(format!(
            "export exceeds row budget ({}); narrow the time range",
            budget.max_rows
        )));
    }
    let mut headers: Vec<&str> = LONG_HEADERS.to_vec();
    if include_faults {
        headers.push("fault");
        headers.push("fault_rules");
    }
    let mut writer = WriterBuilder::new().from_writer(BudgetWriter::new(budget.max_bytes));
    writer
        .write_record(&headers)
        .map_err(|err| map_csv_write(err, budget.max_bytes))?;
    for row in rows {
        let mut record = vec![
            csv_cell(&row.timestamp_utc),
            csv_cell(&row.equipment_id),
            csv_cell(&row.point),
            csv_cell(&row.role),
            csv_cell(&row.unit),
            csv_cell(&row.value),
        ];
        if include_faults {
            let (fault, rules) = fault_at_row(fault_index, &row.equipment_id, &row.timestamp_utc);
            record.push(if fault {
                "1".to_string()
            } else {
                "0".to_string()
            });
            record.push(csv_cell(&rules));
        }
        writer
            .write_record(&record)
            .map_err(|err| map_csv_write(err, budget.max_bytes))?;
    }
    writer
        .flush()
        .map_err(|err| map_io_budget(err, budget.max_bytes))?;
    let body = writer
        .into_inner()
        .map_err(|err| JobError::Io(err.to_string()))?;
    Ok(body.into_vec())
}

struct BudgetWriter {
    inner: Vec<u8>,
    max_bytes: usize,
}

impl BudgetWriter {
    fn new(max_bytes: usize) -> Self {
        Self {
            inner: Vec::new(),
            max_bytes,
        }
    }

    fn into_vec(self) -> Vec<u8> {
        self.inner
    }
}

impl Write for BudgetWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        if self.inner.len().saturating_add(buf.len()) > self.max_bytes {
            return Err(io::Error::new(
                io::ErrorKind::QuotaExceeded,
                "export exceeds output budget",
            ));
        }
        self.inner.extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn map_io_budget(err: io::Error, max_bytes: usize) -> JobError {
    if err.kind() == io::ErrorKind::QuotaExceeded {
        JobError::Invalid(format!("export exceeds output budget ({max_bytes} bytes)"))
    } else {
        JobError::Io(err.to_string())
    }
}

fn map_csv_write(err: csv::Error, max_bytes: usize) -> JobError {
    if let csv::ErrorKind::Io(io_err) = err.kind() {
        if io_err.kind() == io::ErrorKind::QuotaExceeded {
            return map_io_budget(
                io::Error::new(io::ErrorKind::QuotaExceeded, "export exceeds output budget"),
                max_bytes,
            );
        }
    }
    JobError::Io(err.to_string())
}

/// Spreadsheet formula characters are quoted. A real number, including a
/// leading minus or plus, is left unchanged.
fn csv_cell(raw: &str) -> String {
    if raw.is_empty() {
        return String::new();
    }
    if is_plain_number(raw) {
        return raw.trim().to_string();
    }
    match raw.as_bytes().first().copied() {
        Some(b'=' | b'+' | b'-' | b'@' | b'\t' | b'\r') => {
            let mut out = String::with_capacity(raw.len() + 1);
            out.push('\'');
            out.push_str(raw);
            out
        }
        _ => raw.to_string(),
    }
}

fn is_plain_number(raw: &str) -> bool {
    let text = raw.trim();
    let bytes = text.as_bytes();
    if bytes.is_empty() {
        return false;
    }
    let mut index = 0usize;
    if bytes[0] == b'+' || bytes[0] == b'-' {
        index = 1;
    }
    if index >= bytes.len() {
        return false;
    }
    let mut seen_digit = false;
    let mut seen_dot = false;
    let mut exponent = false;
    while index < bytes.len() {
        match bytes[index] {
            b'0'..=b'9' => seen_digit = true,
            b'.' if !seen_dot && !exponent => seen_dot = true,
            b'e' | b'E' if seen_digit && !exponent => {
                exponent = true;
                seen_digit = false;
                if index + 1 < bytes.len() && (bytes[index + 1] == b'+' || bytes[index + 1] == b'-')
                {
                    index += 1;
                }
            }
            _ => return false,
        }
        index += 1;
    }
    seen_digit
}

/// `(equipment_id, ts_key) -> confirmed rule ids at that timestamp`.
fn load_confirmed_fault_index(building_id: &str) -> HashMap<(String, String), Vec<String>> {
    let mut out: HashMap<(String, String), Vec<String>> = HashMap::new();
    let base = durable_storage::resolve_rule_results_base();
    let dir = base.join(format!("building={building_id}"));
    if !dir.is_dir() {
        return out;
    }
    let Ok(entries) = fs::read_dir(&dir) else {
        return out;
    };
    for ent in entries.flatten() {
        let path = ent.path();
        if !path.is_file() {
            continue;
        }
        let Some(rule_id) = path
            .file_stem()
            .and_then(|name| name.to_str())
            .filter(|name| !name.starts_with('_'))
        else {
            continue;
        };
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        let Ok(body) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        for row in body
            .get("rows")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let confirmed = row
                .get("confirmed_fault")
                .and_then(Value::as_bool)
                .or_else(|| {
                    row.get("confirmed_fault")
                        .and_then(Value::as_i64)
                        .map(|n| n != 0)
                })
                .unwrap_or(false);
            if !confirmed {
                continue;
            }
            let equipment_id = row
                .get("equipment_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            if equipment_id.is_empty() {
                continue;
            }
            let ts = row
                .get("timestamp_utc")
                .or_else(|| row.get("timestamp"))
                .and_then(Value::as_str)
                .unwrap_or("");
            for key in normalize_ts_keys(ts) {
                out.entry((equipment_id.clone(), key))
                    .or_default()
                    .push(rule_id.to_string());
            }
        }
    }
    for rules in out.values_mut() {
        rules.sort();
        rules.dedup();
    }
    out
}

fn fault_at_row(
    index: &HashMap<(String, String), Vec<String>>,
    equipment_id: &str,
    timestamp: &str,
) -> (bool, String) {
    let mut rules: Vec<String> = Vec::new();
    for key in normalize_ts_keys(timestamp) {
        if let Some(found) = index.get(&(equipment_id.to_string(), key)) {
            rules.extend(found.iter().cloned());
        }
    }
    rules.sort();
    rules.dedup();
    (!rules.is_empty(), rules.join(";"))
}

fn normalize_ts_keys(raw: &str) -> Vec<String> {
    let text = raw.trim().to_string();
    if text.is_empty() {
        return Vec::new();
    }
    let mut keys: Vec<String> = Vec::new();
    let mut seen = HashSet::new();
    let mut push = |key: String| {
        if !key.is_empty() && seen.insert(key.clone()) {
            keys.push(key);
        }
    };
    push(text.clone());
    if text.len() > 10 {
        let sep = text.as_bytes()[10];
        if sep == b'T' {
            push(format!("{} {}", &text[..10], &text[11..]));
        } else if sep == b' ' {
            push(format!("{}T{}", &text[..10], &text[11..]));
        }
    }
    if text.ends_with("+00:00") {
        push(format!("{}Z", &text[..text.len() - 6]));
    } else if text.ends_with('Z') {
        push(format!("{}+00:00", &text[..text.len() - 1]));
    }
    if let Some(dot) = text.find('.') {
        if text.ends_with('Z') {
            push(format!("{}Z", &text[..dot]));
        }
    }
    keys
}

fn write_single_file_zip(path: &Path, name: &str, body: &[u8]) -> Result<u64, JobError> {
    let file = fs::File::create(path).map_err(|err| JobError::Io(err.to_string()))?;
    let mut writer = ZipWriter::new(file);
    writer
        .set_comment("site_history.csv")
        .map_err(|err| JobError::Io(err.to_string()))?;
    let options = SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    writer
        .start_file(name, options)
        .map_err(|err| JobError::Io(err.to_string()))?;
    writer
        .write_all(body)
        .map_err(|err| JobError::Io(err.to_string()))?;
    writer
        .finish()
        .map_err(|err| JobError::Io(err.to_string()))?;
    fs::metadata(path)
        .map(|meta| meta.len())
        .map_err(|err| JobError::Io(err.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    struct EnvVar {
        name: &'static str,
        prev: Option<String>,
    }

    impl EnvVar {
        fn set(name: &'static str, value: &str) -> Self {
            let prev = std::env::var(name).ok();
            std::env::set_var(name, value);
            Self { name, prev }
        }
    }

    impl Drop for EnvVar {
        fn drop(&mut self) {
            match self.prev.take() {
                Some(value) => std::env::set_var(self.name, value),
                None => std::env::remove_var(self.name),
            }
        }
    }

    fn budget() -> ExportBudget {
        ExportBudget::standard()
    }

    fn parsed(bytes: &[u8]) -> (Vec<String>, Vec<Vec<String>>) {
        let mut reader = csv::ReaderBuilder::new().from_reader(bytes);
        let headers = reader
            .headers()
            .unwrap()
            .iter()
            .map(str::to_string)
            .collect();
        let rows = reader
            .records()
            .map(|record| {
                record
                    .unwrap()
                    .iter()
                    .map(str::to_string)
                    .collect::<Vec<_>>()
            })
            .collect();
        (headers, rows)
    }

    fn cell<'a>(rows: &'a [Vec<String>], equipment: &str, point: &str) -> &'a Vec<String> {
        rows.iter()
            .find(|row| {
                row.get(1).map(String::as_str) == Some(equipment)
                    && row.get(2).map(String::as_str) == Some(point)
            })
            .unwrap_or_else(|| panic!("missing {equipment} {point}"))
    }

    fn write_package(root: &Path, building_id: &str, files: &[(&str, &str)]) {
        let package = root.join("data").join("csv_buildings").join(building_id);
        fs::create_dir_all(&package).unwrap();
        fs::write(package.join("manifest.json"), "{}").unwrap();
        for (rel, body) in files {
            let path = package.join(rel);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).unwrap();
            }
            fs::write(path, body).unwrap();
        }
    }

    #[test]
    fn ahu_and_vav_keep_their_own_points() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(tmp.path());
        write_package(
            tmp.path(),
            "SITE_A",
            &[
                (
                    "AHU_1/history_wide.csv",
                    "timestamp_utc,sat,mat\n2024-06-01T00:00:00Z,55.0,\n",
                ),
                (
                    "VAV_1/history_wide.csv",
                    "timestamp_utc,zone_t\n2024-06-01T00:00:00Z,72\n",
                ),
            ],
        );
        let rows = package_rows("SITE_A", &budget()).unwrap();
        let bytes = render_csv(&rows, false, &HashMap::new(), &budget()).unwrap();
        let (headers, records) = parsed(&bytes);
        assert_eq!(
            headers,
            vec![
                "timestamp_utc",
                "equipment_id",
                "point",
                "role",
                "unit",
                "value"
            ]
        );
        assert_eq!(cell(&records, "AHU_1", "sat")[5], "55.0");
        assert_eq!(cell(&records, "AHU_1", "sat")[3], "sat");
        assert!(records.iter().all(|row| row[2] != "mat"));
        assert_eq!(cell(&records, "VAV_1", "zone_t")[5], "72");
        assert!(records
            .iter()
            .all(|row| !(row[1] == "VAV_1" && row[2] == "sat")));
        assert!(records.iter().all(|row| row[4].is_empty()));
    }

    #[test]
    fn reordered_equal_width_headers_follow_names() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(tmp.path());
        write_package(
            tmp.path(),
            "SITE_A",
            &[
                (
                    "AHU_1/history_wide.csv",
                    "timestamp_utc,sat,mat\n2024-06-01T00:00:00Z,55.0,-3.5\n",
                ),
                (
                    "VAV_1/history_wide.csv",
                    "timestamp_utc,mat,sat\n2024-06-01T00:00:00Z,71.5,80\n",
                ),
            ],
        );
        let rows = package_rows("SITE_A", &budget()).unwrap();
        let bytes = render_csv(&rows, false, &HashMap::new(), &budget()).unwrap();
        let (_, records) = parsed(&bytes);
        assert_eq!(cell(&records, "AHU_1", "sat")[5], "55.0");
        assert_eq!(cell(&records, "AHU_1", "mat")[5], "-3.5");
        assert_eq!(cell(&records, "VAV_1", "mat")[5], "71.5");
        assert_eq!(cell(&records, "VAV_1", "sat")[5], "80");
        assert!(!cell(&records, "AHU_1", "mat")[5].starts_with('\''));
    }

    #[test]
    fn nf_site_without_history_files_keeps_timescale_rows() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(tmp.path());
        write_package(tmp.path(), "SITE_NF", &[]);
        let package = package_rows("SITE_NF", &budget()).unwrap();
        assert!(package.is_empty());
        let timescale = vec![
            LongRow {
                timestamp_utc: "2024-06-01T12:00:00Z".into(),
                equipment_id: "AHU_1".into(),
                point: "AHU_1.sat".into(),
                role: "sat".into(),
                unit: "F".into(),
                value: "55".into(),
            },
            LongRow {
                timestamp_utc: "2024-06-01T12:00:00Z".into(),
                equipment_id: "VAV_1".into(),
                point: "VAV_1.zone_t".into(),
                role: "zone_t".into(),
                unit: String::new(),
                value: String::new(),
            },
        ];
        let selected = rows_for_export(timescale, package);
        let bytes = render_csv(&selected, false, &HashMap::new(), &budget()).unwrap();
        let (_, records) = parsed(&bytes);
        assert_eq!(records.len(), 2);
        let ahu = cell(&records, "AHU_1", "AHU_1.sat");
        assert_eq!(ahu[3], "sat");
        assert_eq!(ahu[4], "F");
        assert_eq!(ahu[5], "55");
        let vav = cell(&records, "VAV_1", "VAV_1.zone_t");
        assert_eq!(vav[3], "zone_t");
        assert!(vav[4].is_empty());
        assert!(vav[5].is_empty());
    }

    #[test]
    fn empty_history_is_a_header_not_an_error() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(tmp.path());
        let rows = package_rows("MISSING_SITE", &budget()).unwrap();
        assert!(rows.is_empty());
        let bytes = render_csv(&rows, false, &HashMap::new(), &budget()).unwrap();
        let (headers, records) = parsed(&bytes);
        assert_eq!(headers[0], "timestamp_utc");
        assert!(records.is_empty());
    }

    #[test]
    fn utc_offsets_collapse_duplicate_instants() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(tmp.path());
        write_package(
            tmp.path(),
            "SITE_A",
            &[(
                "AHU_1/history_wide.csv",
                "\
timestamp_utc,sat
2024-06-01T12:00:00+00:00,1
2024-06-01T08:00:00-04:00,2
2024-06-01T15:00:00+02:00,9
not-a-timestamp,4
",
            )],
        );
        let rows = package_rows("SITE_A", &budget()).unwrap();
        let bytes = render_csv(&rows, false, &HashMap::new(), &budget()).unwrap();
        let (_, records) = parsed(&bytes);
        assert_eq!(records.len(), 2);
        let noon = records
            .iter()
            .find(|row| row[0] == "2024-06-01T12:00:00Z")
            .unwrap();
        assert_eq!(noon[5], "2");
        let later = records
            .iter()
            .find(|row| row[0] == "2024-06-01T13:00:00Z")
            .unwrap();
        assert_eq!(later[5], "9");
        assert!(records.iter().all(|row| row[0].ends_with('Z')));
    }

    #[test]
    fn faults_on_and_off_follow_confirmed_rows() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let rules = tmp.path().join("rules");
        let dir = rules.join("building=SITE_A");
        fs::create_dir_all(&dir).unwrap();
        let payload = serde_json::json!({
            "rows": [
                {"equipment_id": "AHU_1", "timestamp_utc": "2024-06-01T12:00:00Z", "confirmed_fault": true},
                {"equipment_id": "AHU_1", "timestamp_utc": "2024-06-01T13:00:00Z", "confirmed_fault": false},
                {"equipment_id": "VAV_1", "timestamp_utc": "2024-06-01T12:00:00+00:00", "confirmed_fault": 1}
            ]
        });
        fs::write(dir.join("FC1.json"), payload.to_string()).unwrap();
        let _rules = EnvVar::set("OPENFDD_RULE_RESULTS_DIR", rules.to_str().unwrap());
        let index = load_confirmed_fault_index("SITE_A");
        let (yes, rule_ids) = fault_at_row(&index, "AHU_1", "2024-06-01T12:00:00Z");
        assert!(yes);
        assert_eq!(rule_ids, "FC1");
        let (no, _) = fault_at_row(&index, "AHU_1", "2024-06-01T13:00:00Z");
        assert!(!no);

        let rows = vec![
            LongRow {
                timestamp_utc: "2024-06-01T12:00:00Z".into(),
                equipment_id: "AHU_1".into(),
                point: "AHU_1.sat".into(),
                role: "sat".into(),
                unit: String::new(),
                value: "1".into(),
            },
            LongRow {
                timestamp_utc: "2024-06-01T13:00:00Z".into(),
                equipment_id: "AHU_1".into(),
                point: "AHU_1.sat".into(),
                role: "sat".into(),
                unit: String::new(),
                value: "2".into(),
            },
            LongRow {
                timestamp_utc: "2024-06-01T12:00:00Z".into(),
                equipment_id: "VAV_1".into(),
                point: "VAV_1.zone_t".into(),
                role: "zone_t".into(),
                unit: String::new(),
                value: "3".into(),
            },
        ];
        let off = render_csv(&rows, false, &index, &budget()).unwrap();
        let (off_headers, _) = parsed(&off);
        assert!(!off_headers.iter().any(|header| header == "fault"));

        let on = render_csv(&rows, true, &index, &budget()).unwrap();
        let (on_headers, records) = parsed(&on);
        assert_eq!(on_headers[6], "fault");
        assert_eq!(on_headers[7], "fault_rules");
        assert_eq!(cell(&records, "AHU_1", "AHU_1.sat")[6], "1");
        assert_eq!(
            records
                .iter()
                .find(|row| row[0] == "2024-06-01T12:00:00Z" && row[1] == "AHU_1")
                .unwrap()[7],
            "FC1"
        );
        assert_eq!(
            records
                .iter()
                .find(|row| row[0] == "2024-06-01T13:00:00Z")
                .unwrap()[6],
            "0"
        );
        assert_eq!(cell(&records, "VAV_1", "VAV_1.zone_t")[6], "1");
    }

    #[test]
    fn formula_text_is_quoted_and_negative_numbers_stay_numeric() {
        let samples = [
            ("=1+1", "'=1+1"),
            ("+cmd", "'+cmd"),
            ("@SUM(A1)", "'@SUM(A1)"),
            ("\t@cmd", "'\t@cmd"),
            ("\r=1", "'\r=1"),
            ("-12.5", "-12.5"),
            ("+12.5", "+12.5"),
            ("-1.2e-3", "-1.2e-3"),
            ("-0", "-0"),
        ];
        for (raw, expect) in samples {
            assert_eq!(csv_cell(raw), expect, "{raw:?}");
        }
    }

    #[test]
    fn row_and_byte_budgets_fail_closed() {
        let _lock = crate::test_env_lock::lock_env();
        let tmp = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(tmp.path());
        write_package(
            tmp.path(),
            "SITE_A",
            &[(
                "AHU_1/history_wide.csv",
                "timestamp_utc,sat,mat\n2024-06-01T00:00:00Z,1,2\n",
            )],
        );
        let tight = ExportBudget {
            max_rows: 1,
            max_bytes: DEFAULT_MAX_BYTES,
            max_span_secs: DEFAULT_MAX_SPAN_SECS,
        };
        let err = package_rows("SITE_A", &tight).unwrap_err();
        assert!(matches!(err, JobError::Invalid(_)));

        let rows = vec![LongRow {
            timestamp_utc: "2024-06-01T00:00:00Z".into(),
            equipment_id: "AHU_1".into(),
            point: "sat".into(),
            role: "sat".into(),
            unit: String::new(),
            value: "123456789".into(),
        }];
        let tiny = ExportBudget {
            max_rows: 10,
            max_bytes: 16,
            max_span_secs: DEFAULT_MAX_SPAN_SECS,
        };
        let err = render_csv(&rows, false, &HashMap::new(), &tiny).unwrap_err();
        assert!(matches!(err, JobError::Invalid(_)));
    }

    #[test]
    fn default_window_ends_at_the_newest_sample() {
        let max = DateTime::parse_from_rfc3339("2024-06-08T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let (start, end) = bounded_window(max, &budget());
        assert_eq!(end, max);
        assert_eq!(
            start.to_rfc3339_opts(SecondsFormat::Secs, true),
            "2024-06-01T00:00:00Z"
        );
    }

    #[test]
    fn authorized_export_sql_is_a_bounded_read() {
        let rows = AUTHORIZED_ROWS_SQL.to_ascii_lowercase();
        let bounds = AUTHORIZED_MAX_TS_SQL.to_ascii_lowercase();
        assert!(rows.contains("join authorized_series"));
        assert!(rows.contains("limit $4"));
        assert!(bounds.contains("max(s.ts)"));
        for sql in [rows.as_str(), bounds.as_str()] {
            assert!(!sql.contains("insert"));
            assert!(!sql.contains("update"));
            assert!(!sql.contains("delete"));
        }
    }

    #[test]
    fn zip_name_identifies_site_history_csv() {
        assert_eq!(
            site_history_zip_filename("SITE_A"),
            "site_history_SITE_A.zip"
        );
    }

    #[test]
    fn zip_entry_is_site_history_csv() {
        let tmp = tempfile::tempdir().unwrap();
        let zip_path = tmp.path().join("site_history_SITE_A.zip");
        let bytes = render_csv(&[], false, &HashMap::new(), &budget()).unwrap();
        let size = write_single_file_zip(&zip_path, SITE_CSV_NAME, &bytes).unwrap();
        assert!(size > 0);
        let file = fs::File::open(&zip_path).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        assert_eq!(archive.len(), 1);
        assert_eq!(archive.comment(), b"site_history.csv");
        let entry = archive.by_index(0).unwrap();
        assert_eq!(entry.name().unwrap(), "site_history.csv");
    }
}
