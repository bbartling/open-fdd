//! Normalized driver tree for BAS-style React UI (Python-era parity).

use super::bacnet;
use super::bacnet_server;
use super::haystack;
use super::json_api;
use super::modbus;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};

const COMMANDABLE: &[&str] = &[
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

fn poll_label(seconds: u64) -> String {
    match seconds {
        60 => "1 min".to_string(),
        300 => "5 min".to_string(),
        600 => "10 min".to_string(),
        900 => "15 min".to_string(),
        0 => "off".to_string(),
        n => format!("{n}s"),
    }
}

fn object_type_from_point(point: &Value) -> String {
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
                0 => "analog-input",
                1 => "analog-output",
                2 => "analog-value",
                3 => "binary-input",
                4 => "binary-output",
                5 => "binary-value",
                19 => "multi-state-value",
                _ => "object",
            }
            .to_string();
        }
    }
    "object".to_string()
}

fn object_identifier(point: &Value, object_type: &str) -> String {
    if let Some(oid) = point.get("object_identifier").and_then(|v| v.as_str()) {
        return oid.to_string();
    }
    if let Some(arr) = point.get("object_id").and_then(|v| v.as_array()) {
        if arr.len() >= 2 {
            if let Some(inst) = arr.get(1).and_then(|v| v.as_u64()) {
                return format!("{object_type},{inst}");
            }
        }
    }
    if let Some(id) = point.get("id").and_then(|v| v.as_str()) {
        let parts: Vec<&str> = id.split(':').collect();
        if parts.len() >= 4 {
            return format!("{}:{}", parts[2], parts[3]);
        }
    }
    point
        .get("id")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string()
}

fn is_commandable(point: &Value, object_type: &str) -> bool {
    if point.get("writable").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    if point.get("commandable").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    COMMANDABLE.contains(&object_type)
}

fn override_map() -> HashMap<String, Value> {
    let mut map = HashMap::new();
    let raw = bacnet::overrides_last_scan();
    if let Some(events) = raw.get("overrides").and_then(|v| v.as_array()) {
        for ev in events {
            let pid = ev
                .get("point_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            if pid.is_empty() {
                continue;
            }
            let entry = map.entry(pid).or_insert_with(|| {
                json!({
                    "override_priorities": [],
                    "override_slots": [],
                    "has_override": false,
                    "operator_override": false
                })
            });
            let priority = ev.get("priority").and_then(|v| v.as_u64()).unwrap_or(0) as u8;
            if let Some(arr) = entry.get_mut("override_priorities").and_then(|v| v.as_array_mut()) {
                if !arr.iter().any(|p| p.as_u64() == Some(priority as u64)) {
                    arr.push(json!(priority));
                }
            }
            if let Some(arr) = entry.get_mut("override_slots").and_then(|v| v.as_array_mut()) {
                arr.push(json!({
                    "priority_level": priority,
                    "type": ev.get("priority_kind").cloned().unwrap_or(json!("override")),
                    "value": ev.get("value").cloned().unwrap_or(json!(null))
                }));
            }
            entry["has_override"] = json!(true);
            if priority == 8 {
                entry["operator_override"] = json!(true);
                entry["operator_override_value"] = ev.get("value").cloned().unwrap_or(json!(null));
            }
        }
    }
    map
}

fn bacnet_point_ui(point: &Value, device: &Value, overrides: &HashMap<String, Value>) -> Value {
    let object_type = object_type_from_point(point);
    let oid = object_identifier(point, &object_type);
    let point_id = point
        .get("point_id")
        .or_else(|| point.get("id"))
        .and_then(|v| v.as_str())
        .unwrap_or(&oid)
        .to_string();
    let poll_s = point
        .get("poll_interval_s")
        .or_else(|| point.get("poll_interval_seconds"))
        .and_then(|v| v.as_u64())
        .unwrap_or(if point.get("polling_enabled").and_then(|v| v.as_bool()) == Some(true) {
            60
        } else {
            0
        });
    let enabled = point.get("enabled").and_then(|v| v.as_bool()).unwrap_or(poll_s > 0);
    let mut out = json!({
        "point_id": point_id,
        "object_identifier": oid,
        "object_name": point.get("name").or_else(|| point.get("object_name")).cloned().unwrap_or(json!("")),
        "object_type": object_type,
        "enabled": enabled,
        "poll_interval_s": poll_s,
        "poll_label": poll_label(poll_s),
        "present_value": point.get("present_value").or_else(|| point.get("value")).cloned().unwrap_or(json!(null)),
        "units": point.get("units").or_else(|| point.get("unit")).cloned().unwrap_or(json!(null)),
        "commandable": is_commandable(point, &object_type),
        "last_read_at": point.get("last_read_at").cloned().unwrap_or(json!(null)),
        "haystack_id": point.get("haystack_id").cloned().unwrap_or(json!(null)),
        "local_server": point.get("local_server").cloned().unwrap_or(json!(false))
    });
    if let Some(ov) = overrides.get(&point_id) {
        if let Some(obj) = out.as_object_mut() {
            if let Some(ov_obj) = ov.as_object() {
                for (k, v) in ov_obj {
                    obj.insert(k.clone(), v.clone());
                }
            }
        }
    }
    let _ = device;
    out
}

pub fn bacnet_devices_ui() -> Vec<Value> {
    let registry = bacnet::read_registry_value();
    let overrides = override_map();
    let mut devices = Vec::new();

    devices.push(bacnet_server::local_server_device());

    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devs) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devs {
                    let inst = device
                        .get("device_instance")
                        .map(|v| v.to_string())
                        .unwrap_or_else(|| "?".to_string());
                    if inst == bacnet_server::device_instance().to_string() {
                        continue;
                    }
                    let points: Vec<Value> = device
                        .get("points")
                        .and_then(|v| v.as_array())
                        .map(|pts| {
                            pts.iter()
                                .map(|p| bacnet_point_ui(p, device, &overrides))
                                .collect()
                        })
                        .unwrap_or_default();
                    let poll_count = points
                        .iter()
                        .filter(|p| p.get("enabled").and_then(|v| v.as_bool()) == Some(true))
                        .count();
                    let operator_override_count = points
                        .iter()
                        .filter(|p| p.get("operator_override").and_then(|v| v.as_bool()) == Some(true))
                        .count();
                    let override_point_count = points
                        .iter()
                        .filter(|p| p.get("has_override").and_then(|v| v.as_bool()) == Some(true))
                        .count();
                    devices.push(json!({
                        "device_instance": inst.trim_matches('"'),
                        "device_address": device.get("address").cloned().unwrap_or(json!("")),
                        "device_name": device.get("name").cloned().unwrap_or(json!("")),
                        "point_count": points.len(),
                        "poll_count": poll_count,
                        "override_point_count": override_point_count,
                        "operator_override_count": operator_override_count,
                        "points": points
                    }));
                }
            }
        }
    }
    devices
}

pub fn modbus_devices_ui() -> Vec<Value> {
    let registry = bacnet::read_registry_value();
    let mut devices = Vec::new();
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("modbus-tcp") {
                continue;
            }
            if let Some(devs) = driver.get("devices").and_then(|v| v.as_array()) {
                for dev in devs {
                    let host_port = dev
                        .get("address")
                        .and_then(|v| v.as_str())
                        .unwrap_or("127.0.0.1:502");
                    let (host, port) = host_port.split_once(':').unwrap_or((host_port, "502"));
                    let unit_id = dev
                        .get("unit_id")
                        .map(|v| v.to_string())
                        .unwrap_or_else(|| "1".to_string());
                    let device_key = format!("{host}:{port}:{unit_id}");
                    let points: Vec<Value> = dev
                        .get("points")
                        .and_then(|v| v.as_array())
                        .map(|pts| {
                            pts.iter()
                                .map(|p| {
                                    let point_id = p
                                        .get("id")
                                        .and_then(|v| v.as_str())
                                        .unwrap_or("modbus:point")
                                        .to_string();
                                    let poll_s = if p.get("polling_enabled").and_then(|v| v.as_bool()) == Some(true) {
                                        60
                                    } else {
                                        0
                                    };
                                    json!({
                                        "point_id": point_id,
                                        "label": p.get("name").cloned().unwrap_or(json!(point_id)),
                                        "register_address": p.get("register").cloned().unwrap_or(json!(null)),
                                        "function": p.get("function").cloned().unwrap_or(json!("holding_register")),
                                        "object_type": p.get("function").cloned().unwrap_or(json!("holding_register")),
                                        "enabled": poll_s > 0,
                                        "poll_interval_s": poll_s,
                                        "poll_label": poll_label(poll_s),
                                        "present_value": p.get("value").cloned().unwrap_or(json!(null)),
                                        "units": p.get("unit").cloned().unwrap_or(json!(null)),
                                        "haystack_id": p.get("haystack_id").cloned().unwrap_or(json!(null))
                                    })
                                })
                                .collect()
                        })
                        .unwrap_or_default();
                    let poll_count = points.iter().filter(|p| p.get("enabled").and_then(|v| v.as_bool()) == Some(true)).count();
                    devices.push(json!({
                        "device_key": device_key,
                        "host": host,
                        "port": port,
                        "unit_id": unit_id.trim_matches('"'),
                        "device_instance": unit_id.trim_matches('"'),
                        "device_address": host_port,
                        "point_count": points.len(),
                        "poll_count": poll_count,
                        "points": points
                    }));
                }
            }
        }
    }
    devices
}

pub fn json_api_devices_ui() -> Vec<Value> {
    let registry = bacnet::read_registry_value();
    let mut by_host: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("json-api") {
                continue;
            }
            if let Some(sources) = driver.get("sources").and_then(|v| v.as_array()) {
                for src in sources {
                    let url = src.get("url").and_then(|v| v.as_str()).unwrap_or("http://localhost/");
                    let host = url.split('/').nth(2).unwrap_or("localhost").to_string();
                    let point_id = src
                        .get("id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("json-api:point")
                        .to_string();
                    by_host.entry(host.clone()).or_default().push(json!({
                        "point_id": point_id,
                        "label": point_id,
                        "url": url,
                        "method": "GET",
                        "json_path": src.get("maps_to").cloned().unwrap_or(json!("$")),
                        "object_type": "GET",
                        "enabled": false,
                        "poll_interval_s": 0,
                        "poll_label": "off",
                        "present_value": json!(null),
                        "units": json!(null)
                    }));
                }
            }
        }
    }
    by_host
        .into_iter()
        .map(|(host, points)| {
            json!({
                "device_key": host.clone(),
                "host": host,
                "point_count": points.len(),
                "poll_count": 0,
                "points": points
            })
        })
        .collect()
}

pub fn haystack_devices_ui() -> Vec<Value> {
    let model: Value = serde_json::from_str(haystack::model_json()).unwrap_or(json!({}));
    let rows = model.get("rows").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let mut sites: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for row in rows {
        let id = row.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if row.get("point").and_then(|v| v.as_str()) == Some("M") {
            let site = row
                .get("siteRef")
                .and_then(|v| v.as_str())
                .unwrap_or("site:demo")
                .to_string();
            sites.entry(site).or_default().push(json!({
                "point_id": id,
                "label": row.get("dis").cloned().unwrap_or(json!(id)),
                "haystack_id": id,
                "tags": row,
                "kind": row.get("sensor").cloned().unwrap_or(json!(null)),
                "unit": json!(null),
                "curVal": json!(null),
                "enabled": false,
                "poll_interval_s": 0,
                "poll_label": "off",
                "mapping_status": if row.get("bacnetRef").is_some() || row.get("modbusRef").is_some() { "mapped" } else { "unmapped" }
            }));
        }
    }
    sites
        .into_iter()
        .map(|(site_id, points)| {
            json!({
                "device_key": site_id.clone(),
                "host": site_id,
                "site_id": site_id,
                "point_count": points.len(),
                "poll_count": 0,
                "points": points
            })
        })
        .collect()
}

fn driver_root(id: &str, protocol: &str, label: &str, status: &str, child_count: usize, summary: Value) -> Value {
    json!({
        "id": id,
        "protocol": protocol,
        "label": label,
        "enabled": true,
        "status": status,
        "summary": summary,
        "child_count": child_count,
        "actions": []
    })
}

pub fn unified_tree_value() -> Value {
    let bacnet_devices = bacnet_devices_ui();
    let modbus_devices = modbus_devices_ui();
    let json_devices = json_api_devices_ui();
    let haystack_devices = haystack_devices_ui();
    let config = bacnet::bacnet_config_value();
    json!({
        "ok": true,
        "roots": [
            driver_root("bacnet-ip", "bacnet", "BACnet/IP", "online", bacnet_devices.len(), json!({
                "bind": config.get("bind"),
                "mode": config.get("mode"),
                "poll_interval_seconds": config.get("poll_interval_seconds"),
                "last_sample_at": bacnet::poll_metrics().get("at")
            })),
            driver_root("haystack", "haystack", "Haystack", "online", haystack_devices.len(), json!({"gateway": "openfdd-haystack-gateway"})),
            driver_root("modbus-tcp", "modbus", "Modbus TCP", modbus::commission_status_mode(), modbus_devices.len(), modbus::modbus_config_value()),
            driver_root("json-api", "json_api", "JSON API", "online", json_devices.iter().map(|d| d.get("point_count").and_then(|v| v.as_u64()).unwrap_or(0)).sum::<u64>() as usize, json!({"sources": json_api::sources_json()}))
        ],
        "bacnet": { "devices": bacnet_devices, "config": config },
        "modbus": { "devices": modbus_devices },
        "json_api": { "devices": json_devices },
        "haystack": { "devices": haystack_devices }
    })
}

pub fn unified_tree_json() -> String {
    serde_json::to_string_pretty(&unified_tree_value()).unwrap_or_else(|_| "{}".to_string())
}

pub fn driver_tree_compat_json() -> String {
    let registry = bacnet::read_registry_value();
    let mut root = registry.as_object().cloned().unwrap_or_default();
    root.insert("devices".to_string(), json!(bacnet_devices_ui()));
    root.insert("modbus_devices".to_string(), json!(modbus_devices_ui()));
    root.insert("json_api_devices".to_string(), json!(json_api_devices_ui()));
    root.insert("haystack_devices".to_string(), json!(haystack_devices_ui()));
    root.insert("tree".to_string(), unified_tree_value());
    serde_json::to_string_pretty(&Value::Object(root)).unwrap_or_else(|_| "{}".to_string())
}

pub fn overrides_status_ui() -> Value {
    let scan = bacnet::overrides_last_scan();
    let summary = scan.get("summary").cloned().unwrap_or(json!({}));
    let registry = bacnet::read_registry_value();
    let device_count = bacnet::count_field_devices(&registry);
    json!({
        "ok": true,
        "device_count": device_count,
        "scan_interval_s": 3600,
        "full_rotation_hours": device_count.max(1),
        "operator_priority": 8,
        "operator_override_points": summary.get("priority8").cloned().unwrap_or(json!(0)),
        "total_override_points": summary.get("total").cloned().unwrap_or(json!(0)),
        "last_scan_at": scan.get("last_scan").cloned().unwrap_or(json!(null)),
        "last_scan_device": scan.get("scanned_device").cloned().unwrap_or(json!(null)),
        "next_device_instance": scan.get("next_device_instance").cloned().unwrap_or(json!(null)),
        "export_row_count": summary.get("total").cloned().unwrap_or(json!(0))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unified_tree_has_four_roots() {
        let tree = unified_tree_value();
        let roots = tree.get("roots").and_then(|v| v.as_array()).unwrap();
        assert_eq!(roots.len(), 4);
    }

    #[test]
    fn bacnet_devices_include_local_server() {
        let devices = bacnet_devices_ui();
        assert!(devices.iter().any(|d| d.get("local_server").and_then(|v| v.as_bool()) == Some(true)));
    }

    #[test]
    fn commandable_analog_value_detected() {
        let point = json!({"id":"bacnet:1001:analog-value:4","writable":true,"object_id":[2,4]});
        assert!(is_commandable(&point, "analog-value"));
        assert!(!is_commandable(&json!({"object_id":[0,1]}), "analog-input"));
    }
}
