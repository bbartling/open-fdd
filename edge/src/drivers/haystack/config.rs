//! Haystack driver configuration (TOML + environment overrides).

use serde::{Deserialize, Serialize};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const DEFAULT_CONFIG_PATH: &str = "workspace/haystack/local.nhaystack.toml";

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HaystackConfigFile {
    pub haystack: HaystackConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HaystackConfig {
    #[serde(default = "default_id")]
    pub id: String,
    #[serde(default = "default_name")]
    pub name: String,
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub base_url: String,
    #[serde(default = "default_auth_mode")]
    pub auth_mode: String,
    #[serde(default)]
    pub username_env: Option<String>,
    #[serde(default)]
    pub password_env: Option<String>,
    #[serde(default)]
    pub username: Option<String>,
    #[serde(default)]
    pub password: Option<String>,
    #[serde(default = "default_true")]
    pub tls_verify: bool,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
    #[serde(default = "default_poll_interval")]
    pub poll_interval_seconds: u64,
    #[serde(default)]
    pub nav_root: Option<String>,
    #[serde(default)]
    pub filter: Option<String>,
    #[serde(default = "default_site_id")]
    pub site_id: String,
    #[serde(default = "default_source_id")]
    pub source_id: String,
    #[serde(default = "default_source_type")]
    pub source_type: String,
    #[serde(default = "default_true")]
    pub model_import_enabled: bool,
    #[serde(default = "default_true")]
    pub polling_enabled: bool,
}

fn default_id() -> String {
    "local-niagara-nhaystack".to_string()
}
fn default_name() -> String {
    "Local Niagara nHaystack".to_string()
}
fn default_auth_mode() -> String {
    "basic".to_string()
}
fn default_true() -> bool {
    true
}
fn default_timeout() -> u64 {
    15
}
fn default_poll_interval() -> u64 {
    60
}
fn default_site_id() -> String {
    "site:local".to_string()
}
fn default_source_id() -> String {
    "source:local-niagara-haystack".to_string()
}
fn default_source_type() -> String {
    "haystack".to_string()
}

impl Default for HaystackConfig {
    fn default() -> Self {
        Self {
            id: default_id(),
            name: default_name(),
            enabled: false,
            base_url: String::new(),
            auth_mode: default_auth_mode(),
            username_env: None,
            password_env: None,
            username: None,
            password: None,
            tls_verify: true,
            timeout_seconds: default_timeout(),
            poll_interval_seconds: default_poll_interval(),
            nav_root: None,
            filter: None,
            site_id: default_site_id(),
            source_id: default_source_id(),
            source_type: default_source_type(),
            model_import_enabled: true,
            polling_enabled: true,
        }
    }
}

impl HaystackConfig {
    pub fn is_configured(&self) -> bool {
        self.enabled && !self.base_url.trim().is_empty()
    }

    pub fn fixture_mode(&self) -> bool {
        env::var("OPENFDD_HAYSTACK_FIXTURE")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false)
    }

    pub fn effective_enabled(&self) -> bool {
        self.is_configured() || self.fixture_mode()
    }

    pub fn resolve_credentials(&self) -> (Option<String>, Option<String>) {
        let user = env::var("OPENFDD_HAYSTACK_USER")
            .ok()
            .or_else(|| self.username.clone())
            .or_else(|| self.username_env.as_ref().and_then(|k| env::var(k).ok()));
        let pass = env::var("OPENFDD_HAYSTACK_PASS")
            .ok()
            .or_else(|| self.password.clone())
            .or_else(|| self.password_env.as_ref().and_then(|k| env::var(k).ok()));
        (user, pass)
    }

    pub fn redacted_summary(&self) -> serde_json::Value {
        let (user, pass) = self.resolve_credentials();
        serde_json::json!({
            "id": self.id,
            "name": self.name,
            "enabled": self.effective_enabled(),
            "configured": self.is_configured(),
            "base_url": if self.base_url.is_empty() { serde_json::Value::Null } else { serde_json::json!(self.base_url) },
            "auth_mode": self.auth_mode,
            "username": user.as_ref().map(|u| redact_user(u)),
            "password_set": pass.is_some(),
            "tls_verify": self.tls_verify,
            "timeout_seconds": self.timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "nav_root": self.nav_root,
            "filter": self.filter,
            "site_id": self.site_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "model_import_enabled": self.model_import_enabled,
            "polling_enabled": self.polling_enabled,
            "fixture_mode": self.fixture_mode(),
        })
    }
}

pub fn redact_user(user: &str) -> String {
    if user.len() <= 2 {
        return "*".repeat(user.len());
    }
    format!("{}***", &user[..1])
}

pub fn redact_secret(value: &str) -> String {
    if value.is_empty() {
        return String::new();
    }
    "***".to_string()
}

pub fn config_path() -> PathBuf {
    env::var("OPENFDD_HAYSTACK_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(DEFAULT_CONFIG_PATH))
}

pub fn load_config() -> HaystackConfig {
    let mut cfg = load_config_from_path(&config_path()).unwrap_or_default();
    let profile = crate::validation::profile::active_profile();
    if crate::validation::profile::is_haystack_configured(&profile) {
        if cfg.base_url.trim().is_empty() {
            cfg.base_url = profile.haystack_base_url.clone();
        }
        if !profile.haystack_username.is_empty()
            && cfg.username.as_ref().is_none_or(String::is_empty)
        {
            cfg.username = Some(profile.haystack_username.clone());
        }
        if !profile.haystack_password.is_empty()
            && cfg.password.as_ref().is_none_or(String::is_empty)
        {
            cfg.password = Some(profile.haystack_password.clone());
        }
        if !profile.haystack_source_id.is_empty() {
            cfg.source_id = profile.haystack_source_id.clone();
        }
        cfg.enabled = true;
    }
    if let Ok(base) = env::var("OPENFDD_HAYSTACK_BASE") {
        if !base.trim().is_empty() {
            cfg.base_url = base;
            cfg.enabled = true;
        }
    }
    if env::var("OPENFDD_HAYSTACK_ENABLED")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
    {
        cfg.enabled = true;
    }
    if env::var("OPENFDD_HAYSTACK_DISABLED")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
    {
        cfg.enabled = false;
    }
    cfg
}

pub fn load_config_from_path(path: &Path) -> Option<HaystackConfig> {
    let raw = fs::read_to_string(path).ok()?;
    let parsed: HaystackConfigFile = toml::from_str(&raw).ok()?;
    Some(parsed.haystack)
}

pub fn save_config(cfg: &HaystackConfig) -> Result<(), String> {
    let path = config_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let file = HaystackConfigFile {
        haystack: cfg.clone(),
    };
    let text = toml::to_string_pretty(&file).map_err(|e| e.to_string())?;
    fs::write(&path, text).map_err(|e| e.to_string())
}

pub fn apply_save_payload(base: &HaystackConfig, payload: &serde_json::Value) -> HaystackConfig {
    let mut cfg = base.clone();
    if let Some(v) = payload.get("base_url").and_then(|v| v.as_str()) {
        cfg.base_url = v.trim().to_string();
        cfg.enabled = !cfg.base_url.is_empty();
    }
    if let Some(v) = payload.get("username").and_then(|v| v.as_str()) {
        if !v.is_empty() {
            cfg.username = Some(v.to_string());
        }
    }
    if let Some(v) = payload.get("password").and_then(|v| v.as_str()) {
        if !v.is_empty() {
            cfg.password = Some(v.to_string());
        }
    }
    if let Some(v) = payload.get("enabled").and_then(|v| v.as_bool()) {
        cfg.enabled = v;
    }
    if let Some(v) = payload.get("tls_verify").and_then(|v| v.as_bool()) {
        cfg.tls_verify = v;
    }
    if let Some(v) = payload.get("source_id").and_then(|v| v.as_str()) {
        if !v.is_empty() {
            cfg.source_id = v.to_string();
        }
    }
    cfg
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_is_disabled() {
        let cfg = HaystackConfig::default();
        assert!(!cfg.effective_enabled());
    }

    #[test]
    fn redact_user_masks_value() {
        assert_eq!(redact_user("ab"), "**");
        assert!(redact_user("integrator").contains("***"));
    }

    #[test]
    fn env_overrides_base_url() {
        let cfg_path =
            std::env::temp_dir().join(format!("openfdd-haystack-test-{}.toml", std::process::id()));
        std::fs::write(&cfg_path, "[haystack]\nenabled = false\nbase_url = \"\"\n").unwrap();
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
        let _ = std::fs::remove_file(cfg_path);
    }
}
