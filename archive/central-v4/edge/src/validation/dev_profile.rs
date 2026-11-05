//! Extended dev-only validation profile (local TOML, never hardcoded bench values).

use super::profile::{load_profile_from_path, SiteConfig};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq)]
pub struct ModbusRegisterSpec {
    pub address: u16,
    pub label: String,
    pub function: String,
    pub scale: f64,
    pub role: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct HaystackPointSpec {
    pub role: String,
    pub haystack_id: String,
    pub bacnet_role: Option<String>,
}

#[derive(Clone, Debug)]
pub struct DevValidationProfile {
    pub profile_path: PathBuf,
    pub site_config: SiteConfig,
    pub report_title: String,
    pub site_id: String,
    pub modbus_registers: Vec<ModbusRegisterSpec>,
    pub haystack_points: Vec<HaystackPointSpec>,
    pub temp_tolerance_f: f64,
    pub humidity_tolerance_pct: f64,
    pub timestamp_skew_seconds: i64,
}

impl DevValidationProfile {
    pub fn load(path: &Path) -> Result<Self, String> {
        let text = fs::read_to_string(path).map_err(|e| format!("read profile: {e}"))?;
        let site_config = load_profile_from_path(path);
        let mut profile = Self {
            profile_path: path.to_path_buf(),
            site_config,
            report_title: "Local RCx Validation Report".into(),
            site_id: String::new(),
            modbus_registers: Vec::new(),
            haystack_points: Vec::new(),
            temp_tolerance_f: 1.0,
            humidity_tolerance_pct: 5.0,
            timestamp_skew_seconds: 120,
        };
        profile.apply_toml(&text);
        if profile.site_id.is_empty() {
            profile.site_id = profile.site_config.equipment_id.clone();
        }
        Ok(profile)
    }

    fn apply_toml(&mut self, text: &str) {
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
                "dev" | "report" => self.apply_dev_key(key, val),
                "modbus" => self.apply_modbus_dev_key(key, val),
                "haystack" => self.apply_haystack_dev_key(key, val),
                "parity" => self.apply_parity_key(key, val),
                _ => self.apply_dev_key(key, val),
            }
        }
    }

    fn apply_dev_key(&mut self, key: &str, val: &str) {
        match key {
            "report_title" => self.report_title = val.to_string(),
            "site_id" => self.site_id = val.to_string(),
            _ => {}
        }
    }

    fn apply_parity_key(&mut self, key: &str, val: &str) {
        match key {
            "temp_tolerance_f" => {
                if let Ok(n) = val.parse::<f64>() {
                    self.temp_tolerance_f = n;
                }
            }
            "humidity_tolerance_pct" => {
                if let Ok(n) = val.parse::<f64>() {
                    self.humidity_tolerance_pct = n;
                }
            }
            "timestamp_skew_seconds" => {
                if let Ok(n) = val.parse::<i64>() {
                    self.timestamp_skew_seconds = n;
                }
            }
            _ => {}
        }
    }

    fn apply_modbus_dev_key(&mut self, key: &str, val: &str) {
        if let Some(addr) = key.strip_prefix("register.") {
            if let Ok(address) = addr.parse::<u16>() {
                if let Some(spec) = parse_modbus_register_line(address, val) {
                    self.modbus_registers.retain(|r| r.address != address);
                    self.modbus_registers.push(spec);
                }
            }
        }
    }

    fn apply_haystack_dev_key(&mut self, key: &str, val: &str) {
        if let Some(role) = key.strip_prefix("point.") {
            let parts: Vec<&str> = val.split('|').collect();
            let haystack_id = parts.first().copied().unwrap_or("").trim().to_string();
            let bacnet_role = parts.get(1).map(|s| s.trim().to_string());
            if !haystack_id.is_empty() {
                self.haystack_points.push(HaystackPointSpec {
                    role: role.to_string(),
                    haystack_id,
                    bacnet_role,
                });
            }
        }
    }

    pub fn modbus_configured(&self) -> bool {
        super::profile::is_modbus_configured(&self.site_config)
    }

    pub fn haystack_configured(&self) -> bool {
        super::profile::is_haystack_configured(&self.site_config)
    }
}

fn parse_modbus_register_line(address: u16, val: &str) -> Option<ModbusRegisterSpec> {
    // temp_f_x10|input_register|0.1|temp_f
    let parts: Vec<&str> = val.split('|').collect();
    if parts.is_empty() {
        return None;
    }
    Some(ModbusRegisterSpec {
        address,
        label: parts[0].trim().to_string(),
        function: parts
            .get(1)
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "input_register".into()),
        scale: parts.get(2).and_then(|s| s.parse().ok()).unwrap_or(1.0),
        role: parts
            .get(3)
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| parts[0].trim().to_string()),
    })
}

pub fn decode_modbus_scaled(raw: i64, scale: f64) -> f64 {
    raw as f64 * scale
}

pub fn haystack_within_tolerance(bacnet_value: f64, haystack_value: f64, tolerance: f64) -> bool {
    (bacnet_value - haystack_value).abs() <= tolerance
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_modbus_register_line() {
        let spec =
            parse_modbus_register_line(30001, "temp_f_x10|input_register|0.1|temp_f").unwrap();
        assert_eq!(spec.address, 30001);
        assert_eq!(spec.scale, 0.1);
        assert_eq!(spec.role, "temp_f");
    }

    #[test]
    fn decodes_x10_modbus_value() {
        assert!((decode_modbus_scaled(725, 0.1) - 72.5).abs() < f64::EPSILON);
    }

    #[test]
    fn haystack_parity_tolerance() {
        assert!(haystack_within_tolerance(72.0, 72.5, 1.0));
        assert!(!haystack_within_tolerance(72.0, 74.0, 1.0));
    }

    #[test]
    fn loads_dev_profile_fields() {
        let dir = std::env::temp_dir().join(format!("ofdd-dev-prof-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("dev.local.toml");
        fs::write(
            &path,
            r#"
profile_id = "dev-test"
equipment_id = "equip:test"
report_title = "Test Report"
site_id = "site:test"

[dev]
report_title = "Dev Report Title"

[modbus]
register.30001 = "temp_f_x10|input_register|0.1|temp_f"

[parity]
temp_tolerance_f = 2.0

[haystack]
point.oa_t = "point:oa-t|oa_t"
"#,
        )
        .unwrap();
        let p = DevValidationProfile::load(&path).unwrap();
        assert_eq!(p.report_title, "Dev Report Title");
        assert_eq!(p.site_id, "site:test");
        assert_eq!(p.modbus_registers.len(), 1);
        assert_eq!(p.temp_tolerance_f, 2.0);
        assert_eq!(p.haystack_points.len(), 1);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn no_private_defaults_in_struct() {
        let dir = std::env::temp_dir().join(format!("ofdd-dev-empty-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("empty.local.toml");
        fs::write(&path, "profile_id = \"empty\"\n").unwrap();
        let p = DevValidationProfile::load(&path).unwrap();
        assert!(p.site_config.modbus_host.is_empty());
        assert_eq!(p.site_config.device_instance, 0);
        let _ = fs::remove_dir_all(&dir);
    }
}
