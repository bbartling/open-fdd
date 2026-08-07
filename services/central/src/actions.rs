//! Durable Actions run log — JSONL under `$OPENFDD_WORKSPACE/data/actions/log.jsonl`.

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::sync::Mutex;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

static LOG_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionEntry {
    pub id: String,
    pub kind: String,
    pub label: String,
    pub started_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finished_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<Value>,
}

fn workspace_root() -> PathBuf {
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        return PathBuf::from(ws);
    }
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE_DIR") {
        return PathBuf::from(ws);
    }
    PathBuf::from("workspace")
}

fn log_path() -> PathBuf {
    workspace_root()
        .join("data")
        .join("actions")
        .join("log.jsonl")
}

fn utc_now() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string()
}

fn ensure_parent(path: &std::path::Path) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

fn read_all_unlocked() -> Vec<ActionEntry> {
    let path = log_path();
    if !path.is_file() {
        return Vec::new();
    }
    let Ok(file) = File::open(&path) else {
        return Vec::new();
    };
    let reader = BufReader::new(file);
    let mut out = Vec::new();
    for line in reader.lines().flatten() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if let Ok(entry) = serde_json::from_str::<ActionEntry>(trimmed) {
            out.push(entry);
        }
    }
    out
}

fn rewrite_all_unlocked(entries: &[ActionEntry]) -> Result<(), String> {
    let path = log_path();
    ensure_parent(&path).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("jsonl.tmp");
    {
        let mut f = File::create(&tmp).map_err(|e| e.to_string())?;
        for e in entries {
            let line = serde_json::to_string(e).map_err(|err| err.to_string())?;
            writeln!(f, "{line}").map_err(|err| err.to_string())?;
        }
        f.flush().map_err(|e| e.to_string())?;
    }
    fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
    Ok(())
}

fn append_unlocked(entry: &ActionEntry) -> Result<(), String> {
    let path = log_path();
    ensure_parent(&path).map_err(|e| e.to_string())?;
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    let line = serde_json::to_string(entry).map_err(|e| e.to_string())?;
    writeln!(f, "{line}").map_err(|e| e.to_string())?;
    f.flush().map_err(|e| e.to_string())?;
    Ok(())
}

/// Start a new action (`status=running`). Returns the entry id.
pub fn start_action(kind: &str, label: &str, detail: Option<Value>) -> Result<String, String> {
    let id = format!("act-{}", Uuid::new_v4());
    let entry = ActionEntry {
        id: id.clone(),
        kind: kind.to_string(),
        label: label.to_string(),
        started_at: utc_now(),
        finished_at: None,
        duration_ms: None,
        status: "running".into(),
        detail,
    };
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    append_unlocked(&entry)?;
    Ok(id)
}

/// Finish an action with `ok` or `fail` and optional detail merge.
pub fn finish_action(id: &str, status: &str, detail: Option<Value>) -> Result<ActionEntry, String> {
    let status = match status {
        "ok" | "fail" => status,
        other => {
            return Err(format!(
                "invalid finish status '{other}' (expected ok|fail)"
            ));
        }
    };
    let finished_at = utc_now();
    let _guard = LOG_LOCK.lock().map_err(|e| e.to_string())?;
    let mut entries = read_all_unlocked();
    let Some(pos) = entries.iter().position(|e| e.id == id) else {
        return Err(format!("action not found: {id}"));
    };
    let entry = &mut entries[pos];
    let started = chrono::DateTime::parse_from_rfc3339(&entry.started_at)
        .ok()
        .map(|t| t.with_timezone(&Utc));
    let finished = chrono::DateTime::parse_from_rfc3339(&finished_at)
        .ok()
        .map(|t| t.with_timezone(&Utc));
    let duration_ms = match (started, finished) {
        (Some(s), Some(f)) => Some((f - s).num_milliseconds().max(0) as u64),
        _ => None,
    };
    entry.finished_at = Some(finished_at);
    entry.duration_ms = duration_ms;
    entry.status = status.to_string();
    if let Some(d) = detail {
        match (&mut entry.detail, d) {
            (Some(Value::Object(base)), Value::Object(extra)) => {
                for (k, v) in extra {
                    base.insert(k, v);
                }
            }
            (slot, other) => {
                *slot = Some(other);
            }
        }
    }
    let out = entry.clone();
    rewrite_all_unlocked(&entries)?;
    Ok(out)
}

/// List recent actions, newest first.
pub fn list_actions(limit: usize) -> Value {
    let limit = if limit == 0 { 100 } else { limit.min(500) };
    let _guard = match LOG_LOCK.lock() {
        Ok(g) => g,
        Err(_) => {
            return json!({
                "ok": false,
                "error": "actions log lock poisoned",
                "actions": [],
            });
        }
    };
    let mut entries = read_all_unlocked();
    entries.reverse();
    entries.truncate(limit);
    json!({
        "ok": true,
        "count": entries.len(),
        "actions": entries,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static TEST_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn start_finish_list_roundtrip() {
        let _t = TEST_LOCK.lock().unwrap();
        let dir = std::env::temp_dir().join(format!("openfdd-actions-{}", Uuid::new_v4()));
        let _ = fs::create_dir_all(&dir);
        std::env::set_var("OPENFDD_WORKSPACE", &dir);

        let id =
            start_action("fdd_run_all", "Run all", Some(json!({"building": "B1"}))).expect("start");
        let listed = list_actions(10);
        assert_eq!(listed["ok"], true);
        assert_eq!(listed["actions"][0]["id"], id);
        assert_eq!(listed["actions"][0]["status"], "running");

        let done = finish_action(&id, "ok", Some(json!({"rules_ok": 3}))).expect("finish");
        assert_eq!(done.status, "ok");
        assert!(done.duration_ms.is_some());
        assert_eq!(done.detail.as_ref().unwrap()["building"], "B1");
        assert_eq!(done.detail.as_ref().unwrap()["rules_ok"], 3);

        let listed2 = list_actions(10);
        assert_eq!(listed2["actions"][0]["status"], "ok");

        let _ = fs::remove_dir_all(&dir);
        std::env::remove_var("OPENFDD_WORKSPACE");
    }
}
