//! Persisted Haystack grid (optional override of fixture MODEL_JSON).

use crate::validation::profile::workspace_dir;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

pub fn haystack_grid_path() -> PathBuf {
    workspace_dir().join("data/model/haystack_grid.json")
}

pub fn load_haystack_grid() -> Option<Value> {
    let path = haystack_grid_path();
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

pub fn save_haystack_grid(grid: &Value) -> std::io::Result<PathBuf> {
    let path = haystack_grid_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&path, serde_json::to_string_pretty(grid).unwrap_or_else(|_| "{}".into()))?;
    Ok(path)
}

pub fn haystack_model_value() -> Value {
    load_haystack_grid().unwrap_or_else(|| {
        serde_json::from_str(crate::drivers::haystack::MODEL_JSON)
            .unwrap_or(json!({"meta":{"ver":"3.0","mode":"fixture"},"cols":[],"rows":[]}))
    })
}

pub fn haystack_model_json_string() -> String {
    haystack_model_value().to_string()
}
