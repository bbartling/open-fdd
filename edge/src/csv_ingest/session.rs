//! Import session persistence and file staging.

use crate::csv_ingest::parse::{sanitize_filename, ParseProfile};
use chrono::Utc;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

use super::parse;

pub fn sessions_root() -> PathBuf {
    crate::historian::store::workspace_dir().join("data/csv_import_sessions")
}

pub fn session_dir(id: &str) -> PathBuf {
    sessions_root().join(sanitize_session_id(id))
}

fn sanitize_session_id(id: &str) -> String {
    id.chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect()
}

pub fn create_session() -> Value {
    let id = format!("csv-{}", Utc::now().timestamp_millis());
    let dir = session_dir(&id);
    if let Err(e) = fs::create_dir_all(dir.join("files")) {
        return json!({"ok": false, "error": e.to_string()});
    }
    let session = json!({
        "ok": true,
        "session_id": id,
        "status": "created",
        "files": [],
        "created_at": Utc::now().to_rfc3339(),
        "plan": Value::Null,
        "validation_report": Value::Null,
        "result": Value::Null
    });
    if let Err(e) = save_session(&id, &session) {
        return json!({"ok": false, "error": e});
    }
    session
}

pub fn save_session(id: &str, session: &Value) -> Result<(), String> {
    let dir = session_dir(id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::write(
        dir.join("session.json"),
        serde_json::to_string_pretty(session).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

pub fn load_session(id: &str) -> Option<Value> {
    let path = session_dir(id).join("session.json");
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

pub fn stage_file(session_id: &str, filename: &str, raw: &[u8]) -> Result<Value, String> {
    let safe = sanitize_filename(filename)?;
    let (profile, _text) = parse::parse_csv_bytes(raw, None)?;
    let dir = session_dir(session_id).join("files");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::write(dir.join(&safe), raw).map_err(|e| e.to_string())?;
    Ok(json!({
        "filename": safe,
        "original_filename": filename,
        "bytes": raw.len(),
        "profile": profile_to_json(&profile),
    }))
}

pub fn profile_to_json(p: &ParseProfile) -> Value {
    json!({
        "delimiter": p.delimiter.to_string(),
        "encoding": p.encoding,
        "has_bom": p.has_bom,
        "headers": p.headers,
        "sanitized_headers": p.sanitized_headers,
        "columns": p.columns,
        "row_count": p.row_count,
        "quarantined_count": p.quarantined.len(),
        "quarantined": p.quarantined.iter().take(50).collect::<Vec<_>>(),
        "sample_rows": p.sample_rows,
        "timestamp_candidates": super::timestamp::detect_timestamp_columns(&p.headers, &p.sample_rows),
    })
}

pub fn read_staged_file(
    session_id: &str,
    filename: &str,
) -> Result<(ParseProfile, String), String> {
    let safe = sanitize_filename(filename)?;
    let path = session_dir(session_id).join("files").join(&safe);
    if !path.starts_with(sessions_root()) {
        return Err("path traversal".into());
    }
    let raw = fs::read(&path).map_err(|e| e.to_string())?;
    parse::parse_csv_bytes(&raw, None)
}

pub fn list_staged_files(session_id: &str) -> Vec<String> {
    let dir = session_dir(session_id).join("files");
    let mut out = Vec::new();
    if let Ok(entries) = fs::read_dir(dir) {
        for e in entries.flatten() {
            if e.path().is_file() {
                if let Some(n) = e.file_name().to_str() {
                    out.push(n.to_string());
                }
            }
        }
    }
    out.sort();
    out
}

pub fn delete_staged_file(session_id: &str, filename: &str) -> Result<(), String> {
    let safe = sanitize_filename(filename)?;
    let path = session_dir(session_id).join("files").join(&safe);
    if path.exists() {
        fs::remove_file(path).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn session_path_ok(path: &Path) -> bool {
    path.starts_with(sessions_root())
}
