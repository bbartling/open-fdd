//! Data source validation helpers (Modbus decode, Haystack parity, CSV status).

use crate::validation::dev_profile::{
    decode_modbus_scaled, haystack_within_tolerance, DevValidationProfile, ModbusRegisterSpec,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SourceValidationSummary {
    pub bacnet: SourceCheck,
    pub modbus: SourceCheck,
    pub json_api: SourceCheck,
    pub haystack: SourceCheck,
    pub csv: SourceCheck,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SourceCheck {
    pub configured: bool,
    pub pass: bool,
    pub status: String,
    pub sample_count: u64,
    pub notes: String,
    pub details: Value,
}

pub fn decode_modbus_registers(specs: &[ModbusRegisterSpec], raw: &[(u16, i64)]) -> Value {
    let mut rows = Vec::new();
    for spec in specs {
        let raw_val = raw
            .iter()
            .find(|(addr, _)| *addr == spec.address)
            .map(|(_, v)| *v)
            .unwrap_or(0);
        rows.push(json!({
            "address": spec.address,
            "label": spec.label,
            "role": spec.role,
            "raw": raw_val,
            "decoded": decode_modbus_scaled(raw_val, spec.scale),
        }));
    }
    json!({"registers": rows})
}

pub fn haystack_parity_report(
    profile: &DevValidationProfile,
    bacnet: &[(String, f64)],
    haystack: &[(String, f64)],
) -> Value {
    let mut rows = Vec::new();
    for hp in &profile.haystack_points {
        let b = hp
            .bacnet_role
            .as_ref()
            .and_then(|role| bacnet.iter().find(|(r, _)| r == role).map(|(_, v)| *v))
            .or_else(|| bacnet.iter().find(|(r, _)| r == &hp.role).map(|(_, v)| *v));
        let h = haystack
            .iter()
            .find(|(id, _)| id == &hp.haystack_id)
            .map(|(_, v)| *v);
        let tolerance = if hp.role.contains('h') || hp.role.contains("humidity") {
            profile.humidity_tolerance_pct
        } else {
            profile.temp_tolerance_f
        };
        let pass = match (b, h) {
            (Some(bv), Some(hv)) => haystack_within_tolerance(bv, hv, tolerance),
            _ => false,
        };
        rows.push(json!({
            "role": hp.role,
            "haystack_id": hp.haystack_id,
            "bacnet_value": b,
            "haystack_value": h,
            "tolerance": tolerance,
            "pass": pass
        }));
    }
    json!({"parity_rows": rows})
}

pub fn source_summary_from_artifact(
    profile: &DevValidationProfile,
    artifact: &Value,
) -> SourceValidationSummary {
    let bacnet_poll_ok = artifact
        .get("bacnet_poll_ok")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let modbus_ok = artifact
        .get("modbus_ok")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let haystack_ok = artifact
        .get("haystack_ok")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let csv_ok = artifact
        .get("csv_import_ok")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    SourceValidationSummary {
        bacnet: SourceCheck {
            configured: true,
            pass: bacnet_poll_ok > 0,
            status: if bacnet_poll_ok > 0 {
                "ok".into()
            } else {
                "degraded".into()
            },
            sample_count: bacnet_poll_ok,
            notes: String::new(),
            details: json!({"poll_ok_samples": bacnet_poll_ok}),
        },
        modbus: SourceCheck {
            configured: profile.modbus_configured(),
            pass: !profile.modbus_configured() || modbus_ok > 0,
            status: if !profile.modbus_configured() {
                "not_configured".into()
            } else if modbus_ok > 0 {
                "ok".into()
            } else {
                "fail".into()
            },
            sample_count: modbus_ok,
            notes: String::new(),
            details: json!({"poll_ok_samples": modbus_ok}),
        },
        json_api: SourceCheck {
            configured: profile.smoke.json_api_enabled,
            pass: !profile.smoke.json_api_enabled
                || artifact
                    .get("json_api_ok")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0)
                    > 0,
            status: if !profile.smoke.json_api_enabled {
                "not_configured".into()
            } else {
                "ok".into()
            },
            sample_count: artifact
                .get("json_api_ok")
                .and_then(|v| v.as_u64())
                .unwrap_or(0),
            notes: String::new(),
            details: json!({}),
        },
        haystack: SourceCheck {
            configured: profile.haystack_configured(),
            pass: !profile.haystack_configured() || haystack_ok > 0,
            status: if !profile.haystack_configured() {
                "not_configured".into()
            } else if haystack_ok > 0 {
                "ok".into()
            } else {
                "fail".into()
            },
            sample_count: haystack_ok,
            notes: String::new(),
            details: json!({"poll_ok_samples": haystack_ok}),
        },
        csv: SourceCheck {
            configured: profile.smoke.csv_enabled,
            pass: !profile.smoke.csv_enabled || csv_ok > 0,
            status: if !profile.smoke.csv_enabled {
                "not_configured".into()
            } else if csv_ok > 0 {
                "ok".into()
            } else {
                "fail".into()
            },
            sample_count: csv_ok,
            notes: String::new(),
            details: json!({"import_ok_samples": csv_ok}),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::dev_profile::DevValidationProfile;

    #[test]
    fn modbus_decode_x10_values() {
        let specs = vec![ModbusRegisterSpec {
            address: 30001,
            label: "temp_f_x10".into(),
            function: "input_register".into(),
            scale: 0.1,
            role: "temp_f".into(),
        }];
        let decoded = decode_modbus_registers(&specs, &[(30001, 725)]);
        assert_eq!(decoded["registers"][0]["decoded"], json!(72.5));
    }

    #[test]
    fn optional_modbus_not_configured_not_failure() {
        let dir = std::env::temp_dir().join(format!("src-sum-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("p.toml");
        std::fs::write(&path, "profile_id=\"x\"\n").unwrap();
        let profile = DevValidationProfile::load(&path).unwrap();
        let summary = source_summary_from_artifact(&profile, &json!({}));
        assert_eq!(summary.modbus.status, "not_configured");
        assert!(summary.modbus.pass);
        let _ = std::fs::remove_dir_all(dir);
    }
}
