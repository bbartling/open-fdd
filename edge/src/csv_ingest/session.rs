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

pub fn delete_session(session_id: &str) -> Result<(), String> {
    let dir = session_dir(session_id);
    if !dir.starts_with(sessions_root()) {
        return Err("invalid session id".into());
    }
    if dir.exists() {
        fs::remove_dir_all(dir).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn session_path_ok(path: &Path) -> bool {
    path.starts_with(sessions_root())
}

/// Recent import sessions (newest first) for agent/UI pickers.
pub fn list_sessions_handler(limit: usize) -> Value {
    let root = sessions_root();
    let mut sessions = Vec::new();
    if let Ok(entries) = fs::read_dir(&root) {
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            let id = entry.file_name().to_string_lossy().to_string();
            let Some(session) = load_session(&id) else {
                continue;
            };
            sessions.push(json!({
                "session_id": id,
                "status": session.get("status").cloned().unwrap_or(json!(null)),
                "created_at": session.get("created_at").cloned().unwrap_or(json!(null)),
                "file_count": session.get("files").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
                "dataset_name": session.get("plan")
                    .and_then(|p| p.get("output_dataset_name"))
                    .cloned()
                    .unwrap_or(json!(null)),
                "row_count": session.get("preview_summary")
                    .and_then(|p| p.get("row_count"))
                    .cloned()
                    .unwrap_or(json!(null)),
                "fusion_url": format!("/csv?session={id}"),
            }));
        }
    }
    sessions.sort_by(|a, b| {
        let ta = a.get("created_at").and_then(|v| v.as_str()).unwrap_or("");
        let tb = b.get("created_at").and_then(|v| v.as_str()).unwrap_or("");
        tb.cmp(ta)
    });
    sessions.truncate(limit.clamp(1, 100));
    json!({"ok": true, "sessions": sessions})
}

pub fn latest_planned_session_handler() -> Value {
    let listed = list_sessions_handler(20);
    let empty = json!({"ok": false, "error": "no import session found — upload CSVs and run Preview plan in UT3 panel"});
    let Some(arr) = listed.get("sessions").and_then(|v| v.as_array()) else {
        return empty;
    };
    for s in arr {
        let status = s.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if matches!(status, "planned" | "previewed" | "executed") {
            return json!({
                "ok": true,
                "session": s.clone(),
                "session_id": s.get("session_id").cloned().unwrap_or(json!(null)),
                "fusion_url": s.get("fusion_url").cloned().unwrap_or(json!(null)),
            });
        }
    }
    empty
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn delete_session_removes_directory() {
        let id = "test-delete-session";
        let dir = session_dir(id);
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("files")).unwrap();
        fs::write(dir.join("session.json"), r#"{"status":"planned"}"#).unwrap();
        assert!(dir.exists());
        delete_session(id).unwrap();
        assert!(!dir.exists());
    }
}
