//! Smoke profile loaded from env and optional local TOML (gitignored).

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
    pub json_api_url: Option<String>,
}

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

pub fn profile_path() -> PathBuf {
    if let Ok(p) = env::var("OPENFDD_SMOKE_PROFILE_PATH") {
        return PathBuf::from(p);
    }
    let id = env::var("OPENFDD_SMOKE_PROFILE").unwrap_or_else(|_| "local_bacnet_fdd_validation".into());
    workspace_dir()
        .join("smoke-profiles/local")
        .join(format!("{id}.local.toml"))
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
        profile_id: "local_bacnet_fdd_validation".into(),
        source_id: "source:validation".into(),
        source_type: "bacnet".into(),
        device_instance: 0,
        equipment_id: "equip:validation".into(),
        poll_interval_seconds: 300,
        duration_hours: 6.0,
        confirmation_minutes: 5,
        historian_subdir: "validation".into(),
        artifact_subdir: "live_fdd_validation".into(),
        fdd_rule_id: "oa_temp_out_of_range".into(),
        bacnet_points: Vec::new(),
        modbus_host: "192.168.204.14".into(),
        modbus_port: 1502,
        modbus_unit_id: 1,
        modbus_register: 30001,
        json_api_url: None,
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
            if p.equipment_id == "equip:validation" {
                p.equipment_id = inst.to_string();
            }
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
        }
    }
    if let Ok(v) = env::var("OPENFDD_MODBUS_HOST") {
        if !v.is_empty() {
            p.modbus_host = v;
        }
    }
    if let Ok(v) = env::var("OPENFDD_MODBUS_PORT") {
        if let Ok(port) = v.parse() {
            p.modbus_port = port;
        }
    }
}

fn apply_toml(p: &mut SmokeProfile, text: &str) {
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, val)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        let val = val.trim().trim_matches('"');
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
            "confirmation_minutes" => {
                if let Ok(n) = val.parse() {
                    p.confirmation_minutes = n;
                }
            }
            "historian_subdir" => p.historian_subdir = val.to_string(),
            "artifact_dir" => p.artifact_subdir = val.to_string(),
            "fdd_rule_id" => p.fdd_rule_id = val.to_string(),
            "modbus_host" => p.modbus_host = val.to_string(),
            "modbus_port" => {
                if let Ok(n) = val.parse() {
                    p.modbus_port = n;
                }
            }
            "modbus_unit_id" => {
                if let Ok(n) = val.parse() {
                    p.modbus_unit_id = n;
                }
            }
            "json_api_url" => p.json_api_url = Some(val.to_string()),
            _ if key.starts_with("point.") => parse_point_line(p, key, val),
            _ => {}
        }
    }
}

fn parse_point_line(p: &mut SmokeProfile, key: &str, val: &str) {
    // point.oa_t = "Outside Air Temp|1173|oa_t"
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
    json!({
        "profile_id": p.profile_id,
        "source_id": p.source_id,
        "device_instance": p.device_instance,
        "equipment_id": p.equipment_id,
        "poll_interval_seconds": p.poll_interval_seconds,
        "duration_hours": p.duration_hours,
        "confirmation_minutes": p.confirmation_minutes,
        "historian_subdir": p.historian_subdir,
        "artifact_subdir": p.artifact_subdir,
        "bacnet_points_count": p.bacnet_points.len(),
        "profile_path": profile_path().display().to_string(),
        "profile_file_present": profile_path().exists()
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
        let _ = fs::remove_dir_all(ws);
    }

    #[test]
    fn parses_local_toml_points() {
        let _lock = test_lock();
        let ws = std::env::temp_dir().join(format!("ofdd-toml-{}", std::process::id()));
        let dir = ws.join("smoke-profiles/local");
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("test.local.toml"),
            r#"profile_id = "test"
device_instance = 99
point.oa_t = "OA Temp|1173|oa_t"
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
    }
}
