//! Haystack driver facade — config, live client, model import, and API handlers.

use super::client::{
    about as client_about, nav as client_nav, ops as client_ops, read as client_read,
    test_connection,
};
use super::config::{load_config, HaystackConfig};
use super::fixture;
use super::normalize::{
    build_driver_tree, grid_rows, normalize_equipment, normalize_points, normalize_sources,
    poll_samples, rows_to_model_grid,
};
use once_cell::sync::Lazy;
use serde_json::{json, Value};
use std::sync::Mutex;

static MODEL: Lazy<Mutex<Value>> = Lazy::new(|| Mutex::new(fixture::fixture_grid()));

fn with_config<F: FnOnce(&HaystackConfig) -> Value>(f: F) -> Value {
    let cfg = load_config();
    f(&cfg)
}

pub fn status_value() -> Value {
    with_config(|cfg| {
        if !cfg.effective_enabled() {
            return json!({
                "ok": true,
                "enabled": false,
                "status": "disabled",
                "source_id": cfg.source_id,
                "message": "Haystack is disabled or not configured",
                "driver": "haystack",
                "config": cfg.redacted_summary()
            });
        }
        let model = model_value();
        let rows = grid_rows(&model);
        let point_count = rows
            .iter()
            .filter(|r| r.get("point").and_then(|v| v.as_str()) == Some("M"))
            .count();
        json!({
            "ok": true,
            "enabled": true,
            "status": if cfg.is_configured() { "live-or-fixture" } else { "fixture" },
            "source_id": cfg.source_id,
            "message": "Haystack driver ready",
            "driver": "haystack",
            "mode": if cfg.fixture_mode() || !cfg.is_configured() { "fixture" } else { "live" },
            "supported_ops": ["about", "ops", "read", "nav", "poll-once", "import"],
            "points": point_count,
            "config": cfg.redacted_summary()
        })
    })
}

pub fn status_json() -> String {
    serde_json::to_string(&status_value()).unwrap_or_else(|_| "{}".to_string())
}

pub fn about_json() -> String {
    serde_json::to_string(&with_config(client_about)).unwrap_or_else(|_| "{}".to_string())
}

pub fn ops_json() -> String {
    serde_json::to_string(&with_config(client_ops)).unwrap_or_else(|_| "{}".to_string())
}

pub fn test_json() -> String {
    serde_json::to_string(&with_config(test_connection)).unwrap_or_else(|_| "{}".to_string())
}

pub fn nav_json(payload: &Value) -> String {
    serde_json::to_string(&with_config(|cfg| client_nav(cfg, payload)))
        .unwrap_or_else(|_| "{}".to_string())
}

pub fn read_json(payload: &Value) -> String {
    serde_json::to_string(&with_config(|cfg| client_read(cfg, payload)))
        .unwrap_or_else(|_| "{}".to_string())
}

pub fn poll_once_json(payload: &Value) -> String {
    with_config(|cfg| {
        if !cfg.effective_enabled() {
            return json!({
                "ok": true,
                "enabled": false,
                "status": "disabled",
                "source_id": cfg.source_id,
                "message": "Haystack is disabled or not configured"
            });
        }
        let read = client_read(cfg, payload);
        let rows = grid_rows(read.get("records").unwrap_or(&json!({})));
        let samples = poll_samples(&rows, &cfg.source_id);
        json!({
            "ok": true,
            "enabled": true,
            "status": read.get("status").cloned().unwrap_or(json!("live")),
            "source_id": cfg.source_id,
            "message": format!("Polled {} samples", samples.len()),
            "samples": samples,
            "records": read.get("records").cloned().unwrap_or(json!({}))
        })
    })
    .pipe_to_string()
}

pub fn import_json(payload: &Value) -> String {
    with_config(|cfg| {
        if !cfg.effective_enabled() {
            return json!({
                "ok": true,
                "enabled": false,
                "status": "disabled",
                "source_id": cfg.source_id,
                "message": "Haystack is disabled or not configured"
            });
        }
        if !cfg.model_import_enabled {
            return json!({
                "ok": false,
                "enabled": true,
                "status": "disabled",
                "source_id": cfg.source_id,
                "message": "Haystack model import is disabled in config"
            });
        }
        let filter = payload
            .get("filter")
            .and_then(|v| v.as_str())
            .or(cfg.filter.as_deref())
            .unwrap_or("site or equip or point");
        let read_payload =
            json!({"filter": filter, "limit": payload.get("limit").cloned().unwrap_or(json!(500))});
        let read = client_read(cfg, &read_payload);
        let rows = grid_rows(read.get("records").unwrap_or(&json!({})));
        let model = rows_to_model_grid(&rows, &cfg.source_id, &cfg.site_id);
        if let Ok(mut guard) = MODEL.lock() {
            *guard = model.clone();
        }
        json!({
            "ok": true,
            "enabled": true,
            "status": "imported",
            "source_id": cfg.source_id,
            "message": format!("Imported {} Haystack records", rows.len()),
            "imported": rows.len(),
            "preserve_ids": true,
            "records": model
        })
    })
    .pipe_to_string()
}

pub fn driver_tree_json() -> String {
    with_config(|cfg| {
        if !cfg.effective_enabled() {
            return json!({
                "ok": true,
                "enabled": false,
                "status": "disabled",
                "source_id": cfg.source_id,
                "message": "Haystack is disabled or not configured",
                "devices": []
            });
        }
        let model = model_value();
        let rows = grid_rows(&model);
        let mut tree = build_driver_tree(&rows, &cfg.source_id, &cfg.base_url);
        if let Some(obj) = tree.as_object_mut() {
            obj.insert("enabled".to_string(), json!(true));
            obj.insert("status".to_string(), json!("ready"));
        }
        tree
    })
    .pipe_to_string()
}

pub fn model_value() -> Value {
    MODEL
        .lock()
        .map(|g| g.clone())
        .unwrap_or_else(|_| fixture::fixture_grid())
}

pub fn model_json() -> String {
    serde_json::to_string_pretty(&model_value()).unwrap_or_else(|_| "{}".to_string())
}

pub fn sources_json() -> String {
    with_config(|cfg| {
        let rows = grid_rows(&model_value());
        json!({
            "ok": true,
            "enabled": cfg.effective_enabled(),
            "status": if cfg.effective_enabled() { "ready" } else { "disabled" },
            "source_id": cfg.source_id,
            "records": normalize_sources(&rows, &cfg.source_id, &cfg.source_type)
        })
    })
    .pipe_to_string()
}

pub fn equipment_json() -> String {
    with_config(|cfg| {
        let rows = grid_rows(&model_value());
        json!({
            "ok": true,
            "enabled": cfg.effective_enabled(),
            "status": if cfg.effective_enabled() { "ready" } else { "disabled" },
            "source_id": cfg.source_id,
            "records": normalize_equipment(&rows, &cfg.site_id)
        })
    })
    .pipe_to_string()
}

pub fn points_json() -> String {
    with_config(|cfg| {
        let rows = grid_rows(&model_value());
        json!({
            "ok": true,
            "enabled": cfg.effective_enabled(),
            "status": if cfg.effective_enabled() { "ready" } else { "disabled" },
            "source_id": cfg.source_id,
            "records": normalize_points(&rows, &cfg.source_id)
        })
    })
    .pipe_to_string()
}

trait PipeToString {
    fn pipe_to_string(self) -> String;
}

impl PipeToString for Value {
    fn pipe_to_string(self) -> String {
        serde_json::to_string(&self).unwrap_or_else(|_| "{}".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_status_is_clean() {
        let cfg_path = std::env::temp_dir().join(format!(
            "openfdd-haystack-disabled-{}.toml",
            std::process::id()
        ));
        std::fs::write(
            &cfg_path,
            "[haystack]\nenabled = true\nbase_url = \"http://example/haystack\"\n",
        )
        .unwrap();
        std::env::set_var("OPENFDD_HAYSTACK_CONFIG", cfg_path.to_string_lossy().to_string());
        std::env::set_var("OPENFDD_HAYSTACK_DISABLED", "1");
        std::env::remove_var("OPENFDD_HAYSTACK_FIXTURE");
        std::env::remove_var("OPENFDD_HAYSTACK_BASE");
        let st: Value = serde_json::from_str(&status_json()).unwrap();
        assert_eq!(st["enabled"], false);
        assert_eq!(st["status"], "disabled");
        std::env::remove_var("OPENFDD_HAYSTACK_DISABLED");
        std::env::remove_var("OPENFDD_HAYSTACK_CONFIG");
        let _ = std::fs::remove_file(cfg_path);
    }

    #[test]
    fn fixture_import_populates_model() {
        std::env::set_var("OPENFDD_HAYSTACK_FIXTURE", "1");
        std::env::remove_var("OPENFDD_HAYSTACK_DISABLED");
        let out: Value = serde_json::from_str(&import_json(&json!({}))).unwrap();
        assert_eq!(out["ok"], true);
        assert!(out["imported"].as_u64().unwrap_or(0) > 0);
        std::env::remove_var("OPENFDD_HAYSTACK_FIXTURE");
    }

    #[test]
    fn empty_nav_read_do_not_panic() {
        std::env::set_var("OPENFDD_HAYSTACK_FIXTURE", "1");
        std::env::remove_var("OPENFDD_HAYSTACK_DISABLED");
        let nav: Value = serde_json::from_str(&nav_json(&json!({}))).unwrap();
        assert_eq!(nav["ok"], true);
        let read: Value = serde_json::from_str(&read_json(&json!({"ids": []}))).unwrap();
        assert_eq!(read["ok"], true);
        std::env::remove_var("OPENFDD_HAYSTACK_FIXTURE");
    }
}
