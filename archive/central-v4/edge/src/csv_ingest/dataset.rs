//! Dataset registry (metadata only; sample rows live in Timescale).

use chrono::Utc;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

pub fn datasets_root() -> PathBuf {
    crate::historian::store::workspace_dir().join("data/datasets")
}

pub fn registry_path() -> PathBuf {
    datasets_root().join("registry.json")
}

pub fn dataset_dir(id: &str) -> PathBuf {
    datasets_root().join(sanitize_id(id))
}

fn sanitize_id(id: &str) -> String {
    id.chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect()
}

pub fn load_registry() -> Value {
    let path = registry_path();
    if !path.exists() {
        return json!({"ok": true, "datasets": []});
    }
    fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| json!({"ok": true, "datasets": []}))
}

fn save_registry(reg: &Value) -> Result<(), String> {
    fs::create_dir_all(datasets_root()).map_err(|e| e.to_string())?;
    fs::write(
        registry_path(),
        serde_json::to_string_pretty(reg).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

pub fn list_datasets() -> Value {
    let reg = load_registry();
    json!({
        "ok": true,
        "datasets": reg.get("datasets").cloned().unwrap_or(json!([]))
    })
}

/// Dataset metadata. Package rows live in the Timescale historian only, so no
/// row pages are stored beside the registry.
pub fn preview_dataset(dataset_id: &str, offset: u64, limit: u64) -> Value {
    let id = sanitize_id(dataset_id);
    let meta_path = dataset_dir(&id).join("metadata.json");
    let meta: Option<Value> = fs::read_to_string(meta_path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .or_else(|| {
            load_registry()
                .get("datasets")
                .and_then(|d| d.as_array())
                .and_then(|arr| {
                    arr.iter()
                        .find(|d| d.get("id").and_then(|v| v.as_str()) == Some(id.as_str()))
                        .cloned()
                })
        });
    match meta {
        Some(meta) => json!({
            "ok": true,
            "dataset_id": id,
            "metadata": meta,
            "offset": offset,
            "limit": limit,
            "rows": [],
            "rows_source": "timescale",
        }),
        None => json!({"ok": false, "error": "dataset not found"}),
    }
}

pub fn delete_dataset(dataset_id: &str) -> Result<(), String> {
    let id = sanitize_id(dataset_id);
    let dir = dataset_dir(&id);
    if dir.exists() {
        fs::remove_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mut reg = load_registry();
    if let Some(arr) = reg.get_mut("datasets").and_then(|d| d.as_array_mut()) {
        arr.retain(|d| d.get("id").and_then(|v| v.as_str()) != Some(id.as_str()));
        save_registry(&reg)?;
    }
    // Package / Haystack building cleanup: csv_buildings + parquet partition.
    let ws = crate::historian::store::workspace_dir();
    let csv_buildings = ws.join("data").join("csv_buildings").join(&id);
    // Collect equipment ids before wiping the package tree so session_config can be trimmed.
    let equipment_ids = list_equipment_dirs(&csv_buildings);
    crate::fdd::session_config::strip_site_from_session_config(&id, &equipment_ids)?;
    if csv_buildings.exists() {
        let _ = fs::remove_dir_all(&csv_buildings);
    }
    let parquet_roots = [
        fdd_store::local_file_root_from_env(),
        Some(ws.join(".cache/parquet")),
        Some(PathBuf::from(".cache/parquet")),
    ];
    for root in parquet_roots.into_iter().flatten() {
        let part = root.join(format!("building={id}"));
        if part.exists() {
            let _ = fs::remove_dir_all(&part);
        }
    }
    // OFDD-073: purge scoped FDD rule_results so DELETE site leaves no ghost FAULTs.
    let rule_results_roots = [
        std::env::var("OPENFDD_RULE_RESULTS_DIR")
            .ok()
            .map(PathBuf::from),
        Some(ws.join(".cache/rule_results")),
        Some(PathBuf::from(".cache/rule_results")),
    ];
    for root in rule_results_roots.into_iter().flatten() {
        let part = root.join(format!("building={id}"));
        if part.exists() {
            let _ = fs::remove_dir_all(&part);
        }
    }
    Ok(())
}

/// Best-effort equipment folder names under a materialized package building root.
fn list_equipment_dirs(building_root: &Path) -> Vec<String> {
    let mut ids = Vec::new();
    if !building_root.is_dir() {
        return ids;
    }
    for e in walkdir::WalkDir::new(building_root)
        .min_depth(1)
        .max_depth(3)
        .into_iter()
        .flatten()
    {
        if e.file_type().is_dir()
            && (e.path().join("history_wide.csv").is_file()
                || e.path().join("columns.csv").is_file())
        {
            if let Some(name) = e.file_name().to_str() {
                if name != "weather" {
                    ids.push(name.to_string());
                }
            }
        }
    }
    ids.sort();
    ids.dedup();
    ids
}

/// Register a package building id in the dataset registry (for Delete site by Haystack name).
pub fn register_package_dataset(
    building_id: &str,
    row_count: u64,
    equipment_count: usize,
    extra: &Value,
) -> Result<(), String> {
    let id = sanitize_id(building_id);
    if id.is_empty() {
        return Err("invalid building id".into());
    }
    let metadata = json!({
        "id": id,
        "row_count": row_count,
        "equipment_count": equipment_count,
        "source": "openfdd_package_v1",
        "created_at": Utc::now().to_rfc3339(),
        "extra": extra,
    });
    let mut reg = load_registry();
    let datasets = reg
        .as_object_mut()
        .and_then(|o| o.get_mut("datasets"))
        .and_then(|d| d.as_array_mut())
        .ok_or("registry corrupt")?;
    datasets.retain(|d| d.get("id").and_then(|v| v.as_str()) != Some(id.as_str()));
    datasets.push(metadata);
    save_registry(&reg)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    #[test]
    fn delete_dataset_purges_rule_results_building_partition() {
        let _guard = crate::test_support::workspace_env_lock();
        let tmp = TempDir::new().unwrap();
        // isolate workspace + CWD-relative rule_results roots used by delete_dataset
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        let prev_cwd = std::env::current_dir().ok();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.path());
        std::env::set_current_dir(tmp.path()).unwrap();

        let id = "BUILDING_50";
        let results = tmp
            .path()
            .join(".cache/rule_results")
            .join(format!("building={id}"));
        fs::create_dir_all(&results).unwrap();
        let mut f = fs::File::create(results.join("SV-STALE.json")).unwrap();
        writeln!(f, "{{\"fault_hours\": 1.0}}").unwrap();

        let pq = tmp
            .path()
            .join(".cache/parquet")
            .join(format!("building={id}"));
        fs::create_dir_all(&pq).unwrap();
        fs::write(pq.join("marker"), b"x").unwrap();

        // also leave a sibling building so we prove scoped purge
        let keep = tmp
            .path()
            .join(".cache/rule_results")
            .join("building=BUILDING_100");
        fs::create_dir_all(&keep).unwrap();
        fs::write(keep.join("keep.json"), b"{}").unwrap();

        delete_dataset(id).expect("delete ok");
        assert!(!results.exists(), "BUILDING_50 rule_results must be purged");
        assert!(!pq.exists(), "BUILDING_50 parquet partition must be purged");
        assert!(keep.exists(), "BUILDING_100 rule_results must remain");

        if let Some(ws) = prev_ws {
            std::env::set_var("OPENFDD_WORKSPACE", ws);
        } else {
            std::env::remove_var("OPENFDD_WORKSPACE");
        }
        if let Some(cwd) = prev_cwd {
            let _ = std::env::set_current_dir(cwd);
        }
    }

    #[test]
    fn delete_dataset_purges_parquet_partition() {
        let _guard = crate::test_support::workspace_env_lock();
        let tmp = TempDir::new().unwrap();
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        let prev_pq = std::env::var("OPENFDD_PARQUET_ROOT").ok();
        let prev_storage = std::env::var("OPENFDD_STORAGE_URL").ok();
        std::env::remove_var("OPENFDD_STORAGE_URL");
        std::env::set_var("OPENFDD_WORKSPACE", tmp.path());
        let pq = tmp.path().join(".cache/parquet");
        std::env::set_var("OPENFDD_PARQUET_ROOT", &pq);

        let id = "SITE_MQTT";
        let part = pq.join(format!("building={id}"));
        fs::create_dir_all(&part).unwrap();
        fs::write(part.join("marker.parquet"), b"x").unwrap();
        assert!(part.exists());

        delete_dataset(id).expect("delete ok");
        assert!(!part.exists(), "parquet building partition must be purged");

        if let Some(ws) = prev_ws {
            std::env::set_var("OPENFDD_WORKSPACE", ws);
        } else {
            std::env::remove_var("OPENFDD_WORKSPACE");
        }
        if let Some(p) = prev_pq {
            std::env::set_var("OPENFDD_PARQUET_ROOT", p);
        } else {
            std::env::remove_var("OPENFDD_PARQUET_ROOT");
        }
        if let Some(s) = prev_storage {
            std::env::set_var("OPENFDD_STORAGE_URL", s);
        } else {
            std::env::remove_var("OPENFDD_STORAGE_URL");
        }
    }
}
