//! CSV import jobs — commits normalized rows to the historian via API (Feather is canonical).

use crate::historian::store;
use chrono::Utc;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

const IMPORT_HEADER: &str =
    "job_id,profile_id,status,rows_committed,source_file,created_at,completed_at,error";

pub fn jobs_dir() -> PathBuf {
    store::workspace_dir().join("data/import_jobs")
}

pub fn jobs_exist() -> bool {
    jobs_dir().exists()
        && fs::read_dir(jobs_dir())
            .map(|mut d| d.next().is_some())
            .unwrap_or(false)
}

fn job_path(job_id: &str) -> PathBuf {
    jobs_dir().join(job_id)
}

fn job_file(job_id: &str) -> PathBuf {
    job_path(job_id).join("job.json")
}

fn csv_file(job_id: &str) -> PathBuf {
    job_path(job_id).join("upload.csv")
}

fn load_job(job_id: &str) -> Option<Value> {
    let path = job_file(job_id);
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

fn save_job(job: &Value) -> Result<(), String> {
    let job_id = job
        .get("job_id")
        .and_then(|v| v.as_str())
        .ok_or("missing job_id")?;
    let dir = job_path(job_id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::write(
        job_file(job_id),
        serde_json::to_string_pretty(job).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

pub fn create_job(body: &Value) -> Value {
    let job_id = format!("import-{}", Utc::now().timestamp_millis());
    let job = json!({
        "ok": true,
        "job_id": job_id,
        "status": "created",
        "profile_id": body.get("profile_id").and_then(|v| v.as_str()).unwrap_or("default_csv_import"),
        "site_id": body.get("site_id").and_then(|v| v.as_str()).unwrap_or("site:demo"),
        "building_id": body.get("building_id").and_then(|v| v.as_str()).unwrap_or("building:main"),
        "source_id": body.get("source_id").and_then(|v| v.as_str()).unwrap_or("source:csv-import"),
        "rows_committed": 0,
        "created_at": Utc::now().to_rfc3339(),
        "preview": Value::Null,
        "error": Value::Null
    });
    match save_job(&job) {
        Ok(()) => job,
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn upload_csv(job_id: &str, body: &str) -> Value {
    let Some(mut job) = load_job(job_id) else {
        return json!({"ok": false, "error": "job not found"});
    };
    if body.trim().is_empty() {
        return json!({"ok": false, "error": "empty upload"});
    }
    if body.len() > 250 * 1024 * 1024 {
        return json!({"ok": false, "error": "file exceeds 250MB limit"});
    }
    let path = csv_file(job_id);
    if let Err(err) = fs::write(&path, body) {
        return json!({"ok": false, "error": err.to_string()});
    }
    job["status"] = json!("uploaded");
    job["bytes"] = json!(body.len());
    job["source_file"] = json!(path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("upload.csv"));
    let _ = save_job(&job);
    json!({"ok": true, "job_id": job_id, "status": "uploaded", "bytes": body.len()})
}

fn parse_f64_field(
    record: &csv::StringRecord,
    idx: usize,
    field: &str,
    line: u64,
    default: Option<f64>,
    warnings: &mut Vec<String>,
) -> f64 {
    match record.get(idx) {
        Some(s) if s.trim().is_empty() => {
            if let Some(d) = default {
                warnings.push(format!("line {line}: {field} empty, using default {d}"));
                d
            } else {
                warnings.push(format!("line {line}: {field} empty"));
                0.0
            }
        }
        Some(s) => match s.trim().parse::<f64>() {
            Ok(v) => v,
            Err(_) => {
                warnings.push(format!("line {line}: invalid {field} value '{s}'"));
                default.unwrap_or(0.0)
            }
        },
        None => {
            if let Some(d) = default {
                warnings.push(format!("line {line}: missing {field}, using default {d}"));
                d
            } else {
                0.0
            }
        }
    }
}

pub fn preview_job(job_id: &str) -> Value {
    let Some(mut job) = load_job(job_id) else {
        return json!({"ok": false, "error": "job not found"});
    };
    let path = csv_file(job_id);
    if !path.exists() {
        return json!({"ok": false, "error": "upload missing"});
    }
    let file = match fs::File::open(&path) {
        Ok(f) => f,
        Err(err) => return json!({"ok": false, "error": err.to_string()}),
    };
    let mut rdr = csv::ReaderBuilder::new().flexible(true).from_reader(file);
    let headers = rdr.headers().ok().cloned().unwrap_or_default();
    let columns: Vec<String> = headers.iter().map(str::to_string).collect();
    let mut sample_rows = Vec::new();
    let mut line_count = 1u64;
    for result in rdr.records().take(5) {
        line_count += 1;
        if let Ok(record) = result {
            sample_rows.push(record.iter().map(str::to_string).collect::<Vec<_>>());
        }
    }
    let preview = json!({
        "header": headers.iter().collect::<Vec<_>>().join(","),
        "columns": columns,
        "sample_rows": sample_rows,
        "line_count_estimate": line_count,
        "parser": "csv-crate"
    });
    job["status"] = json!("previewed");
    job["preview"] = preview.clone();
    let _ = save_job(&job);
    json!({"ok": true, "job_id": job_id, "preview": preview})
}

pub fn patch_options(job_id: &str, body: &Value) -> Value {
    let Some(mut job) = load_job(job_id) else {
        return json!({"ok": false, "error": "job not found"});
    };
    for key in [
        "profile_id",
        "site_id",
        "building_id",
        "source_id",
        "equipment_id",
    ] {
        if let Some(v) = body.get(key).and_then(|v| v.as_str()) {
            job[key] = json!(v);
        }
    }
    let _ = save_job(&job);
    json!({"ok": true, "job_id": job_id, "job": job})
}

pub fn commit_job(job_id: &str) -> Value {
    let Some(job) = load_job(job_id) else {
        return json!({"ok": false, "error": "job not found"});
    };
    let path = csv_file(job_id);
    if !path.exists() {
        return json!({"ok": false, "error": "upload missing"});
    };
    let equipment = job
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .unwrap_or("equip:validation");
    let source = job
        .get("source_id")
        .and_then(|v| v.as_str())
        .unwrap_or("source:csv-import");
    let mut rows_committed = 0u64;
    let mut warnings: Vec<String> = Vec::new();
    let file = match fs::File::open(&path) {
        Ok(f) => f,
        Err(err) => return json!({"ok": false, "error": err.to_string()}),
    };
    let mut rdr = csv::ReaderBuilder::new().flexible(true).from_reader(file);
    let mut line = 1u64;
    for result in rdr.records() {
        line += 1;
        let record = match result {
            Ok(r) => r,
            Err(err) => {
                let msg = format!("line {line}: csv parse error: {err}");
                let mut updated = job.clone();
                updated["status"] = json!("failed");
                updated["error"] = json!(msg);
                let _ = save_job(&updated);
                return json!({"ok": false, "job_id": job_id, "error": msg, "rows_committed": rows_committed});
            }
        };
        if record.iter().all(|s| s.trim().is_empty()) {
            continue;
        }
        if record.len() < 3 {
            let msg =
                format!("line {line}: expected timestamp,equipment_id,oa_t[,oa_h,duct_t,zn_t]");
            let mut updated = job.clone();
            updated["status"] = json!("failed");
            updated["error"] = json!(msg);
            let _ = save_job(&updated);
            return json!({"ok": false, "job_id": job_id, "error": msg, "rows_committed": rows_committed});
        }
        let ts = record.get(0).unwrap_or("").trim().to_string();
        if ts.is_empty() {
            warnings.push(format!("line {line}: timestamp empty, skipped"));
            continue;
        }
        let equip = record
            .get(1)
            .filter(|s| !s.trim().is_empty())
            .unwrap_or(equipment);
        let oa_t = parse_f64_field(&record, 2, "oa_t", line, None, &mut warnings);
        let oa_h = parse_f64_field(&record, 3, "oa_h", line, Some(45.0), &mut warnings);
        let duct_t = parse_f64_field(&record, 4, "duct_t", line, Some(55.0), &mut warnings);
        let zn_t = parse_f64_field(&record, 5, "zn_t", line, Some(72.0), &mut warnings);
        let row = store::make_pivot_row(
            &ts,
            equip,
            oa_t,
            oa_h,
            duct_t,
            zn_t,
            &format!("{source}:{job_id}"),
            "csv-import",
            false,
        );
        if let Err(err) = store::append_pivot_row(&row) {
            let mut updated = job.clone();
            updated["status"] = json!("failed");
            updated["error"] = json!(err);
            let _ = save_job(&updated);
            return json!({"ok": false, "job_id": job_id, "error": err, "rows_committed": rows_committed});
        }
        rows_committed += 1;
    }
    let mut updated = job.clone();
    updated["status"] = json!("completed");
    updated["rows_committed"] = json!(rows_committed);
    updated["warnings"] = json!(warnings);
    updated["warning_count"] = json!(warnings.len());
    updated["completed_at"] = json!(Utc::now().to_rfc3339());
    updated["historian_row_count"] = json!(store::row_count());
    let _ = save_job(&updated);
    json!({
        "ok": true,
        "job_id": job_id,
        "status": "completed",
        "rows_committed": rows_committed,
        "warning_count": warnings.len(),
        "warnings": warnings,
        "historian_row_count": store::row_count()
    })
}

pub fn status_job(job_id: &str) -> Value {
    match load_job(job_id) {
        Some(job) => json!({"ok": true, "job": job}),
        None => json!({"ok": false, "error": "job not found"}),
    }
}

pub fn report_job(job_id: &str) -> Value {
    let Some(job) = load_job(job_id) else {
        return json!({"ok": false, "error": "job not found"});
    };
    json!({
        "ok": true,
        "job_id": job_id,
        "report": {
            "status": job.get("status"),
            "rows_committed": job.get("rows_committed"),
            "preview": job.get("preview"),
            "error": job.get("error"),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at")
        }
    })
}

pub fn jobs_csv_export() -> String {
    let mut out = String::from(IMPORT_HEADER);
    out.push('\n');
    let dir = jobs_dir();
    if !dir.exists() {
        return out;
    }
    for entry in fs::read_dir(dir).into_iter().flatten().flatten() {
        if !entry.path().is_dir() {
            continue;
        }
        let job_id = entry.file_name().to_string_lossy().to_string();
        let Some(job) = load_job(&job_id) else {
            continue;
        };
        out.push_str(&csv_escape_row(&[
            job_id,
            job.get("profile_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .into(),
            job.get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .into(),
            job.get("rows_committed")
                .map(|v| v.to_string())
                .unwrap_or_else(|| "0".into()),
            job.get("source_file")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .into(),
            job.get("created_at")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .into(),
            job.get("completed_at")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .into(),
            job.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .into(),
        ]));
        out.push('\n');
    }
    out
}

fn csv_escape_row(fields: &[String]) -> String {
    fields
        .iter()
        .map(|f| {
            if f.contains(',') || f.contains('"') || f.contains('\n') {
                format!("\"{}\"", f.replace('"', "\"\""))
            } else {
                f.clone()
            }
        })
        .collect::<Vec<_>>()
        .join(",")
}

pub fn safe_job_id(raw: &str) -> Option<&str> {
    if raw.is_empty()
        || raw.contains("..")
        || raw.contains('/')
        || raw.contains('\\')
        || !raw.starts_with("import-")
    {
        None
    } else {
        Some(raw)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_path_traversal_job_id() {
        assert!(safe_job_id("../etc/passwd").is_none());
        assert!(safe_job_id("import-123").is_some());
    }
}
