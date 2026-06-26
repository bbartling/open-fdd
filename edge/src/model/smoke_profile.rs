//! Build a Haystack grid from the active validation smoke profile.

use super::persist;
use crate::validation::profile::{active_profile, BacnetPointRole, SmokeProfile};
use serde_json::{json, Value};

pub fn import_from_active_profile() -> Value {
    let profile = active_profile();
    import_from_profile(&profile)
}

pub fn import_from_profile(profile: &SmokeProfile) -> Value {
    let site_id = format!("site:{}", profile.profile_id);
    let equip_id = format!("equip:{}", profile.equipment_id);
    let source_id = profile.source_id.clone();
    let device = profile.device_instance;

    let mut rows: Vec<Value> = vec![
        json!({
            "id": site_id,
            "dis": format!("Site {}", profile.profile_id),
            "site": "M"
        }),
        json!({
            "id": equip_id,
            "dis": format!("Equipment {}", profile.equipment_id),
            "equip": "M",
            "siteRef": site_id,
            "ahu": "M",
            "sourceRef": source_id
        }),
        json!({
            "id": source_id,
            "dis": format!("Source {}", profile.source_type),
            "source": "M",
            "protocol": profile.source_type,
            "deviceInstance": device
        }),
    ];

    for pt in &profile.bacnet_points {
        rows.push(point_row(profile, &equip_id, &source_id, pt));
    }

    let grid = json!({
        "meta": {
            "ver": "3.0",
            "mode": "smoke-profile-import",
            "profile_id": profile.profile_id,
            "source_id": source_id,
            "fdd_rule_id": profile.fdd_rule_id
        },
        "cols": [
            {"name":"id"},{"name":"dis"},{"name":"site"},{"name":"equip"},{"name":"point"},
            {"name":"sensor"},{"name":"kind"},{"name":"unit"},{"name":"curVal"},
            {"name":"bacnetRef"},{"name":"fddInput"},{"name":"equipRef"},{"name":"sourceRef"}
        ],
        "rows": rows
    });

    match persist::save_haystack_grid(&grid) {
        Ok(path) => json!({
            "ok": true,
            "imported": rows.len(),
            "path": path.display().to_string(),
            "profile_id": profile.profile_id,
            "equipment_id": profile.equipment_id,
            "source_id": source_id,
            "point_count": profile.bacnet_points.len(),
            "fdd_rule_id": profile.fdd_rule_id,
            "mode": "smoke-profile-import"
        }),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

fn point_row(
    profile: &SmokeProfile,
    equip_id: &str,
    source_id: &str,
    pt: &BacnetPointRole,
) -> Value {
    let tags = infer_tags(&pt.fdd_input);
    json!({
        "id": format!("point:{}", pt.fdd_input),
        "dis": pt.name,
        "point": "M",
        "sensor": "M",
        "kind": "Number",
        "unit": infer_unit(&pt.fdd_input),
        "curVal": null,
        "equipRef": equip_id,
        "sourceRef": source_id,
        "bacnetRef": format!("bacnet:{}:analog-input:{}", profile.device_instance, pt.object_instance),
        "fddInput": pt.fdd_input,
        "tags": tags
    })
}

fn infer_unit(fdd_input: &str) -> &'static str {
    if fdd_input.contains("_h") {
        "%RH"
    } else {
        "°F"
    }
}

fn infer_tags(fdd_input: &str) -> Value {
    let mut tags = vec!["point", "sensor"];
    if fdd_input.contains("oa") {
        tags.extend(["outside", "air"]);
    }
    if fdd_input.contains("duct") {
        tags.extend(["discharge", "air"]);
    }
    if fdd_input.contains("zn") {
        tags.extend(["zone", "air"]);
    }
    if fdd_input.contains("_t") {
        tags.push("temp");
    }
    if fdd_input.contains("_h") {
        tags.push("humidity");
    }
    json!(tags)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::profile::SmokeProfile;

    #[test]
    fn builds_rows_from_profile_points() {
        let _lock = crate::test_support::workspace_env_lock();
        let dir = std::env::temp_dir().join(format!("openfdd-smoke-import-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        std::env::set_var("OPENFDD_WORKSPACE", &dir);
        let profile = SmokeProfile {
            profile_id: "local_bacnet_fdd_validation".into(),
            source_id: "source:validation-bacnet".into(),
            source_type: "bacnet".into(),
            device_instance: 42,
            equipment_id: "equip:local-test".into(),
            poll_interval_seconds: 60,
            duration_hours: 1.0,
            confirmation_minutes: 5,
            historian_subdir: "validation".into(),
            artifact_subdir: "live_fdd_validation".into(),
            fdd_rule_id: "oa_temp_out_of_range".into(),
            bacnet_points: vec![crate::validation::profile::BacnetPointRole::sensor(
                "Outside Air Temp",
                1001,
                "oa_t",
            )],
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
        };
        let out = import_from_profile(&profile);
        assert_eq!(out["ok"].as_bool(), Some(true));
        assert_eq!(out["point_count"].as_u64(), Some(1));
        let _ = std::fs::remove_dir_all(dir);
    }
}
