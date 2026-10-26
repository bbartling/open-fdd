//! Ordinary CSV site dump — flat historian rows in a zip (Wave UX Soft export-two-option).

use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use csv::WriterBuilder;
use serde_json::Value;
use zip::write::SimpleFileOptions;
use zip::ZipWriter;

use crate::durable_storage;
use crate::jobs::JobError;

pub const CSV_BUNDLE_SCHEMA: &str = "openfdd_site_csv_v1";
const SITE_CSV_NAME: &str = "site_history.csv";

pub async fn build_csv_zip(
    building_id: &str,
    include_faults: bool,
    zip_path: &Path,
) -> Result<u64, JobError> {
    let csv_bytes = build_site_csv_bytes(building_id, include_faults).await?;
    write_single_file_zip(zip_path, SITE_CSV_NAME, &csv_bytes)
}

async fn build_site_csv_bytes(
    building_id: &str,
    include_faults: bool,
) -> Result<Vec<u8>, JobError> {
    package_fallback_csv(building_id, include_faults)
}

fn package_fallback_csv(building_id: &str, include_faults: bool) -> Result<Vec<u8>, JobError> {
    let package = super::engineering_bundle::package_root(building_id)?;
    let mut files: Vec<(String, PathBuf)> = Vec::new();
    collect_history_wide(&package, &package, &mut files)?;
    if files.is_empty() {
        return Err(JobError::NotFound(format!(
            "no historian or package history for building_id: {building_id}"
        )));
    }
    files.sort_by(|a, b| a.0.cmp(&b.0));
    let mut merged = WriterBuilder::new()
        .has_headers(true)
        .from_writer(Vec::new());
    let mut out_headers: Option<Vec<String>> = None;
    let fault_index = if include_faults {
        Some(load_confirmed_fault_index(building_id))
    } else {
        None
    };
    for (equip_id, path) in files {
        let text = fs::read_to_string(&path).map_err(|e| JobError::Io(e.to_string()))?;
        let mut rdr = csv::ReaderBuilder::new()
            .has_headers(true)
            .from_reader(text.as_bytes());
        let headers: Vec<String> = rdr
            .headers()
            .map_err(|e| JobError::Io(e.to_string()))?
            .iter()
            .map(str::to_string)
            .collect();
        if out_headers.is_none() {
            let mut hdrs = headers.clone();
            if !hdrs.iter().any(|h| h == "equipment_id") {
                hdrs.insert(1, "equipment_id".into());
            }
            if include_faults {
                hdrs.push("fault".into());
                hdrs.push("fault_rules".into());
            }
            merged
                .write_record(&hdrs)
                .map_err(|e| JobError::Io(e.to_string()))?;
            out_headers = Some(hdrs);
        }
        let Some(hdrs) = out_headers.as_ref() else {
            return Err(JobError::Io("csv headers were not written".into()));
        };
        let ts_col = hdrs
            .iter()
            .position(|h| h == "timestamp_utc" || h == "timestamp");
        let equip_idx = headers.iter().position(|h| h == "equipment_id");
        for rec in rdr.records() {
            let rec = rec.map_err(|e| JobError::Io(e.to_string()))?;
            let mut row: Vec<String> = rec.iter().map(str::to_string).collect();
            let eq = equip_idx
                .and_then(|i| row.get(i))
                .filter(|s| !s.is_empty())
                .cloned()
                .unwrap_or_else(|| equip_id.clone());
            if equip_idx.is_none() {
                row.insert(1, eq.clone());
            }
            if let Some(ref idx) = fault_index {
                let ts = ts_col.and_then(|i| row.get(i)).cloned().unwrap_or_default();
                let (fault, rules) = fault_at_row(idx, &eq, &ts);
                row.push(if fault { "1" } else { "0" }.into());
                row.push(rules);
            }
            merged
                .write_record(&row)
                .map_err(|e| JobError::Io(e.to_string()))?;
        }
    }
    merged.into_inner().map_err(|e| JobError::Io(e.to_string()))
}

fn collect_history_wide(
    root: &Path,
    dir: &Path,
    out: &mut Vec<(String, PathBuf)>,
) -> Result<(), JobError> {
    let hist = dir.join("history_wide.csv");
    if hist.is_file() {
        let equip = dir
            .strip_prefix(root)
            .ok()
            .and_then(|p| p.components().next())
            .and_then(|c| c.as_os_str().to_str())
            .filter(|s| *s != "utilities" && *s != "weather")
            .unwrap_or_else(|| {
                dir.file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("equipment")
            })
            .to_string();
        out.push((equip, hist));
        return Ok(());
    }
    if !dir.is_dir() {
        return Ok(());
    }
    for entry in fs::read_dir(dir).map_err(|e| JobError::Io(e.to_string()))? {
        let entry = entry.map_err(|e| JobError::Io(e.to_string()))?;
        let path = entry.path();
        if path.is_dir() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name != "utilities" {
                collect_history_wide(root, &path, out)?;
            }
        }
    }
    Ok(())
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
            .and_then(|s| s.to_str())
            .filter(|s| !s.starts_with('_'))
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
                .and_then(|v| v.as_bool())
                .or_else(|| {
                    row.get("confirmed_fault")
                        .and_then(|v| v.as_i64())
                        .map(|n| n != 0)
                })
                .unwrap_or(false);
            if !confirmed {
                continue;
            }
            let eq = row
                .get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            if eq.is_empty() {
                continue;
            }
            let ts = row
                .get("timestamp_utc")
                .or_else(|| row.get("timestamp"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            for key in normalize_ts_keys(ts) {
                out.entry((eq.clone(), key))
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
        if let Some(r) = index.get(&(equipment_id.to_string(), key)) {
            rules.extend(r.iter().cloned());
        }
    }
    rules.sort();
    rules.dedup();
    (!rules.is_empty(), rules.join(";"))
}

fn normalize_ts_keys(raw: &str) -> Vec<String> {
    let s = raw.trim().to_string();
    if s.is_empty() {
        return Vec::new();
    }
    let mut keys: Vec<String> = Vec::new();
    let mut seen = HashSet::new();
    let mut push = |k: String| {
        if !k.is_empty() && seen.insert(k.clone()) {
            keys.push(k);
        }
    };
    push(s.clone());
    if s.len() > 10 {
        let sep = s.as_bytes()[10];
        if sep == b'T' {
            push(format!("{} {}", &s[..10], &s[11..]));
        } else if sep == b' ' {
            push(format!("{}T{}", &s[..10], &s[11..]));
        }
    }
    if s.ends_with("+00:00") {
        push(format!("{}Z", &s[..s.len() - 6]));
    } else if s.ends_with('Z') {
        push(format!("{}+00:00", &s[..s.len() - 1]));
    }
    if let Some(dot) = s.find('.') {
        if s.ends_with('Z') {
            push(format!("{}Z", &s[..dot]));
        }
    }
    keys
}

fn write_single_file_zip(path: &Path, name: &str, body: &[u8]) -> Result<u64, JobError> {
    let file = fs::File::create(path).map_err(|e| JobError::Io(e.to_string()))?;
    let mut writer = ZipWriter::new(file);
    let options = SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    writer
        .start_file(name, options)
        .map_err(|e| JobError::Io(e.to_string()))?;
    writer
        .write_all(body)
        .map_err(|e| JobError::Io(e.to_string()))?;
    writer.finish().map_err(|e| JobError::Io(e.to_string()))?;
    fs::metadata(path)
        .map(|m| m.len())
        .map_err(|e| JobError::Io(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fault_index_and_join_use_confirmed_rows_only() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("building=BLDG_A");
        fs::create_dir_all(&dir).unwrap();
        let payload = serde_json::json!({
            "rows": [
                {"equipment_id": "AHU_1", "timestamp_utc": "2024-06-01T12:00:00Z", "confirmed_fault": true},
                {"equipment_id": "AHU_1", "timestamp_utc": "2024-06-01T13:00:00Z", "confirmed_fault": false},
            ]
        });
        fs::write(dir.join("FC1.json"), payload.to_string()).unwrap();
        let prev = std::env::var("OPENFDD_RULE_RESULTS_DIR").ok();
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", tmp.path());
        let idx = load_confirmed_fault_index("BLDG_A");
        if let Some(v) = prev {
            std::env::set_var("OPENFDD_RULE_RESULTS_DIR", v);
        } else {
            std::env::remove_var("OPENFDD_RULE_RESULTS_DIR");
        }
        let (yes, rules) = fault_at_row(&idx, "AHU_1", "2024-06-01T12:00:00Z");
        assert!(yes);
        assert_eq!(rules, "FC1");
        let (no, _) = fault_at_row(&idx, "AHU_1", "2024-06-01T13:00:00Z");
        assert!(!no);
    }
}
