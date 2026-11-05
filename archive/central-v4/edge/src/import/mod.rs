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
    let source_filename = body
        .get("source_filename")
        .and_then(|v| v.as_str())
        .unwrap_or("import.csv");
    let (site_id, equip_id, source_id, _) =
        crate::model::csv_import::ids_from_filename(source_filename);
    let job = json!({
        "ok": true,
        "job_id": job_id,
        "status": "created",
        "source_filename": source_filename,
        "site_id": site_id,
        "equipment_id": equip_id,
        "source_id": source_id,
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
        "source_filename",
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
    let source_filename = job
        .get("source_filename")
        .and_then(|v| v.as_str())
        .or_else(|| job.get("source_file").and_then(|v| v.as_str()))
        .unwrap_or("import.csv");
    let (site_id, equipment, source, _) =
        crate::model::csv_import::ids_from_filename(source_filename);
    let mut rows_committed = 0u64;
    let mut warnings: Vec<String> = Vec::new();
    let file = match fs::File::open(&path) {
        Ok(f) => f,
        Err(err) => return json!({"ok": false, "error": err.to_string()}),
    };
    let mut rdr = csv::ReaderBuilder::new().flexible(true).from_reader(file);
    let headers = match rdr.headers() {
        Ok(h) => h.iter().map(str::to_string).collect::<Vec<_>>(),
        Err(err) => return json!({"ok": false, "error": err.to_string()}),
    };
    if headers.is_empty() {
        return json!({"ok": false, "error": "csv header row missing"});
    }
    let ts_idx = crate::model::csv_import::find_timestamp_column(&headers);
    let value_cols: Vec<(usize, String)> = headers
        .iter()
        .enumerate()
        .filter(|(i, h)| *i != ts_idx && !h.trim().is_empty())
        .map(|(i, h)| (i, crate::model::csv_import::column_slug(h)))
        .collect();
    let mut line = 1u64;
    let mut new_rows: Vec<Value> = Vec::new();
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
        if record.len() < headers.len() && record.len() <= ts_idx {
            warnings.push(format!("line {line}: short row, skipped"));
            continue;
        }
        let ts = record.get(ts_idx).unwrap_or("").trim().to_string();
        if ts.is_empty() {
            warnings.push(format!("line {line}: timestamp empty, skipped"));
            continue;
        }
        let mut row = json!({
            "timestamp": ts,
            "equipment_id": equipment,
            "source": format!("{source}:{job_id}"),
            "source_driver": "csv",
            "is_simulated": false
        });
        for (idx, slug) in &value_cols {
            if let Some(raw) = record.get(*idx) {
                if raw.trim().is_empty() {
                    continue;
                }
                match raw.trim().parse::<f64>() {
                    Ok(v) => {
                        row[slug] = json!(v);
                        crate::model::csv_import::apply_pivot_aliases(&mut row, slug, v);
                    }
                    Err(_) => warnings.push(format!("line {line}: {slug} not numeric")),
                }
            }
        }
        if row.as_object().map(|o| o.len()).unwrap_or(0) <= 5 {
            warnings.push(format!("line {line}: no numeric values, skipped"));
            continue;
        }
        new_rows.push(row);
        rows_committed += 1;
    }
    if !new_rows.is_empty() {
        let mut all = store::load_pivot_rows().unwrap_or_default();
        all.extend(new_rows);
        if let Err(err) = store::rewrite_all(&all) {
            let mut updated = job.clone();
            updated["status"] = json!("failed");
            updated["error"] = json!(err);
            let _ = save_job(&updated);
            return json!({"ok": false, "job_id": job_id, "error": err, "rows_committed": rows_committed});
        }
    }
    let model = {
        let maps = crate::model::csv_workbench::load_column_mappings();
        let (_, _, source_id, _) = crate::model::csv_import::ids_from_filename(source_filename);
        let header_map = maps.get(&source_id).cloned();
        crate::model::csv_import::import_from_csv_commit(
            &headers,
            source_filename,
            job_id,
            header_map.as_ref(),
        )
    };
    let mut updated = job.clone();
    updated["status"] = json!("completed");
    updated["rows_committed"] = json!(rows_committed);
    updated["warnings"] = json!(warnings);
    updated["warning_count"] = json!(warnings.len());
    updated["completed_at"] = json!(Utc::now().to_rfc3339());
    updated["historian_row_count"] = json!(store::row_count());
    updated["site_id"] = json!(site_id);
    updated["equipment_id"] = json!(equipment);
    updated["source_id"] = json!(source);
    updated["model_import"] = model.clone();
    let _ = save_job(&updated);
    json!({
        "ok": true,
        "job_id": job_id,
        "status": "completed",
        "rows_committed": rows_committed,
        "warning_count": warnings.len(),
        "warnings": warnings,
        "historian_row_count": store::row_count(),
        "site_id": site_id,
        "equipment_id": equipment,
        "source_id": source,
        "model_import": model
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
