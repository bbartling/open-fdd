//! Bench-fixture pivot rows (JSONL) for edge unit tests and offline demos.
//!
//! Not a product historian: central never writes here. Product telemetry is
//! Timescale only.

use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

pub fn historian_subdir() -> String {
    std::env::var("OPENFDD_HISTORIAN_SUBDIR")
        .unwrap_or_else(|_| crate::validation::profile::active_profile().historian_subdir)
}

pub fn bench_dir() -> PathBuf {
    historian_dir_for_subdir(&historian_subdir())
}

pub fn historian_root() -> PathBuf {
    workspace_dir().join("data/historian")
}

pub fn historian_dir_for_subdir(subdir: &str) -> PathBuf {
    historian_root().join(subdir)
}

pub fn valid_subdir(subdir: &str) -> bool {
    !subdir.is_empty() && !subdir.contains("..") && !subdir.contains('/') && !subdir.contains('\\')
}

pub fn list_historian_subdirs() -> Vec<String> {
    let root = historian_root();
    let mut out = Vec::new();
    if !root.exists() {
        return out;
    }
    if pivot_jsonl_path().exists() {
        out.push(historian_subdir());
    }
    if let Ok(entries) = fs::read_dir(&root) {
        for entry in entries.flatten() {
            if !entry.path().is_dir() {
                continue;
            }
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') {
                continue;
            }
            if entry.path().join("telemetry_pivot.jsonl").exists() && !out.contains(&name) {
                out.push(name);
            }
        }
    }
    if out.is_empty() {
        out.push(historian_subdir());
    }
    out.sort();
    out.dedup();
    out
}

pub fn pivot_jsonl_path_for(subdir: &str) -> PathBuf {
    historian_dir_for_subdir(subdir).join("telemetry_pivot.jsonl")
}

pub fn load_rows_in(subdir: &str) -> Result<Vec<Value>, String> {
    if !valid_subdir(subdir) {
        return Err("invalid historian subdir".into());
    }
    let path = pivot_jsonl_path_for(subdir);
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

pub fn row_count_in(subdir: &str) -> usize {
    load_rows_in(subdir).map(|r| r.len()).unwrap_or(0)
}

pub fn rewrite_subdir(subdir: &str, rows: &[Value]) -> Result<(), String> {
    if !valid_subdir(subdir) {
        return Err("invalid historian subdir".into());
    }
    let dir = historian_dir_for_subdir(subdir);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join("telemetry_pivot.jsonl");
    if rows.is_empty() {
        if path.exists() {
            fs::remove_file(&path).map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    for row in rows {
        let line = serde_json::to_string(row).map_err(|e| e.to_string())?;
        writeln!(file, "{line}").map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn pivot_jsonl_path() -> PathBuf {
    bench_dir().join("telemetry_pivot.jsonl")
}

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn ensure_dir() {
    let dir = bench_dir();
    let _ = fs::create_dir_all(&dir);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(&dir) {
            let mut perms = meta.permissions();
            perms.set_mode(0o2775);
            let _ = fs::set_permissions(&dir, perms);
        }
        let pivot = pivot_jsonl_path();
        if pivot.exists() {
            if let Ok(meta) = fs::metadata(&pivot) {
                let mut perms = meta.permissions();
                perms.set_mode(0o664);
                let _ = fs::set_permissions(&pivot, perms);
            }
        }
    }
}

pub fn append_pivot_row(row: &Value) -> Result<(), String> {
    append_pivot_rows(std::slice::from_ref(row))
}

pub fn append_pivot_rows(rows: &[Value]) -> Result<(), String> {
    if rows.is_empty() {
        return Ok(());
    }
    ensure_dir();
    let path = pivot_jsonl_path();
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    for row in rows {
        let line = serde_json::to_string(row).map_err(|e| e.to_string())?;
        writeln!(file, "{line}").map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn load_pivot_rows() -> Result<Vec<Value>, String> {
    let path = pivot_jsonl_path();
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

pub fn row_count() -> usize {
    load_pivot_rows().map(|r| r.len()).unwrap_or(0)
}

pub fn last_sample_at() -> Option<String> {
    load_pivot_rows()
        .ok()
        .and_then(|rows| rows.last().cloned())
        .and_then(|r| {
            r.get("timestamp")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
}

pub fn clear_rows_with_source_prefix(prefix: &str) -> Result<usize, String> {
    let rows = load_pivot_rows()?;
    let before = rows.len();
    let kept: Vec<Value> = rows
        .into_iter()
        .filter(|r| {
            r.get("source")
                .and_then(|v| v.as_str())
                .map(|s| !s.starts_with(prefix))
                .unwrap_or(true)
        })
        .collect();
    let removed = before.saturating_sub(kept.len());
    rewrite_all(&kept)?;
    Ok(removed)
}

pub fn rewrite_all(rows: &[Value]) -> Result<(), String> {
    ensure_dir();
    let path = pivot_jsonl_path();
    if rows.is_empty() {
        if path.exists() {
            fs::remove_file(&path).map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    for row in rows {
        let line = serde_json::to_string(row).map_err(|e| e.to_string())?;
        writeln!(file, "{line}").map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn parse_ts_ms(s: &str) -> Option<i64> {
    let trimmed = s.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(trimmed) {
        return Some(dt.with_timezone(&Utc).timestamp_millis());
    }
    for fmt in [
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ] {
        if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(trimmed, fmt) {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc).timestamp_millis());
        }
    }
    // Never invent Utc::now() — callers must skip the row.
    None
}

pub struct PivotSample<'a> {
    pub timestamp: &'a str,
    pub equipment_id: &'a str,
    pub oa_t: f64,
    pub oa_h: f64,
    pub duct_t: f64,
    pub zn_t: f64,
    pub source: &'a str,
    pub source_driver: &'a str,
    pub is_simulated: bool,
}

pub fn make_pivot_row(sample: PivotSample<'_>) -> Value {
    json!({
        "timestamp": sample.timestamp,
        "equipment_id": sample.equipment_id,
        "oa_t": sample.oa_t,
        "oa_h": sample.oa_h,
        "duct_t": sample.duct_t,
        "zn_t": sample.zn_t,
        "source": sample.source,
        "source_driver": sample.source_driver,
        "is_simulated": sample.is_simulated
    })
}

pub fn status_json() -> Value {
    json!({
        "ok": true,
        "historian_path": bench_dir().display().to_string(),
        "jsonl": pivot_jsonl_path().display().to_string(),
        "row_count": row_count(),
        "last_sample_at": last_sample_at()
    })
}
