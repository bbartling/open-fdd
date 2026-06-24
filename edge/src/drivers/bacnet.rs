//! BACnet driver facade (rusty-bacnet live path + simulated CI path).
//!
//! Live mode (`OPENFDD_BACNET_MODE=live`) uses [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet)
//! for Who-Is/I-Am discovery, object-list walks, ReadProperty(present-value), and
//! ReadProperty(priority-array) override scans. Simulated mode keeps deterministic
//! data so Docker/CI runs without an OT BACnet network.

use super::bacnet_live;
use chrono::Utc;
use serde_json::{json, Value};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

const DEVICES_JSON: &str = r#"[
  {"object_identifier":{"type":"device","instance":5007},"vendor_id":5,"address":"192.168.204.200:47808","label":"BENS Bench Controller","protocol":"BACnet/IP"}
]"#;

const POINTS_JSON: &str = r#"[
  {"device_instance":5007,"mac":"c0a801c8bac0","object_id":[0,1173],"name":"Outside Air Temp","kind":"sensor","unit":"°F","writable":false,"value":62.0,"haystack_id":"point:oa-t"},
  {"device_instance":5007,"mac":"c0a801c8bac0","object_id":[1,2466],"name":"ACTUATOR-0","kind":"cmd","unit":"%","writable":true,"value":55.0,"haystack_id":"point:actuator-0"},
  {"device_instance":5007,"mac":"c0a801c8bac0","object_id":[1,10032],"name":"C06-0-10VDC-O","kind":"cmd","unit":"V","writable":true,"value":11.0,"haystack_id":"point:c06-ao"}
]"#;

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn bacnet_overrides_dir() -> PathBuf {
    workspace_dir().join("bacnet/overrides")
}

fn legacy_overrides_dir() -> PathBuf {
    workspace_dir().join("overrides")
}

fn overrides_dir() -> PathBuf {
    bacnet_overrides_dir()
}

fn override_registry_path() -> PathBuf {
    bacnet_overrides_dir().join("registry.json")
}

fn export_csv_path() -> PathBuf {
    bacnet_overrides_dir().join("overrides_export.csv")
}

fn csv_path(name: &str) -> PathBuf {
    bacnet_overrides_dir().join(name)
}

pub fn override_scan_interval_s() -> u64 {
    env::var("OFDD_OVERRIDE_SCAN_INTERVAL_S")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(3600)
}

pub fn operator_override_priority() -> u8 {
    env::var("OFDD_OPERATOR_OVERRIDE_PRIORITY")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8)
}

pub const OVERRIDE_EXPORT_CSV_HEADER: &str = "scanned_at,device_instance,device_address,device_label,object_identifier,object_name,object_type,present_value,priority_level,priority_value,operator_override,override_kind,units,source";

pub fn override_kind(priority: u8, operator_priority: u8) -> &'static str {
    if priority == operator_priority {
        "operator"
    } else {
        "supervisory"
    }
}

pub fn is_operator_override(priority: u8, operator_priority: u8) -> bool {
    priority == operator_priority
}

fn now_rfc3339() -> String {
    Utc::now().to_rfc3339()
}

pub fn bacnet_config_value() -> Value {
    json!({
        "mode": env::var("OPENFDD_BACNET_MODE").unwrap_or_else(|_| "simulated".to_string()),
        "iface": env::var("OPENFDD_BACNET_IFACE").unwrap_or_else(|_| "enp3s0".to_string()),
        "bind": env::var("OPENFDD_BACNET_BIND").unwrap_or_else(|_| "192.168.204.55/24:47808".to_string()),
        "device_instance": env::var("OPENFDD_BACNET_DEVICE_INSTANCE").unwrap_or_else(|_| "599999".to_string()),
        "device_name": env::var("OPENFDD_BACNET_DEVICE_NAME").unwrap_or_else(|_| "OpenFDD".to_string()),
        "scan_interval_seconds": env::var("OPENFDD_BACNET_SCAN_INTERVAL_SECONDS").unwrap_or_else(|_| "3600".to_string()),
        "poll_interval_seconds": env::var("OPENFDD_BACNET_POLL_INTERVAL_SECONDS").unwrap_or_else(|_| "60".to_string()),
        "router_ip": env::var("OPENFDD_BACNET_ROUTER_IP").unwrap_or_else(|_| "192.168.204.200".to_string()),
        "mstp_network": env::var("OPENFDD_BACNET_MSTP_NET").unwrap_or_else(|_| "2000".to_string()),
        "discover_low": env::var("OPENFDD_BACNET_DISCOVER_LOW").unwrap_or_else(|_| "5007".to_string()),
        "discover_high": env::var("OPENFDD_BACNET_DISCOVER_HIGH").unwrap_or_else(|_| "5007".to_string())
    })
}

fn bench5007_points() -> Vec<Value> {
    vec![
        json!({"id":"bacnet:5007:analog-input:1173","device_instance":5007,"object_id":[0,1173],"name":"Outside Air Temp","polling_enabled":true,"writable":false,"haystack_id":"point:oa-t","fdd_input":"oa_t"}),
        json!({"id":"bacnet:5007:analog-input:1168","device_instance":5007,"object_id":[0,1168],"name":"Outside Air Humidity","polling_enabled":true,"writable":false,"haystack_id":"point:oa-h","fdd_input":"oa_h"}),
        json!({"id":"bacnet:5007:analog-input:1192","device_instance":5007,"object_id":[0,1192],"name":"Discharge Air Temp","polling_enabled":true,"writable":false,"haystack_id":"point:duct-t","fdd_input":"duct_t"}),
        json!({"id":"bacnet:5007:analog-input:10014","device_instance":5007,"object_id":[0,10014],"name":"Zone Temp","polling_enabled":true,"writable":false,"haystack_id":"point:stat_zn-t","fdd_input":"stat_zn_t"}),
        json!({"id":"bacnet:5007:analog-output:10032","device_instance":5007,"object_id":[1,10032],"name":"C06-0-10VDC-O","polling_enabled":true,"writable":true,"commandable":true,"haystack_id":"point:c06-ao","fdd_input":"c06_ao"}),
        json!({"id":"bacnet:5007:analog-output:2466","device_instance":5007,"object_id":[1,2466],"name":"ACTUATOR-0","polling_enabled":true,"writable":true,"commandable":true,"haystack_id":"point:actuator-0","fdd_input":"actuator_0"}),
    ]
}

fn bench5007_device() -> Value {
    json!({
      "device_instance":5007,
      "name":"BENS Bench Controller",
      "address":"192.168.204.200:47808",
      "router_ip":"192.168.204.200",
      "mstp_network":2000,
      "polling_enabled":true,
      "points": bench5007_points()
    })
}

fn default_registry() -> Value {
    json!({
      "site_id":"demo",
      "building_id":"rust-edge-demo",
      "bacnet_config": bacnet_config_value(),
      "drivers":[
        {
          "id":"bacnet-ip",
          "label":"BACnet/IP",
          "status":"online",
          "enabled":true,
          "override_scan":{"enabled":true,"cadence_seconds":3600,"method":"ReadProperty(priority-array) on writable points"},
          "devices":[
            bench5007_device()
          ]
        },
        {
          "id":"modbus-tcp",
          "label":"Modbus/TCP",
          "status":"online",
          "enabled":true,
          "devices":[
            {
              "unit_id":1,
              "name":"Plant Modbus Gateway",
              "address":"192.168.1.50:502",
              "points":[
                {"id":"modbus:tcp:1:40001","name":"CHW Plant Supply Temp","register":40001,"function":"holding_register","haystack_id":"point:chwst"},
                {"id":"modbus:tcp:1:40002","name":"Pump Speed Command","register":40002,"function":"holding_register","haystack_id":"point:pump-speed-cmd"}
              ]
            }
          ]
        },
        {
          "id":"json-api",
          "label":"JSON API",
          "status":"online",
          "enabled":true,
          "sources":[
            {"id":"openweather-oat","url":"https://api.openweathermap.org/data/2.5/weather","maps_to":"point:oat"},
            {"id":"plant-json-api","url":"http://edge-controller.local/api/points","maps_to":"plant telemetry"}
          ]
        },
        {
          "id":"haystack",
          "label":"Haystack Gateway",
          "status":"online",
          "enabled":true,
          "sites":[
            {"id":"site:demo","dis":"Demo Site"},
            {"id":"equip:5007","dis":"Device 5007 Bench","siteRef":"site:demo"}
          ],
          "note":"Niagara-style station integration is represented through Project Haystack read/nav/ops instead of custom Niagara WebSockets."
        }
      ]
    })
}

fn registry_path() -> PathBuf {
    workspace_dir()
        .join("data")
        .join("drivers")
        .join("bacnet")
        .join("driver_tree.json")
}

fn merge_missing_drivers(mut registry: Value) -> Value {
    let default = default_registry();
    let default_drivers = default
        .get("drivers")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let drivers = registry.as_object_mut().and_then(|obj| {
        if !obj.contains_key("drivers") {
            obj.insert("drivers".to_string(), json!([]));
        }
        obj.get_mut("drivers").and_then(|v| v.as_array_mut())
    });
    let Some(drivers) = drivers else {
        return default;
    };
    for driver in default_drivers {
        let id = driver.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if id.is_empty() {
            continue;
        }
        let present = drivers
            .iter()
            .any(|d| d.get("id").and_then(|v| v.as_str()) == Some(id));
        if !present {
            drivers.push(driver);
        }
    }
    registry
}

fn read_registry() -> Value {
    let path = registry_path();
    match fs::read_to_string(&path) {
        Ok(text) => {
            let parsed =
                serde_json::from_str::<Value>(&text).unwrap_or_else(|_| default_registry());
            merge_missing_drivers(parsed)
        }
        Err(_) => default_registry(),
    }
}

fn write_registry(value: &Value) {
    let path = registry_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(
        path,
        serde_json::to_string_pretty(value).unwrap_or_else(|_| "{}".to_string()),
    );
}

const COMMANDABLE_OBJECT_TYPES: &[&str] = &[
    "analog-output",
    "analog-value",
    "binary-output",
    "binary-value",
    "multi-state-output",
    "multi-state-value",
    "integer-value",
    "large-analog-value",
    "positive-integer-value",
];

fn point_object_type(point: &Value) -> String {
    if let Some(t) = point.get("object_type").and_then(|v| v.as_str()) {
        return t.to_string();
    }
    if let Some(id) = point.get("id").and_then(|v| v.as_str()) {
        let parts: Vec<&str> = id.split(':').collect();
        if parts.len() >= 4 {
            return parts[2].to_string();
        }
    }
    if let Some(arr) = point.get("object_id").and_then(|v| v.as_array()) {
        if let Some(class) = arr.first().and_then(|v| v.as_u64()) {
            return match class {
                0 => "analog-input".to_string(),
                1 => "analog-output".to_string(),
                2 => "analog-value".to_string(),
                3 => "binary-input".to_string(),
                4 => "binary-output".to_string(),
                5 => "binary-value".to_string(),
                19 => "multi-state-value".to_string(),
                _ => "object".to_string(),
            };
        }
    }
    String::new()
}

fn is_commandable_point(point: &Value) -> bool {
    if point.get("commandable").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    COMMANDABLE_OBJECT_TYPES.contains(&point_object_type(point).as_str())
}

fn enrich_point_from_device(mut point: Value, device: &Value) -> Value {
    if point.get("device_instance").is_none() {
        point["device_instance"] = device.get("device_instance").cloned().unwrap_or(json!(0));
    }
    if point.get("device_name").is_none() {
        point["device_name"] = device.get("name").cloned().unwrap_or(json!("unknown"));
    }
    if point.get("address").is_none() {
        point["address"] = device.get("address").cloned().unwrap_or(json!("unknown"));
    }
    if point.get("commandable").is_none() {
        point["commandable"] = json!(is_commandable_point(&point));
    }
    point
}

fn commandable_points(registry: &Value) -> Vec<Value> {
    let mut points = Vec::new();
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()).unwrap_or("") != "bacnet-ip" {
                continue;
            }
            if let Some(devices) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devices {
                    if let Some(dev_points) = device.get("points").and_then(|v| v.as_array()) {
                        for point in dev_points {
                            if is_commandable_point(point) {
                                points.push(enrich_point_from_device(point.clone(), device));
                            }
                        }
                    }
                }
            }
        }
    }
    points
}

fn writable_points(registry: &Value) -> Vec<Value> {
    commandable_points(registry)
}

fn bench_device_instance() -> u32 {
    env::var("OPENFDD_BACNET_DISCOVER_LOW")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(5007)
}

pub fn merge_live_discovery_into_registry(device_instance: u32) -> Value {
    if !bacnet_live::is_live_mode() {
        return json!({"ok": true, "skipped": true, "reason": "not live mode"});
    }
    let discovered =
        match bacnet_live::block_on(bacnet_live::discover_device_points(device_instance)) {
            Ok(points) => points,
            Err(err) => return json!({"ok": false, "error": err}),
        };

    let mut registry = read_registry();
    registry["bacnet_config"] = bacnet_config_value();

    let device_address = discovered
        .first()
        .and_then(|p| p.get("address"))
        .cloned()
        .unwrap_or(json!(""));

    if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()).unwrap_or("") != "bacnet-ip" {
                continue;
            }
            let mut devices = driver
                .get("devices")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();

            let existing_idx = devices.iter().position(|d| {
                d.get("device_instance")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32
                    == device_instance
            });

            let mut merged_by_id: std::collections::BTreeMap<String, Value> =
                std::collections::BTreeMap::new();
            if let Some(idx) = existing_idx {
                if let Some(existing_pts) = devices[idx].get("points").and_then(|v| v.as_array()) {
                    for p in existing_pts {
                        if let Some(id) = p.get("id").and_then(|v| v.as_str()) {
                            merged_by_id.insert(id.to_string(), p.clone());
                        }
                    }
                }
            }

            for p in discovered {
                let id = p
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if id.is_empty() {
                    continue;
                }
                let mut merged = merged_by_id.remove(&id).unwrap_or_else(|| json!({}));
                if let Some(obj) = merged.as_object_mut() {
                    if let Some(obj_p) = p.as_object() {
                        for (k, v) in obj_p {
                            obj.insert(k.clone(), v.clone());
                        }
                    }
                } else {
                    merged = p.clone();
                }
                merged_by_id.insert(id, merged);
            }

            let points: Vec<Value> = merged_by_id.into_values().collect();
            let mut device = if let Some(idx) = existing_idx {
                devices[idx].clone()
            } else {
                json!({
                    "device_instance": device_instance,
                    "name": format!("BACnet Device {device_instance}"),
                    "address": device_address,
                    "polling_enabled": true,
                    "points": []
                })
            };
            device["points"] = json!(points);
            if let Some(idx) = existing_idx {
                devices[idx] = device;
            } else {
                devices.push(device);
            }
            driver["devices"] = json!(devices);
            break;
        }
    }

    write_registry(&registry);
    json!({
        "ok": true,
        "device_instance": device_instance,
        "points": collect_bacnet_points(&registry).len(),
        "commandable_points": commandable_points(&registry).len(),
        "source": "rusty-bacnet"
    })
}

fn read_priority_array_for_point(point: &Value) -> Vec<(u8, Value)> {
    if bacnet_live::is_live_mode() {
        if let Some((device_instance, object_type, instance)) =
            bacnet_live::point_object_from_json(point)
        {
            if let Ok(values) = bacnet_live::block_on(bacnet_live::read_priority_array(
                device_instance,
                object_type,
                instance,
            )) {
                return values;
            }
        }
    }

    let name = point.get("name").and_then(|v| v.as_str()).unwrap_or("");
    if name == "ACTUATOR-0" {
        vec![(8, json!(55.0))]
    } else if name == "C06-0-10VDC-O" {
        vec![(1, json!(11.0))]
    } else {
        Vec::new()
    }
}

fn ensure_csv_header(path: &PathBuf) {
    if path.exists() {
        return;
    }
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{}", OVERRIDE_EXPORT_CSV_HEADER);
    }
}

fn ensure_legacy_csv_header(path: &PathBuf) {
    if path.exists() {
        return;
    }
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(
            file,
            "timestamp,scan_id,device_instance,device_name,address,point_id,object_id,point_name,haystack_id,priority,priority_kind,value,source_method"
        );
    }
}

fn append_csv(path: &PathBuf, row: &[String]) {
    ensure_csv_header(path);
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let line = row
            .iter()
            .map(|v| v.replace('"', "\"\""))
            .map(|v| format!("\"{}\"", v))
            .collect::<Vec<_>>()
            .join(",");
        let _ = writeln!(file, "{line}");
    }
}

fn read_csv(path: &PathBuf) -> String {
    fs::read_to_string(path).unwrap_or_else(|_| format!("{}\n", OVERRIDE_EXPORT_CSV_HEADER))
}

fn read_override_registry() -> Value {
    let path = override_registry_path();
    if let Ok(text) = fs::read_to_string(&path) {
        serde_json::from_str(&text).unwrap_or_else(|_| json!({}))
    } else if let Ok(text) = fs::read_to_string(legacy_overrides_dir().join("last_scan.json")) {
        serde_json::from_str(&text).unwrap_or_else(|_| json!({}))
    } else {
        json!({})
    }
}

fn write_override_registry(value: &Value) {
    let path = override_registry_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(
        path,
        serde_json::to_string_pretty(value).unwrap_or_else(|_| "{}".to_string()),
    );
    let _ = fs::write(
        legacy_overrides_dir().join("last_scan.json"),
        serde_json::to_string_pretty(value).unwrap_or_else(|_| "{}".to_string()),
    );
}

fn field_device_instances(registry: &Value) -> Vec<u32> {
    let mut devices = Vec::new();
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devs) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devs {
                    if device.get("local_server").and_then(|v| v.as_bool()) == Some(true) {
                        continue;
                    }
                    if let Some(inst) = device.get("device_instance").and_then(|v| v.as_u64()) {
                        devices.push(inst as u32);
                    }
                }
            }
        }
    }
    devices.sort_unstable();
    devices.dedup();
    devices
}

fn pick_scan_device(registry: &Value, override_reg: &Value) -> (u32, usize, u32) {
    let devices = field_device_instances(registry);
    if devices.is_empty() {
        let fallback = bench_device_instance();
        return (fallback, 0, fallback);
    }
    let rotation = override_reg
        .get("rotation_index")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as usize;
    let idx = rotation % devices.len();
    let device = devices[idx];
    let next_idx = (idx + 1) % devices.len();
    let next_device = devices[next_idx];
    (device, next_idx, next_device)
}

fn object_identifier_for_point(point: &Value) -> String {
    if let Some(id) = point.get("id").and_then(|v| v.as_str()) {
        return id.to_string();
    }
    let object_type = point_object_type(point);
    let instance = point
        .get("object_id")
        .and_then(|v| v.as_array())
        .and_then(|a| a.get(1))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    format!("{object_type}:{instance}")
}

fn export_csv_row(
    scanned_at: &str,
    point: &Value,
    priority: u8,
    priority_value: &Value,
    operator_priority: u8,
) -> Vec<String> {
    let kind = override_kind(priority, operator_priority);
    let operator = is_operator_override(priority, operator_priority);
    vec![
        scanned_at.to_string(),
        point
            .get("device_instance")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "0".to_string()),
        point
            .get("address")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        point
            .get("device_name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        object_identifier_for_point(point),
        point
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        point_object_type(point),
        point
            .get("value")
            .map(|v| v.to_string())
            .unwrap_or_else(|| priority_value.to_string()),
        priority.to_string(),
        priority_value.to_string(),
        operator.to_string(),
        kind.to_string(),
        point
            .get("unit")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        "ReadProperty(priority-array)".to_string(),
    ]
}

fn legacy_csv_row(
    scanned_at: &str,
    scan_id: &str,
    point: &Value,
    priority: u8,
    priority_value: &Value,
    operator_priority: u8,
) -> Vec<String> {
    let kind = override_kind(priority, operator_priority);
    vec![
        scanned_at.to_string(),
        scan_id.to_string(),
        point
            .get("device_instance")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "0".to_string()),
        point
            .get("device_name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        point
            .get("address")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        point
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        point
            .get("object_id")
            .map(|v| v.to_string())
            .unwrap_or_default(),
        point
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        point
            .get("haystack_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        priority.to_string(),
        kind.to_string(),
        priority_value.to_string(),
        "ReadProperty(priority-array)".to_string(),
    ]
}

pub fn overrides_summary_json() -> Value {
    let reg = read_override_registry();
    let summary = reg.get("summary").cloned().unwrap_or(json!({}));
    json!({
        "ok": true,
        "last_scan_at": reg.get("last_scan_at").cloned().unwrap_or(json!(null)),
        "last_scanned_device": reg.get("last_scanned_device").cloned().unwrap_or(json!(null)),
        "next_device": reg.get("next_device_instance").cloned().unwrap_or(json!(null)),
        "device_count": reg.get("device_count").cloned().unwrap_or(json!(0)),
        "operator_priority": reg.get("operator_priority").cloned().unwrap_or(json!(operator_override_priority())),
        "operator_override_count": summary.get("priority8").cloned().unwrap_or(json!(0)),
        "other_override_count": summary.get("non_priority8").cloned().unwrap_or(json!(0)),
        "total_override_count": summary.get("total").cloned().unwrap_or(json!(0)),
        "export_row_count": reg.get("export_row_count").cloned().unwrap_or(json!(0)),
        "scan_interval_s": reg.get("scan_interval_s").cloned().unwrap_or(json!(override_scan_interval_s())),
        "scan_health": reg.get("scan_health").cloned().unwrap_or(json!("unknown")),
        "scan_error": reg.get("scan_error").cloned().unwrap_or(json!(null))
    })
}

pub fn start_hourly_override_scanner(service_mode: String) {
    if service_mode != "commission" {
        return;
    }
    thread::spawn(move || loop {
        let _ = scan_once_value();
        thread::sleep(Duration::from_secs(override_scan_interval_s()));
    });
}

pub fn scan_once_value() -> Value {
    let operator_priority = operator_override_priority();
    let registry = read_registry();
    let override_reg = read_override_registry();
    let (device_instance, next_rotation, next_device) = pick_scan_device(&registry, &override_reg);
    let merge = merge_live_discovery_into_registry(device_instance);
    let device_count = field_device_instances(&registry).len().max(1) as u64;

    let mut scan_health = "ok".to_string();
    let mut scan_error: Option<String> = None;

    let scan_points: Vec<Value> = if bacnet_live::is_live_mode() {
        match bacnet_live::block_on(bacnet_live::discover_device_points(device_instance)) {
            Ok(discovered) => discovered
                .into_iter()
                .filter(|p| is_commandable_point(p))
                .map(|mut p| {
                    if p.get("device_instance").is_none() {
                        p["device_instance"] = json!(device_instance);
                    }
                    if p.get("device_name").is_none() {
                        p["device_name"] = json!(format!("Device {device_instance}"));
                    }
                    p
                })
                .collect(),
            Err(err) => {
                scan_health = "degraded".to_string();
                scan_error = Some(err.clone());
                commandable_points(&registry)
                    .into_iter()
                    .filter(|p| {
                        p.get("device_instance")
                            .and_then(|v| v.as_u64())
                            .map(|d| d as u32 == device_instance)
                            .unwrap_or(true)
                    })
                    .collect()
            }
        }
    } else {
        commandable_points(&registry)
            .into_iter()
            .filter(|p| {
                p.get("device_instance")
                    .and_then(|v| v.as_u64())
                    .map(|d| d as u32 == device_instance)
                    .unwrap_or(true)
            })
            .collect()
    };

    let scan_id = format!("bacnet-scan-{}", Utc::now().timestamp());
    let ts = now_rfc3339();
    let mut events: Vec<Value> = Vec::new();
    let mut p8_count = 0;
    let mut non_p8_count = 0;

    let export_path = export_csv_path();
    let legacy_all = legacy_overrides_dir().join("bacnet_overrides.csv");
    let legacy_p8 = legacy_overrides_dir().join("bacnet_priority8_overrides.csv");
    let legacy_other = legacy_overrides_dir().join("bacnet_non_priority8_overrides.csv");
    let split_p8 = csv_path("bacnet_priority8_overrides.csv");
    let split_other = csv_path("bacnet_non_priority8_overrides.csv");

    for point in &scan_points {
        let priority_values = read_priority_array_for_point(point);
        for (priority, value) in priority_values {
            let kind = override_kind(priority, operator_priority);
            if is_operator_override(priority, operator_priority) {
                p8_count += 1;
            } else {
                non_p8_count += 1;
            }

            let event = json!({
                "timestamp": ts,
                "scan_id": scan_id,
                "device_instance": point.get("device_instance").cloned().unwrap_or(json!(0)),
                "device_name": point.get("device_name").cloned().unwrap_or(json!("unknown")),
                "address": point.get("address").cloned().unwrap_or(json!("unknown")),
                "point_id": point.get("id").cloned().unwrap_or(json!("unknown")),
                "object_id": point.get("object_id").cloned().unwrap_or(json!([])),
                "point": point.get("name").cloned().unwrap_or(json!("unknown")),
                "haystack_id": point.get("haystack_id").cloned().unwrap_or(json!("")),
                "priority": priority,
                "priority_kind": kind,
                "level": kind,
                "value": value,
                "source_method": "ReadProperty(priority-array)"
            });

            let export_row = export_csv_row(&ts, point, priority, &value, operator_priority);
            append_csv(&export_path, &export_row);
            if is_operator_override(priority, operator_priority) {
                append_csv(&split_p8, &export_row);
            } else {
                append_csv(&split_other, &export_row);
            }
            let legacy_row =
                legacy_csv_row(&ts, &scan_id, point, priority, &value, operator_priority);
            ensure_legacy_csv_header(&legacy_all);
            append_csv(&legacy_all, &legacy_row);
            if is_operator_override(priority, operator_priority) {
                ensure_legacy_csv_header(&legacy_p8);
                append_csv(&legacy_p8, &legacy_row);
            } else {
                ensure_legacy_csv_header(&legacy_other);
                append_csv(&legacy_other, &legacy_row);
            }
            events.push(event);
        }
    }

    let export_row_count = count_csv_rows(&export_path);
    let status = json!({
        "ok": true,
        "last_scan": ts,
        "last_scan_at": ts,
        "scan_id": scan_id,
        "scanned_device": device_instance,
        "last_scanned_device": device_instance,
        "next_device_instance": next_device,
        "rotation_index": next_rotation,
        "device_count": device_count,
        "operator_priority": operator_priority,
        "scan_interval_s": override_scan_interval_s(),
        "scan_health": scan_health,
        "scan_error": scan_error,
        "export_row_count": export_row_count,
        "merge": merge,
        "commandable_point_count": scan_points.len(),
        "cadence": format!("{}s", override_scan_interval_s()),
        "method": "ReadProperty(priority-array) for commandable BACnet points",
        "csv": {
            "export": export_path.display().to_string(),
            "all": export_path.display().to_string(),
            "priority8": split_p8.display().to_string(),
            "non_priority8": split_other.display().to_string(),
            "legacy_all": legacy_all.display().to_string()
        },
        "summary": {
            "priority8": p8_count,
            "non_priority8": non_p8_count,
            "total": p8_count + non_p8_count
        },
        "overrides": events
    });

    write_override_registry(&status);
    status
}

fn count_csv_rows(path: &PathBuf) -> u64 {
    fs::read_to_string(path)
        .map(|text| {
            text.lines()
                .skip(1)
                .filter(|line| !line.trim().is_empty())
                .count() as u64
        })
        .unwrap_or(0)
}

fn collect_bacnet_points(registry: &Value) -> Vec<Value> {
    let mut points = Vec::new();
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()).unwrap_or("") != "bacnet-ip" {
                continue;
            }
            if let Some(devices) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devices {
                    if let Some(dev_points) = device.get("points").and_then(|v| v.as_array()) {
                        for point in dev_points {
                            let mut p = point.clone();
                            if p.get("device_instance").is_none() {
                                p["device_instance"] =
                                    device.get("device_instance").cloned().unwrap_or(json!(0));
                            }
                            if p.get("address").is_none() {
                                p["address"] =
                                    device.get("address").cloned().unwrap_or(json!("unknown"));
                            }
                            points.push(p);
                        }
                    }
                }
            }
        }
    }
    points
}

pub fn whois_json() -> String {
    if bacnet_live::is_live_mode() {
        match bacnet_live::block_on(bacnet_live::whois_devices()) {
            Ok(devices) => serde_json::to_string(&devices).unwrap_or_else(|_| "[]".to_string()),
            Err(err) => serde_json::to_string(&json!({"ok": false, "error": err}))
                .unwrap_or_else(|_| r#"{"ok":false}"#.to_string()),
        }
    } else {
        DEVICES_JSON.to_string()
    }
}

pub fn points_json() -> String {
    if bacnet_live::is_live_mode() {
        serde_json::to_string(&collect_bacnet_points(&read_registry()))
            .unwrap_or_else(|_| "[]".to_string())
    } else {
        POINTS_JSON.to_string()
    }
}

pub fn point_discovery_value(body: &Value) -> Value {
    let device_instance = body
        .get("device_instance")
        .and_then(|v| v.as_u64())
        .unwrap_or(5007) as u32;

    if bacnet_live::is_live_mode() {
        match bacnet_live::block_on(bacnet_live::discover_device_points(device_instance)) {
            Ok(points) => json!({
                "ok": true,
                "device_instance": device_instance,
                "points": points,
                "source": "rusty-bacnet"
            }),
            Err(err) => json!({"ok": false, "error": err}),
        }
    } else {
        json!({
            "ok": true,
            "status": "simulated registry loaded",
            "device_instance": device_instance,
            "points": bench5007_points()
        })
    }
}

pub fn sync_discovery_value() -> Value {
    let device_instance = bench_device_instance();
    if bacnet_live::is_live_mode() {
        return merge_live_discovery_into_registry(device_instance);
    }

    let points = bench5007_points();
    let mut registry = read_registry();
    registry["bacnet_config"] = bacnet_config_value();
    if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()).unwrap_or("") != "bacnet-ip" {
                continue;
            }
            let mut devices = driver
                .get("devices")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            devices.retain(|d| {
                d.get("device_instance")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32
                    != device_instance
            });
            let mut device = bench5007_device();
            device["points"] = json!(points);
            devices.push(device);
            driver["devices"] = json!(devices);
            break;
        }
    }
    write_registry(&registry);
    json!({
        "ok": true,
        "synced": true,
        "device_instance": device_instance,
        "points": points.len(),
        "source": "simulated"
    })
}

pub fn read_present_value_json(body: &Value) -> String {
    if bacnet_live::is_live_mode() {
        let resolved = body
            .get("point_id")
            .and_then(|v| v.as_str())
            .and_then(bacnet_live::point_object_from_id)
            .or_else(|| bacnet_live::point_object_from_json(body));

        if let Some((device_instance, object_type, instance)) = resolved {
            match bacnet_live::block_on(bacnet_live::read_present_value(
                device_instance,
                object_type,
                instance,
            )) {
                Ok(value) => {
                    return serde_json::to_string(&value).unwrap_or_else(|_| "{}".to_string())
                }
                Err(err) => {
                    return serde_json::to_string(&json!({"ok": false, "error": err}))
                        .unwrap_or_else(|_| r#"{"ok":false}"#.to_string())
                }
            }
        }
        return serde_json::to_string(&json!({
            "ok": false,
            "error": "point_id or device_instance/object_id required"
        }))
        .unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }

    r#"{"point":"Outside Air Temp","device_instance":5007,"value":62.0,"unit":"°F","source":"bacnet-simulated"}"#.to_string()
}

pub fn driver_tree_json() -> String {
    super::tree::driver_tree_compat_json()
}

pub fn read_registry_value() -> Value {
    read_registry()
}

pub fn overrides_last_scan() -> Value {
    read_override_registry()
}

pub fn poll_metrics() -> Value {
    let registry = read_registry();
    let points = collect_bacnet_points(&registry);
    let enabled = points
        .iter()
        .filter(|p| p.get("polling_enabled").and_then(|v| v.as_bool()) == Some(true))
        .count();
    json!({
        "samples": points.len(),
        "enabled_points": enabled,
        "at": now_rfc3339()
    })
}

pub fn count_discovered_devices(registry: &Value) -> u64 {
    count_field_devices(registry)
}

pub fn count_field_devices(registry: &Value) -> u64 {
    let mut count = 0_u64;
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devs) = driver.get("devices").and_then(|v| v.as_array()) {
                count += devs.len() as u64;
            }
        }
    }
    count
}

pub fn active_fault_count() -> u64 {
    overrides_last_scan()
        .get("summary")
        .and_then(|s| s.get("total"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
}

pub fn priority_array_json(body: &Value) -> String {
    if let Some(point_id) = body.get("point_id").and_then(|v| v.as_str()) {
        if bacnet_live::is_live_mode() {
            if let Some((device_instance, object_type, instance)) =
                bacnet_live::point_object_from_id(point_id)
            {
                let point = json!({
                    "id": point_id,
                    "device_instance": device_instance,
                    "object_id": [object_type.to_raw(), instance],
                });
                let slots: Vec<Value> = read_priority_array_for_point(&point)
                    .into_iter()
                    .map(|(priority, value)| {
                        json!({
                            "priority_level": priority,
                            "type": if value.is_null() { "null" } else { "value" },
                            "value": value
                        })
                    })
                    .collect();
                return serde_json::to_string(&json!({
                    "ok": true,
                    "point_id": point_id,
                    "priority_array": slots
                }))
                .unwrap_or_else(|_| "{}".to_string());
            }
        }
    }

    let registry = read_registry();
    let point_id = body.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
    for point in collect_bacnet_points(&registry) {
        let id = point.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if id != point_id && point.get("point_id").and_then(|v| v.as_str()) != Some(point_id) {
            continue;
        }
        let slots: Vec<Value> = read_priority_array_for_point(&point)
            .into_iter()
            .map(|(priority, value)| {
                json!({
                    "priority_level": priority,
                    "type": if value.is_null() { "null" } else { "value" },
                    "value": value
                })
            })
            .collect();
        return serde_json::to_string(
            &json!({"ok": true, "point_id": point_id, "priority_array": slots}),
        )
        .unwrap_or_else(|_| "{}".to_string());
    }
    serde_json::to_string(&json!({"ok": false, "error": "point not found"})).unwrap_or_default()
}

pub fn overrides_json() -> String {
    let reg = read_override_registry();
    if reg.as_object().map(|o| !o.is_empty()).unwrap_or(false) {
        serde_json::to_string_pretty(&reg).unwrap_or_else(|_| "{}".to_string())
    } else {
        serde_json::to_string_pretty(&scan_once_value()).unwrap_or_else(|_| "{}".to_string())
    }
}

pub fn overrides_csv() -> String {
    read_csv(&export_csv_path())
}

pub fn priority8_csv() -> String {
    read_csv(&csv_path("bacnet_priority8_overrides.csv"))
}

pub fn non_priority8_csv() -> String {
    read_csv(&csv_path("bacnet_non_priority8_overrides.csv"))
}

pub fn write_dry_run_json() -> &'static str {
    r#"{"ok":true,"dry_run":true,"safety":"BACnet write path requires integrator role and approved=true"}"#
}

pub fn commission_status_json() -> String {
    json!({
        "ok": true,
        "service": "bacnet-commission",
        "status": "ready",
        "config": bacnet_config_value(),
        "features": ["whois","object-list","read-property","priority-array-scan","csv-override-log","rusty-bacnet-live"]
    }).to_string()
}

pub fn poll_status_json() -> String {
    json!({
        "ok": true,
        "service": "bacnet-poll",
        "status": "ready",
        "config": bacnet_config_value(),
        "cadence_seconds": env::var("OPENFDD_BACNET_POLL_INTERVAL_SECONDS").unwrap_or_else(|_| "60".to_string()),
        "writes_scan_cadence_seconds": env::var("OPENFDD_BACNET_SCAN_INTERVAL_SECONDS").unwrap_or_else(|_| "3600".to_string())
    }).to_string()
}

#[cfg(test)]
mod override_export_tests {
    use super::*;
    use std::env;

    #[test]
    fn csv_header_has_stable_columns() {
        let cols: Vec<&str> = OVERRIDE_EXPORT_CSV_HEADER.split(',').collect();
        assert_eq!(cols.len(), 14);
        assert_eq!(cols[0], "scanned_at");
        assert_eq!(cols[10], "operator_override");
        assert_eq!(cols[11], "override_kind");
    }

    #[test]
    fn classifies_p8_vs_other_priority() {
        let op = operator_override_priority();
        assert!(is_operator_override(op, op));
        assert!(!is_operator_override(1, op));
        assert_eq!(override_kind(op, op), "operator");
        assert_eq!(override_kind(1, op), "supervisory");
    }

    #[test]
    fn registry_roundtrip_persists_scan_state() {
        let tmp = env::temp_dir().join(format!("openfdd-bacnet-override-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        env::set_var("OPENFDD_WORKSPACE", &tmp);
        let sample = json!({
            "last_scan_at": "2026-06-23T00:00:00Z",
            "last_scanned_device": 5007,
            "next_device_instance": 5007,
            "device_count": 1,
            "operator_priority": 8,
            "export_row_count": 2,
            "scan_health": "ok",
            "summary": {"priority8": 1, "non_priority8": 1, "total": 2}
        });
        write_override_registry(&sample);
        let loaded = read_override_registry();
        assert_eq!(loaded["last_scanned_device"], 5007);
        assert_eq!(loaded["export_row_count"], 2);
        assert!(override_registry_path().exists());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn export_csv_row_marks_operator_override() {
        let point = json!({
            "device_instance": 5007,
            "address": "192.168.204.200:47808",
            "device_name": "Bench",
            "id": "bacnet:5007:analog-output:2466",
            "name": "ACTUATOR-0",
            "object_id": [1, 2466],
            "unit": "%",
            "value": 55.0
        });
        let row = export_csv_row("2026-06-23T00:00:00Z", &point, 8, &json!(55.0), 8);
        assert_eq!(row[10], "true");
        assert_eq!(row[11], "operator");
    }
}
