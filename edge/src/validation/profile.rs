//! Smoke / validation profile loaded from env and optional local TOML (gitignored).

use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct BacnetPointRole {
    pub name: String,
    pub object_instance: u32,
    pub fdd_input: String,
}

#[derive(Clone, Debug)]
pub struct SmokeProfile {
    pub profile_id: String,
    pub source_id: String,
    pub source_type: String,
    pub device_instance: u32,
    pub equipment_id: String,
    pub poll_interval_seconds: u64,
    pub duration_hours: f64,
    pub confirmation_minutes: i64,
    pub historian_subdir: String,
    pub artifact_subdir: String,
    pub fdd_rule_id: String,
    pub bacnet_points: Vec<BacnetPointRole>,
    pub modbus_host: String,
    pub modbus_port: u16,
    pub modbus_unit_id: u8,
    pub modbus_register: u16,
    pub modbus_enabled: bool,
    pub modbus_poll_interval_seconds: u64,
    pub haystack_enabled: bool,
    pub haystack_base_url: String,
    pub haystack_username: String,
    pub haystack_password: String,
    pub haystack_source_id: String,
    pub haystack_poll_interval_seconds: u64,
    pub csv_enabled: bool,
    pub csv_source_id: String,
    pub csv_interval_seconds: u64,
    pub json_api_enabled: bool,
    pub json_api_url: Option<String>,
    pub json_api_poll_interval_seconds: u64,
    pub duration_minutes: u64,
}

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

pub fn validation_profile_path() -> PathBuf {
    if let Ok(p) = env::var("OPENFDD_VALIDATION_PROFILE") {
        return PathBuf::from(p);
    }
    profile_path()
}

pub fn profile_path() -> PathBuf {
    if let Ok(p) = env::var("OPENFDD_SMOKE_PROFILE_PATH") {
        return PathBuf::from(p);
    }
    let id =
        env::var("OPENFDD_SMOKE_PROFILE").unwrap_or_else(|_| "local_validation_profile".into());
    workspace_dir()
        .join("smoke-profiles/local")
        .join(format!("{id}.local.toml"))
}

pub fn is_modbus_configured(p: &SmokeProfile) -> bool {
    p.modbus_enabled && !p.modbus_host.trim().is_empty()
}

pub fn is_haystack_configured(p: &SmokeProfile) -> bool {
    p.haystack_enabled && !p.haystack_base_url.trim().is_empty()
}

pub fn active_profile() -> SmokeProfile {
    let mut profile = from_env_defaults();
    if let Ok(text) = fs::read_to_string(profile_path()) {
        apply_toml(&mut profile, &text);
    }
    apply_env_overrides(&mut profile);
    profile
}

fn from_env_defaults() -> SmokeProfile {
    SmokeProfile {
        profile_id: "local_validation".into(),
        source_id: "source:validation".into(),
        source_type: "bacnet".into(),
        device_instance: 0,
        equipment_id: "equip:local-test-equipment".into(),
        poll_interval_seconds: 300,
        duration_hours: 6.0,
        confirmation_minutes: 5,
        historian_subdir: "validation".into(),
        artifact_subdir: "live_fdd_validation".into(),
        fdd_rule_id: "oa_temp_out_of_range".into(),
        bacnet_points: Vec::new(),
        modbus_host: String::new(),
        modbus_port: 1502,
        modbus_unit_id: 1,
        modbus_register: 30001,
        modbus_enabled: false,
        modbus_poll_interval_seconds: 300,
        haystack_enabled: false,
        haystack_base_url: String::new(),
        haystack_username: String::new(),
        haystack_password: String::new(),
        haystack_source_id: "source:local-haystack".into(),
        haystack_poll_interval_seconds: 300,
        csv_enabled: true,
        csv_source_id: "source:validation-csv".into(),
        csv_interval_seconds: 300,
        json_api_enabled: false,
        json_api_url: None,
        json_api_poll_interval_seconds: 300,
        duration_minutes: 60,
    }
}

fn apply_env_overrides(p: &mut SmokeProfile) {
    if let Ok(v) = env::var("OPENFDD_SMOKE_PROFILE") {
        if !v.is_empty() {
            p.profile_id = v;
        }
    }
    if let Ok(v) = env::var("OPENFDD_SMOKE_DEVICE_INSTANCE") {
        if let Ok(inst) = v.parse::<u32>() {
            p.device_instance = inst;
        }
    }
    if let Ok(v) = env::var("OPENFDD_SMOKE_DURATION_HOURS") {
        if let Ok(h) = v.parse::<f64>() {
            p.duration_hours = h;
        }
    }
    if let Ok(v) = env::var("OPENFDD_SMOKE_INTERVAL_SECONDS") {
        if let Ok(s) = v.parse::<u64>() {
            p.poll_interval_seconds = s;
        }
    }
    if let Ok(v) = env::var("OPENFDD_HISTORIAN_SUBDIR") {
        if !v.is_empty() {
            p.historian_subdir = v;
        }
    }
    if let Ok(v) = env::var("OPENFDD_SMOKE_JSON_API_URL") {
        if !v.is_empty() {
            p.json_api_url = Some(v);
            p.json_api_enabled = true;
        }
    }
    if let Ok(v) = env::var("OPENFDD_MODBUS_HOST") {
        if !v.is_empty() {
            p.modbus_host = v;
            p.modbus_enabled = true;
        }
    }
    if let Ok(v) = env::var("OPENFDD_MODBUS_PORT") {
        if let Ok(port) = v.parse() {
            p.modbus_port = port;
        }
    }
    if let Ok(v) = env::var("OPENFDD_HAYSTACK_BASE") {
        if !v.trim().is_empty() {
            p.haystack_base_url = v;
            p.haystack_enabled = true;
        }
    }
    if let Ok(v) = env::var("OPENFDD_HAYSTACK_USER") {
        if !v.is_empty() {
            p.haystack_username = v;
        }
    }
    if let Ok(v) = env::var("OPENFDD_HAYSTACK_PASS") {
        if !v.is_empty() {
            p.haystack_password = v;
        }
    }
}

fn apply_toml(p: &mut SmokeProfile, text: &str) {
    let mut section = String::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            section = line[1..line.len() - 1].trim().to_string();
            continue;
        }
        let Some((key, val)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        let val = val.trim().trim_matches('"');
        match section.as_str() {
            "bacnet" => apply_bacnet_key(p, key, val),
            "modbus" => apply_modbus_key(p, key, val),
            "haystack" => apply_haystack_key(p, key, val),
            "csv_append" => apply_csv_key(p, key, val),
            "json_api" => apply_json_api_key(p, key, val),
            _ => apply_root_key(p, key, val),
        }
    }
}

fn apply_root_key(p: &mut SmokeProfile, key: &str, val: &str) {
    match key {
        "profile_id" => p.profile_id = val.to_string(),
        "source_id" => p.source_id = val.to_string(),
        "source_type" => p.source_type = val.to_string(),
        "device_instance" => {
            if let Ok(n) = val.parse() {
                p.device_instance = n;
            }
        }
        "equipment_id" => p.equipment_id = val.to_string(),
        "poll_interval_seconds" => {
            if let Ok(n) = val.parse() {
                p.poll_interval_seconds = n;
            }
        }
        "duration_hours" => {
            if let Ok(n) = val.parse() {
                p.duration_hours = n;
            }
        }
        "duration_minutes" => {
            if let Ok(n) = val.parse() {
                p.duration_minutes = n;
            }
        }
        "confirmation_minutes" => {
            if let Ok(n) = val.parse() {
                p.confirmation_minutes = n;
            }
        }
        "historian_subdir" => p.historian_subdir = val.to_string(),
        "artifact_dir" | "artifact_subdir" => p.artifact_subdir = val.to_string(),
        "fdd_rule_id" => p.fdd_rule_id = val.to_string(),
        _ if key.starts_with("point.") => parse_point_line(p, key, val),
        _ => {}
    }
}

fn apply_bacnet_key(p: &mut SmokeProfile, key: &str, val: &str) {
    match key {
        "enabled" => {
            if val == "true" || val == "1" {
                p.source_type = "bacnet".into();
            }
        }
        "device_instance" => {
            if let Ok(n) = val.parse() {
                p.device_instance = n;
            }
        }
        "poll_interval_seconds" => {
            if let Ok(n) = val.parse() {
                p.poll_interval_seconds = n;
            }
        }
        _ if key.starts_with("point.") => parse_point_line(p, key, val),
        _ => {}
    }
}

fn apply_modbus_key(p: &mut SmokeProfile, key: &str, val: &str) {
    match key {
        "enabled" => p.modbus_enabled = val == "true" || val == "1",
        "host" => p.modbus_host = val.to_string(),
        "port" => {
            if let Ok(n) = val.parse() {
                p.modbus_port = n;
            }
        }
        "unit_id" => {
            if let Ok(n) = val.parse() {
                p.modbus_unit_id = n;
            }
        }
        "register" => {
            if let Ok(n) = val.parse() {
                p.modbus_register = n;
            }
        }
        "poll_interval_seconds" => {
            if let Ok(n) = val.parse() {
                p.modbus_poll_interval_seconds = n;
            }
        }
        _ => {}
    }
}

fn apply_haystack_key(p: &mut SmokeProfile, key: &str, val: &str) {
    match key {
        "enabled" => p.haystack_enabled = val == "true" || val == "1",
        "base_url" => p.haystack_base_url = val.to_string(),
        "username" => p.haystack_username = val.to_string(),
        "password" => p.haystack_password = val.to_string(),
        "source_id" => p.haystack_source_id = val.to_string(),
        "poll_interval_seconds" => {
            if let Ok(n) = val.parse() {
                p.haystack_poll_interval_seconds = n;
            }
        }
        _ => {}
    }
}

fn apply_csv_key(p: &mut SmokeProfile, key: &str, val: &str) {
    match key {
        "enabled" => p.csv_enabled = val == "true" || val == "1",
        "source_id" => p.csv_source_id = val.to_string(),
        "interval_seconds" => {
            if let Ok(n) = val.parse() {
                p.csv_interval_seconds = n;
            }
        }
        _ => {}
    }
}

fn apply_json_api_key(p: &mut SmokeProfile, key: &str, val: &str) {
    match key {
        "enabled" => p.json_api_enabled = val == "true" || val == "1",
        "url" => p.json_api_url = Some(val.to_string()),
        "poll_interval_seconds" => {
            if let Ok(n) = val.parse() {
                p.json_api_poll_interval_seconds = n;
            }
        }
        _ => {}
    }
}

fn parse_point_line(p: &mut SmokeProfile, key: &str, val: &str) {
    // point.oa_t = "Outside Air Temp|1001|oa_t"
    let input = key.trim_start_matches("point.");
    let parts: Vec<&str> = val.split('|').collect();
    if parts.len() >= 3 {
        if let Ok(inst) = parts[1].parse() {
            p.bacnet_points.push(BacnetPointRole {
                name: parts[0].to_string(),
                object_instance: inst,
                fdd_input: parts[2].to_string(),
            });
        }
    } else if !input.is_empty() {
        p.bacnet_points.push(BacnetPointRole {
            name: input.to_string(),
            object_instance: 0,
            fdd_input: input.to_string(),
        });
    }
}

pub fn profile_summary_json() -> Value {
    let p = active_profile();
    let path = profile_path();
    json!({
        "profile_id": p.profile_id,
        "source_id": p.source_id,
        "device_instance": p.device_instance,
        "equipment_id": p.equipment_id,
        "poll_interval_seconds": p.poll_interval_seconds,
        "duration_hours": p.duration_hours,
        "duration_minutes": p.duration_minutes,
        "confirmation_minutes": p.confirmation_minutes,
        "historian_subdir": p.historian_subdir,
        "artifact_subdir": p.artifact_subdir,
        "bacnet_points_count": p.bacnet_points.len(),
        "modbus_configured": is_modbus_configured(&p),
        "haystack_configured": is_haystack_configured(&p),
        "csv_enabled": p.csv_enabled,
        "profile_path": path.display().to_string(),
        "profile_file_present": path.exists()
    })
}

pub fn fdd_sql(profile: &SmokeProfile) -> String {
    let equip = &profile.equipment_id;
    let confirmation_minutes = profile.confirmation_minutes;
    format!(
        r#"WITH samples AS (
  SELECT timestamp, equipment_id, oa_t, oa_h, duct_t, zn_t,
    CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true ELSE false END AS raw_fault
  FROM telemetry_pivot WHERE equipment_id = '{equip}'
),
streak_groups AS (
  SELECT *, SUM(CASE WHEN NOT raw_fault THEN 1 ELSE 0 END) OVER (ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM samples
),
streak_stats AS (
  SELECT timestamp, equipment_id, oa_t, oa_h, duct_t, zn_t, raw_fault,
    MIN(timestamp) OVER (PARTITION BY streak_id ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS raw_fault_started_at,
    COUNT(*) OVER (PARTITION BY streak_id ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS samples_in_streak
  FROM streak_groups WHERE raw_fault
)
SELECT timestamp, equipment_id, oa_t, oa_h, duct_t, zn_t, raw_fault, raw_fault_started_at,
  CAST(samples_in_streak AS DOUBLE) AS minutes_in_fault,
  {confirmation_minutes} AS confirmation_required_minutes,
  CASE WHEN samples_in_streak >= {confirmation_minutes} THEN true ELSE false END AS confirmed_fault
FROM streak_stats
UNION ALL
SELECT timestamp, equipment_id, oa_t, oa_h, duct_t, zn_t, raw_fault,
  CAST(NULL AS TIMESTAMP), CAST(0 AS DOUBLE), {confirmation_minutes}, false
FROM samples WHERE NOT raw_fault
ORDER BY timestamp"#
    )
}

pub fn live_fdd_enabled() -> bool {
    env_flag("OPENFDD_SMOKE_LIVE_FDD") || env_flag("BENCH_SMOKE_LIVE_FDD")
}

pub fn short_mode() -> bool {
    env_flag("BENCH_SMOKE_SHORT_FDD")
}

pub fn require_modbus() -> bool {
    env_flag("OPENFDD_SMOKE_REQUIRE_MODBUS")
}

pub fn no_demo_pass() -> bool {
    env_flag("OPENFDD_SMOKE_NO_DEMO_PASS")
}

pub fn require_confirmed_fault() -> bool {
    env_flag("OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT")
}

pub fn validate_docker() -> bool {
    env_flag("OPENFDD_SMOKE_VALIDATE_DOCKER")
}

pub fn validate_modbus() -> bool {
    env_flag("OPENFDD_SMOKE_VALIDATE_MODBUS")
}

pub fn validate_json_api() -> bool {
    env_flag("OPENFDD_SMOKE_VALIDATE_JSON_API")
}

pub fn simulate_phases() -> bool {
    env_flag("OPENFDD_SMOKE_SIMULATE") || env_flag("BENCH_SMOKE_SIMULATE")
}

fn env_flag(key: &str) -> bool {
    env::var(key)
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_overrides_device_instance() {
        let _lock = test_lock();
        let ws = std::env::temp_dir().join(format!("ofdd-prof-{}", std::process::id()));
        std::env::set_var("OPENFDD_WORKSPACE", &ws);
        std::env::set_var("OPENFDD_SMOKE_DEVICE_INSTANCE", "42");
        let p = active_profile();
        assert_eq!(p.device_instance, 42);
        std::env::remove_var("OPENFDD_WORKSPACE");
        std::env::remove_var("OPENFDD_SMOKE_DEVICE_INSTANCE");
        let _ = fs::remove_dir_all(ws);
    }

    #[test]
    fn parses_local_toml_points() {
        let _lock = test_lock();
        std::env::remove_var("OPENFDD_SMOKE_DEVICE_INSTANCE");
        let ws = std::env::temp_dir().join(format!("ofdd-toml-{}", std::process::id()));
        let dir = ws.join("smoke-profiles/local");
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("test.local.toml"),
            r#"profile_id = "test"
device_instance = 99
point.oa_t = "OA Temp|1001|oa_t"
"#,
        )
        .unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &ws);
        std::env::set_var("OPENFDD_SMOKE_PROFILE", "test");
        let p = active_profile();
        assert_eq!(p.device_instance, 99);
        assert_eq!(p.bacnet_points.len(), 1);
        let _ = fs::remove_dir_all(ws);
    }

    #[test]
    fn default_modbus_not_configured() {
        let _lock = test_lock();
        let ws = std::env::temp_dir().join(format!("ofdd-modbus-{}", std::process::id()));
        std::env::set_var("OPENFDD_WORKSPACE", &ws);
        std::env::remove_var("OPENFDD_MODBUS_HOST");
        let p = active_profile();
        assert!(!is_modbus_configured(&p));
        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    fn test_lock() -> std::sync::MutexGuard<'static, ()> {
        static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    #[test]
    fn smoke_env_flags() {
        let _lock = test_lock();
        std::env::set_var("OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT", "1");
        std::env::set_var("OPENFDD_SMOKE_VALIDATE_MODBUS", "1");
        assert!(require_confirmed_fault());
        assert!(validate_modbus());
        std::env::remove_var("OPENFDD_SMOKE_REQUIRE_CONFIRMED_FAULT");
        std::env::remove_var("OPENFDD_SMOKE_VALIDATE_MODBUS");
        std::env::remove_var("OPENFDD_WORKSPACE");
        std::env::remove_var("OPENFDD_SMOKE_PROFILE");
    }
}
