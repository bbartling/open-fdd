//! Per-source Feather (Arrow IPC) shard store — Python `feather_store.py` parity (FIX-43).
//!
//! Layout: `workspace/data/feather_store/<source>/<site_id>/shard-<epoch_ms>-<uuid>.feather`

use arrow::array::{Float64Array, StringArray, TimestampMillisecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::ipc::writer::FileWriter;
use arrow::record_batch::RecordBatch;
use chrono::{DateTime, Utc};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use super::store;

pub const TIMESTAMP_COL: &str = "timestamp";
pub const SITE_ID_COL: &str = "site_id";

pub fn root() -> PathBuf {
    store::workspace_dir().join("data/feather_store")
}

pub fn site_dir(source: &str, site_id: &str) -> PathBuf {
    root()
        .join(safe_path_part(source))
        .join(safe_path_part(site_id))
}

fn safe_path_part(part: &str) -> String {
    let cleaned: String = part
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_' || *c == '.' || *c == ':')
        .collect();
    let trimmed = cleaned.trim_matches('.');
    if trimmed.is_empty() {
        "default".to_string()
    } else {
        trimmed.to_string()
    }
}

fn parse_ts_ms(ts: &str) -> i64 {
    DateTime::parse_from_rfc3339(ts)
        .map(|d| d.timestamp_millis())
        .unwrap_or_else(|_| Utc::now().timestamp_millis())
}

fn shard_name() -> String {
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let suffix: u32 = rand::random();
    format!("shard-{ms}-{suffix:08x}.feather")
}

/// Write one wide poll row as a Feather shard (dynamic numeric columns).
pub fn write_wide_shard(
    source: &str,
    site_id: &str,
    timestamp: &str,
    columns: &BTreeMap<String, f64>,
) -> Result<PathBuf, String> {
    if columns.is_empty() {
        return Err("no columns to write".into());
    }
    let dir = site_dir(source, site_id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(shard_name());

    let mut fields = vec![
        Field::new(
            TIMESTAMP_COL,
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new(SITE_ID_COL, DataType::Utf8, false),
    ];
    let col_names: Vec<String> = columns.keys().cloned().collect();
    for name in &col_names {
        fields.push(Field::new(name, DataType::Float64, true));
    }
    let schema = Arc::new(Schema::new(fields));

    let ts_arr = TimestampMillisecondArray::from(vec![parse_ts_ms(timestamp)]);
    let site_arr = StringArray::from(vec![site_id.to_string()]);
    let mut arrays: Vec<Arc<dyn arrow::array::Array>> = vec![Arc::new(ts_arr), Arc::new(site_arr)];
    for name in &col_names {
        let v = columns.get(name).copied();
        arrays.push(Arc::new(Float64Array::from(vec![v])));
    }

    let batch = RecordBatch::try_new(schema.clone(), arrays).map_err(|e| e.to_string())?;
    let file = fs::File::create(&path).map_err(|e| e.to_string())?;
    let mut writer = FileWriter::try_new(file, &schema).map_err(|e| e.to_string())?;
    writer.write(&batch).map_err(|e| e.to_string())?;
    writer.finish().map_err(|e| e.to_string())?;
    Ok(path)
}

pub fn list_sites(source: Option<&str>) -> Vec<(String, String)> {
    let root = root();
    if !root.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    let sources: Vec<PathBuf> = if let Some(src) = source {
        vec![root.join(safe_path_part(src))]
    } else {
        fs::read_dir(&root)
            .map(|rd| {
                rd.flatten()
                    .filter(|e| e.path().is_dir())
                    .map(|e| e.path())
                    .collect()
            })
            .unwrap_or_default()
    };
    for src_dir in sources {
        if !src_dir.is_dir() {
            continue;
        }
        let source_name = src_dir
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        if let Ok(entries) = fs::read_dir(&src_dir) {
            for entry in entries.flatten() {
                if !entry.path().is_dir() {
                    continue;
                }
                if has_feather_shards(&entry.path()) {
                    out.push((
                        source_name.clone(),
                        entry.file_name().to_string_lossy().to_string(),
                    ));
                }
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

fn has_feather_shards(dir: &Path) -> bool {
    fs::read_dir(dir)
        .map(|rd| {
            rd.flatten()
                .any(|e| e.path().extension().is_some_and(|x| x == "feather"))
        })
        .unwrap_or(false)
}

pub fn total_bytes() -> u64 {
    let root = root();
    if !root.is_dir() {
        return 0;
    }
    let mut total = 0_u64;
    for entry in walk_feather_files(&root) {
        if let Ok(meta) = fs::metadata(entry) {
            total += meta.len();
        }
    }
    total
}

pub fn feather_file_count() -> usize {
    walk_feather_files(&root()).count()
}

fn walk_feather_files(root: &Path) -> impl Iterator<Item = PathBuf> + '_ {
    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        if let Ok(rd) = fs::read_dir(dir) {
            for entry in rd.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    walk(&path, out);
                } else if path.extension().is_some_and(|x| x == "feather") {
                    out.push(path);
                }
            }
        }
    }
    let mut files = Vec::new();
    walk(root, &mut files);
    files.into_iter()
}

pub fn column_slug(label: &str) -> String {
    let mut out = String::new();
    let mut prev_dash = false;
    for c in label.chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
            prev_dash = false;
        } else if !prev_dash {
            out.push('-');
            prev_dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    #[test]
    fn write_shard_creates_feather_file() {
        let ws = env::temp_dir().join(format!("ofdd-feather-{}", std::process::id()));
        env::set_var("OPENFDD_WORKSPACE", &ws);
        let mut cols = BTreeMap::new();
        cols.insert("temp-deg-f".into(), 72.5);
        cols.insert("rh".into(), 45.0);
        let path = write_wide_shard("modbus", "site:local", "2026-07-03T12:00:00Z", &cols)
            .expect("write shard");
        assert!(path.exists());
        assert!(path.extension().is_some_and(|x| x == "feather"));
        assert!(path.metadata().map(|m| m.len()).unwrap_or(0) > 0);
        env::remove_var("OPENFDD_WORKSPACE");
        let _ = fs::remove_dir_all(ws);
    }
}
