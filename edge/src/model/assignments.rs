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

pub fn save_from_request(body: &Value) -> Value {
    if body.get("confirm").and_then(|v| v.as_bool()) != Some(true) {
        return json!({
            "ok": false,
            "error": "confirm:true required to save Haystack assignments"
        });
    }
    let doc = if body.get("points").is_some() || body.get("fault_equation_bindings").is_some() {
        body.clone()
    } else if let Some(inner) = body.get("assignments") {
        inner.clone()
    } else {
        return json!({
            "ok": false,
            "error": "assignments document required (points / fault_equation_bindings or assignments wrapper)"
        });
    };
    match save_assignments_value(&doc) {
        Ok(path) => json!({
            "ok": true,
            "saved": true,
            "scope": "haystack-assignment",
            "path": path.display().to_string()
        }),
        Err(err) => json!({"ok": false, "error": err.to_string()}),
    }
}

pub fn save_assignment_json() -> &'static str {
    r#"{"ok":false,"error":"POST JSON body with assignments and confirm:true"}"#
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::with_temp_workspace;
    use serde_json::json;

    #[test]
    fn save_requires_confirm() {
        let out = save_from_request(&json!({"points": []}));
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(false));
    }

    #[test]
    fn save_persists_assignments() {
        with_temp_workspace(|_| {
            let doc = json!({
                "confirm": true,
                "points": [{"point_id": "p1", "haystack_ref": "point:test"}]
            });
            let out = save_from_request(&doc);
            assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
            let loaded = load_assignments_value();
            assert_eq!(loaded["points"].as_array().map(|a| a.len()), Some(1));
        });
    }
}
