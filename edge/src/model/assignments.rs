//! Protocol-agnostic Haystack assignment layer.
//!
//! Driver points are assigned to Haystack point refs. Fault equations,
//! historian storage, external refs, and algorithms bind to Haystack refs.

use crate::validation::profile::workspace_dir;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

pub fn assignments_path() -> PathBuf {
    workspace_dir().join("data/model/assignments.json")
}

pub fn empty_assignments_value() -> Value {
    json!({
        "ok": true,
        "model": "haystack-only",
        "assignment_policy": "Driver points bind to Haystack IDs; FDD rules and storage refs use Haystack refs.",
        "points": [],
        "fault_equation_bindings": [],
        "algorithm_bindings": []
    })
}

pub fn load_assignments_value() -> Value {
    let path = assignments_path();
    let text = match fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return empty_assignments_value(),
    };
    serde_json::from_str(&text).unwrap_or_else(|_| empty_assignments_value())
}

pub fn save_assignments_value(value: &Value) -> std::io::Result<PathBuf> {
    let path = assignments_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(
        &path,
        serde_json::to_string_pretty(value).unwrap_or_else(|_| "{}".into()),
    )?;
    Ok(path)
}

pub fn assignments_json_string() -> String {
    load_assignments_value().to_string()
}

pub fn save_assignment_json() -> &'static str {
    r#"{"ok":true,"saved":true,"scope":"haystack-assignment","path":"workspace/data/model/assignments.json"}"#
}

pub fn resolve_json() -> &'static str {
    r#"{"ok":true,"haystack_id":null,"selected_binding":null,"storage_ref":null,"message":"No assignment resolved — model is empty or point not found"}"#
}

pub fn algorithm_bindings_json_string() -> String {
    let v = load_assignments_value();
    json!({
        "ok": true,
        "algorithm_bindings": v.get("algorithm_bindings").cloned().unwrap_or(json!([]))
    })
    .to_string()
}
