//! Source registry persisted under workspace/connectors/registry.json.

use crate::connectors::secrets::workspace_dir;
use crate::connectors::types::{SourceHealth, SourceRecord, SourceType};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

pub fn connectors_dir() -> PathBuf {
    workspace_dir().join("connectors")
}

pub fn registry_path() -> PathBuf {
    connectors_dir().join("registry.json")
}

pub fn local_config_dir() -> PathBuf {
    connectors_dir().join("local")
}

pub fn default_registry() -> Value {
    json!({
        "version": 1,
        "sources": [
            {
                "source_id": "openweathermap_oat",
                "source_type": "json_api",
                "display_name": "OpenWeatherMap OAT (example)",
                "enabled": true,
                "site_id": "site:demo",
                "building_id": "building:main",
                "config_path": "examples/connectors/openweathermap.example.toml",
                "health": {"status": "unknown", "message": "not tested"},
                "row_count": 0,
                "mapped_points": 0,
                "unmapped_points": 0
            },
            {
                "source_id": "demo_building_json_feed",
                "source_type": "json_api",
                "display_name": "Demo building JSON feed",
                "enabled": true,
                "site_id": "site:demo",
                "building_id": "building:main",
                "config_path": "examples/connectors/json_api.example.toml",
                "health": {"status": "online", "message": "demo fixture"},
                "row_count": 0,
                "mapped_points": 0,
                "unmapped_points": 0
            },
            {
                "source_id": "demo_portfolio_postgres",
                "source_type": "postgres_readonly",
                "display_name": "Demo portfolio Postgres (read-only template)",
                "enabled": true,
                "site_id": "site:demo",
                "building_id": "building:main",
                "config_path": "examples/connectors/postgres_readonly.example.toml",
                "health": {"status": "degraded", "message": "awaiting local DSN secret"},
                "row_count": 0,
                "mapped_points": 0,
                "unmapped_points": 0
            },
            {
                "source_id": "simulation_bench",
                "source_type": "simulation",
                "display_name": "Simulation source (bench)",
                "enabled": true,
                "site_id": "site:demo",
                "building_id": "building:main",
                "config_path": "examples/connectors/demo_data_lake.example.toml",
                "health": {"status": "online", "message": "deterministic demo rows"},
                "row_count": 0,
                "mapped_points": 0,
                "unmapped_points": 0
            }
        ],
        "mappings": [],
        "backfill_jobs": []
    })
}

pub fn read_registry() -> Value {
    ensure_dirs();
    let path = registry_path();
    if !path.exists() {
        let default = default_registry();
        let _ = write_registry(&default);
        return default;
    }
    let text = fs::read_to_string(&path).unwrap_or_else(|_| "{}".into());
    serde_json::from_str(&text).unwrap_or_else(|_| default_registry())
}

pub fn write_registry(value: &Value) -> Result<(), String> {
    ensure_dirs();
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    fs::write(registry_path(), text).map_err(|e| e.to_string())
}

pub fn list_sources() -> Value {
    let reg = read_registry();
    let sources = reg
        .get("sources")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    json!({"ok": true, "sources": sources})
}

pub fn get_source(source_id: &str) -> Option<Value> {
    read_registry()
        .get("sources")
        .and_then(|v| v.as_array())
        .and_then(|arr| {
            arr.iter()
                .find(|s| s.get("source_id").and_then(|v| v.as_str()) == Some(source_id))
                .cloned()
        })
}

pub fn upsert_source(record: Value) -> Result<Value, String> {
    let source_id = record
        .get("source_id")
        .and_then(|v| v.as_str())
        .ok_or("source_id required")?
        .to_string();
    let source_type = record
        .get("source_type")
        .and_then(|v| v.as_str())
        .ok_or("source_type required")?;
    if SourceType::parse(source_type).is_none() {
        return Err(format!("unsupported source_type: {source_type}"));
    }
    let mut reg = read_registry();
    let sources = reg
        .get_mut("sources")
        .and_then(|v| v.as_array_mut())
        .ok_or("invalid registry")?;
    if let Some(existing) = sources
        .iter_mut()
        .find(|s| s.get("source_id").and_then(|v| v.as_str()) == Some(&source_id))
    {
        *existing = record;
    } else {
        sources.push(record);
    }
    write_registry(&reg)?;
    Ok(json!({"ok": true, "source_id": source_id}))
}

pub fn resolve_config_path(config_path: &str) -> PathBuf {
    let local_name = Path::new(config_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("source");
    let local_override = local_config_dir().join(format!("{local_name}.local.toml"));
    if local_override.exists() {
        return local_override;
    }
    let local_json = local_config_dir().join(format!("{local_name}.local.json"));
    if local_json.exists() {
        return local_json;
    }
    PathBuf::from(config_path)
}

pub fn load_source_config(source_id: &str) -> Result<Value, String> {
    let source = get_source(source_id).ok_or_else(|| format!("unknown source: {source_id}"))?;
    let config_path = source
        .get("config_path")
        .and_then(|v| v.as_str())
        .ok_or("source missing config_path")?;
    let path = resolve_config_file(config_path);
    if !path.exists() {
        return Err(format!("config not found: {}", path.display()));
    }
    let text = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    if path.extension().and_then(|e| e.to_str()) == Some("toml") {
        let parsed: toml::Value = toml::from_str(&text).map_err(|e| e.to_string())?;
        Ok(serde_json::to_value(parsed).map_err(|e| e.to_string())?)
    } else {
        serde_json::from_str(&text).map_err(|e| e.to_string())
    }
}

fn resolve_config_file(config_path: &str) -> PathBuf {
    let local = resolve_config_path(config_path);
    if local.exists() {
        return local;
    }
    for root in repo_roots() {
        let candidate = root.join(config_path);
        if candidate.exists() {
            return candidate;
        }
    }
    PathBuf::from(config_path)
}

pub fn repo_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Ok(v) = std::env::var("OPENFDD_REPO_ROOT") {
        roots.push(PathBuf::from(v));
    }
    roots.push(PathBuf::from("."));
    roots.push(PathBuf::from("/app"));
    roots
}

pub fn update_source_health(
    source_id: &str,
    health: SourceHealth,
    row_count: Option<u64>,
) -> Result<(), String> {
    let mut reg = read_registry();
    let sources = reg
        .get_mut("sources")
        .and_then(|v| v.as_array_mut())
        .ok_or("invalid registry")?;
    for s in sources.iter_mut() {
        if s.get("source_id").and_then(|v| v.as_str()) == Some(source_id) {
            s["health"] = json!({
                "status": health.status,
                "message": health.message,
                "last_error": health.last_error
            });
            if let Some(n) = row_count {
                s["row_count"] = json!(n);
            }
            break;
        }
    }
    write_registry(&reg)
}

pub fn update_source_poll_time(source_id: &str) -> Result<(), String> {
    let mut reg = read_registry();
    let sources = reg
        .get_mut("sources")
        .and_then(|v| v.as_array_mut())
        .ok_or("invalid registry")?;
    let now = chrono::Utc::now().to_rfc3339();
    for s in sources.iter_mut() {
        if s.get("source_id").and_then(|v| v.as_str()) == Some(source_id) {
            s["last_poll_at"] = json!(now);
            break;
        }
    }
    write_registry(&reg)
}

pub fn parse_source_record(v: &Value) -> Option<SourceRecord> {
    serde_json::from_value(v.clone()).ok()
}

fn ensure_dirs() {
    let _ = fs::create_dir_all(connectors_dir());
    let _ = fs::create_dir_all(local_config_dir());
    let _ = fs::create_dir_all(local_config_dir().join("sql"));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_registry_has_multiple_json_sources() {
        let reg = default_registry();
        let sources = reg["sources"].as_array().unwrap();
        let json_count = sources
            .iter()
            .filter(|s| s["source_type"] == "json_api")
            .count();
        assert!(json_count >= 2);
    }
}
