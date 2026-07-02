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
    fs::write(
        &path,
        serde_json::to_string_pretty(grid).unwrap_or_else(|_| "{}".into()),
    )?;
    crate::model::rdf::invalidate_store();
    Ok(path)
}

pub fn empty_haystack_grid() -> Value {
    json!({
        "meta": {"ver": "3.0", "mode": "empty"},
        "cols": [],
        "rows": []
    })
}

pub fn default_local_haystack_grid() -> Value {
    json!({
        "meta": {"ver": "3.0", "mode": "default-local"},
        "cols": [
            {"name": "id"},
            {"name": "dis"},
            {"name": "site"},
            {"name": "equip"},
            {"name": "siteRef"}
        ],
        "rows": [
            {"id": "site:local", "dis": "Local site", "site": "M"},
            {"id": "equip:local-test-equipment", "dis": "Local test equipment", "equip": "M", "siteRef": "site:local"}
        ]
    })
}

pub fn haystack_model_value() -> Value {
    if haystack_grid_path().exists() {
        return load_haystack_grid().unwrap_or_else(empty_haystack_grid);
    }
    default_local_haystack_grid()
}

pub fn haystack_model_json_string() -> String {
    haystack_model_value().to_string()
}
