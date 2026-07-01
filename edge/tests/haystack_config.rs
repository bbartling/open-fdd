//! Haystack config/driver env tests (isolated — avoids lib+bin unit test duplicate races).

use open_fdd_edge_prototype::drivers::haystack::config::{load_config, HaystackConfig};
use open_fdd_edge_prototype::drivers::haystack::driver::{import_json, status_json};
use open_fdd_edge_prototype::test_support::workspace_env_lock;
use serde_json::{json, Value};
use std::env;
use std::fs;

#[test]
fn default_config_is_disabled() {
    let _lock = workspace_env_lock();
    let cfg = HaystackConfig::default();
    assert!(!cfg.effective_enabled());
}

#[test]
fn env_overrides_base_url() {
    let _lock = workspace_env_lock();
    let cfg_path =
        std::env::temp_dir().join(format!("openfdd-haystack-test-{}.toml", std::process::id()));
    fs::write(&cfg_path, "[haystack]\nenabled = false\nbase_url = \"\"\n").unwrap();
    let key_base = "OPENFDD_HAYSTACK_BASE";
    let key_cfg = "OPENFDD_HAYSTACK_CONFIG";
    let prev_base = env::var(key_base).ok();
    let prev_cfg = env::var(key_cfg).ok();
    env::set_var(key_cfg, cfg_path.to_string_lossy().to_string());
    env::set_var(key_base, "http://example/haystack");
    env::remove_var("OPENFDD_HAYSTACK_DISABLED");
    let cfg = load_config();
    assert_eq!(cfg.base_url, "http://example/haystack");
    assert!(cfg.enabled);
    match prev_base {
        Some(v) => env::set_var(key_base, v),
        None => env::remove_var(key_base),
    }
    match prev_cfg {
        Some(v) => env::set_var(key_cfg, v),
        None => env::remove_var(key_cfg),
    }
    let _ = fs::remove_file(cfg_path);
}

#[test]
fn disabled_status_is_clean() {
    let _lock = workspace_env_lock();
    let cfg_path = std::env::temp_dir().join(format!(
        "openfdd-haystack-disabled-{}.toml",
        std::process::id()
    ));
    fs::write(
        &cfg_path,
        "[haystack]\nenabled = true\nbase_url = \"http://example/haystack\"\n",
    )
    .unwrap();
    env::set_var(
        "OPENFDD_HAYSTACK_CONFIG",
        cfg_path.to_string_lossy().to_string(),
    );
    env::set_var("OPENFDD_HAYSTACK_DISABLED", "1");
    env::remove_var("OPENFDD_HAYSTACK_FIXTURE");
    env::remove_var("OPENFDD_HAYSTACK_BASE");
    let st: Value = serde_json::from_str(&status_json()).unwrap();
    assert_eq!(st["enabled"], false);
    assert_eq!(st["status"], "disabled");
    env::remove_var("OPENFDD_HAYSTACK_DISABLED");
    env::remove_var("OPENFDD_HAYSTACK_CONFIG");
    let _ = fs::remove_file(cfg_path);
}

#[test]
fn flat_root_toml_parses_without_haystack_section() {
    let _lock = workspace_env_lock();
    let cfg_path =
        std::env::temp_dir().join(format!("openfdd-haystack-flat-{}.toml", std::process::id()));
    fs::write(
        &cfg_path,
        "enabled = true\nbase_url = \"https://station.example/haystack\"\n",
    )
    .unwrap();
    let key_cfg = "OPENFDD_HAYSTACK_CONFIG";
    let prev_cfg = env::var(key_cfg).ok();
    env::set_var(key_cfg, cfg_path.to_string_lossy().to_string());
    env::remove_var("OPENFDD_HAYSTACK_DISABLED");
    env::remove_var("OPENFDD_HAYSTACK_BASE");
    let cfg = load_config();
    assert_eq!(cfg.base_url, "https://station.example/haystack");
    assert!(cfg.enabled);
    match prev_cfg {
        Some(v) => env::set_var(key_cfg, v),
        None => env::remove_var(key_cfg),
    }
    let _ = fs::remove_file(cfg_path);
}

#[test]
fn fixture_import_populates_model() {
    let _lock = workspace_env_lock();
    env::set_var("OPENFDD_HAYSTACK_FIXTURE", "1");
    env::remove_var("OPENFDD_HAYSTACK_DISABLED");
    let out: Value = serde_json::from_str(&import_json(&json!({}))).unwrap();
    assert_eq!(out["ok"], true);
    assert!(out["imported"].as_u64().unwrap_or(0) > 0);
    env::remove_var("OPENFDD_HAYSTACK_FIXTURE");
}
