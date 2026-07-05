//! BACnet driver facade — live rusty-bacnet only (no simulated OT data).

use super::bacnet_live;
use super::bacnet_server;
use super::live_gate;
use crate::validation::profile::active_profile;
use bacnet_types::enums::ObjectType;
use bacnet_types::primitives::PropertyValue;
use chrono::{Duration as ChronoDuration, Utc};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

static BACNET_POLL_SAMPLES: AtomicU64 = AtomicU64::new(0);
static BACNET_LAST_POLL: Mutex<Option<String>> = Mutex::new(None);

fn profile_device_instance() -> u32 {
    let p = active_profile();
    if p.device_instance > 0 {
        p.device_instance
    } else {
        env::var("OPENFDD_BACNET_DISCOVER_LOW")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(0)
    }
}

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

pub fn override_retention_years() -> u32 {
    env::var("OFDD_OVERRIDE_CSV_RETENTION_YEARS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1)
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
    let mode = if bacnet_live::is_live_mode() {
        "live"
    } else {
        "disabled"
    };
    json!({
        "mode": mode,
        "iface": env::var("OPENFDD_BACNET_IFACE").unwrap_or_default(),
        "bind": env::var("OPENFDD_BACNET_BIND").unwrap_or_default(),
        "device_instance": env::var("OPENFDD_BACNET_DEVICE_INSTANCE").unwrap_or_else(|_| "599999".to_string()),
        "device_name": env::var("OPENFDD_BACNET_DEVICE_NAME").unwrap_or_else(|_| "OpenFDD".to_string()),
        "scan_interval_seconds": env::var("OPENFDD_BACNET_SCAN_INTERVAL_SECONDS").unwrap_or_else(|_| "3600".to_string()),
        "poll_interval_seconds": env::var("OPENFDD_BACNET_POLL_INTERVAL_SECONDS").unwrap_or_else(|_| "60".to_string()),
        "router_ip": env::var("OPENFDD_BACNET_ROUTER_IP").unwrap_or_default(),
        "mstp_network": env::var("OPENFDD_BACNET_MSTP_NET").unwrap_or_default(),
        "discover_low": env::var("OPENFDD_BACNET_DISCOVER_LOW").unwrap_or_else(|_| "0".to_string()),
        "discover_high": env::var("OPENFDD_BACNET_DISCOVER_HIGH").unwrap_or_else(|_| "4194303".to_string())
    })
}

fn haystack_registry_sites() -> Value {
    let mut sites = Vec::new();
    for row in crate::model::query::haystack_rows() {
        if row.get("site").and_then(|v| v.as_str()) == Some("M") {
            sites.push(json!({
                "id": row.get("id").cloned().unwrap_or(Value::Null),
                "dis": row.get("dis").cloned().unwrap_or(Value::Null)
            }));
        } else if row.get("equip").and_then(|v| v.as_str()) == Some("M") {
            sites.push(json!({
                "id": row.get("id").cloned().unwrap_or(Value::Null),
                "dis": row.get("dis").cloned().unwrap_or(Value::Null),
                "siteRef": row.get("siteRef").cloned().unwrap_or(Value::Null)
            }));
        }
    }
    json!(sites)
}

fn default_registry() -> Value {
    let bacnet_devices = json!([]);
    let modbus_devices = json!([]);
    let site_id =
        crate::model::scope::active_site_id().unwrap_or_else(|| "site:unknown".to_string());
    let site_slug = site_id.trim_start_matches("site:");
    json!({
      "site_id": site_slug,
      "building_id": format!("{site_slug}-main"),
      "bacnet_config": bacnet_config_value(),
      "drivers":[
        {
          "id":"bacnet-ip",
          "label":"BACnet/IP",
          "status":"online",
          "enabled":true,
          "override_scan":{"enabled":true,"cadence_seconds":3600,"method":"ReadProperty(priority-array) on writable points"},
          "devices": bacnet_devices
        },
        {
          "id":"modbus-tcp",
          "label":"Modbus/TCP",
          "status":"online",
          "enabled":true,
          "devices": modbus_devices
        },
        {
          "id":"json-api",
          "label":"JSON API",
          "status":"not_configured",
          "enabled": false,
          "configured": false,
          "sources":[]
        },
        {
          "id":"haystack",
          "label":"Haystack Gateway",
          "status":"online",
          "enabled":true,
          "sites": haystack_registry_sites(),
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

fn whois_cache_path() -> PathBuf {
    workspace_dir()
        .join("data")
        .join("drivers")
        .join("bacnet")
        .join("whois_discovered.json")
}

fn instances_from_whois_devices(devices: &[Value]) -> Vec<u32> {
    let local = bacnet_server::device_instance();
    let mut out = Vec::new();
    for dev in devices {
        let Some(inst) = dev
            .get("object_identifier")
            .and_then(|o| o.get("instance"))
            .and_then(|v| v.as_u64())
            .map(|n| n as u32)
            .or_else(|| {
                dev.get("device_instance")
                    .and_then(|v| v.as_u64())
                    .map(|n| n as u32)
            })
        else {
            continue;
        };
        if inst != local && inst > 0 {
            out.push(inst);
        }
    }
    out.sort_unstable();
    out.dedup();
    out
}

fn persist_whois_discoveries(devices: &[Value]) {
    let instances = instances_from_whois_devices(devices);
    if instances.is_empty() {
        return;
    }
    let path = whois_cache_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let payload = json!({
        "updated_at": now_rfc3339(),
        "instances": instances,
        "devices": devices
    });
    let _ = fs::write(
        path,
        serde_json::to_string_pretty(&payload).unwrap_or_else(|_| "{}".to_string()),
    );
}

fn cached_whois_instances() -> Vec<u32> {
    let path = whois_cache_path();
    if !path.exists() {
        return Vec::new();
    }
    let Ok(text) = fs::read_to_string(&path) else {
        return Vec::new();
    };
    let Ok(v) = serde_json::from_str::<Value>(&text) else {
        return Vec::new();
    };
    v.get("instances")
        .and_then(|a| a.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|x| x.as_u64().map(|n| n as u32))
                .collect()
        })
        .unwrap_or_default()
}

/// Address from Who-Is cache for a field instance (if known).
fn cached_whois_address(device_instance: u32) -> Option<String> {
    let path = whois_cache_path();
    let text = fs::read_to_string(path).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    let devices = v.get("devices")?.as_array()?;
    for dev in devices {
        let inst = dev
            .get("object_identifier")
            .and_then(|o| o.get("instance"))
            .and_then(|x| x.as_u64())
            .or_else(|| dev.get("device_instance").and_then(|x| x.as_u64()))
            .map(|n| n as u32);
        if inst == Some(device_instance) {
            if let Some(addr) = dev.get("address").and_then(|a| a.as_str()) {
                if !addr.is_empty() {
                    return Some(addr.to_string());
                }
            }
        }
    }
    None
}

/// Ensure a field device appears in the driver tree even when live point discovery fails.
/// Who-Is alone must be enough for `GET /api/bacnet/driver/tree` to list the instance.
fn ensure_field_device_shell(device_instance: u32, address: Option<String>) -> bool {
    let local = bacnet_server::device_instance();
    if device_instance == 0 || device_instance == local {
        return false;
    }
    let mut registry = read_registry();
    registry["bacnet_config"] = bacnet_config_value();
    let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) else {
        return false;
    };
    for driver in drivers {
        if driver.get("id").and_then(|v| v.as_str()).unwrap_or("") != "bacnet-ip" {
            continue;
        }
        let mut devices = driver
            .get("devices")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        if devices.iter().any(|d| {
            d.get("device_instance")
                .and_then(|v| v.as_u64())
                .unwrap_or(0) as u32
                == device_instance
        }) {
            return false;
        }
        let addr = address
            .or_else(|| cached_whois_address(device_instance))
            .unwrap_or_default();
        devices.push(json!({
            "device_instance": device_instance,
            "name": format!("BACnet Device {device_instance}"),
            "address": addr,
            "polling_enabled": true,
            "points": [],
            "source": "whois-shell"
        }));
        driver["devices"] = json!(devices);
        write_registry(&registry);
        return true;
    }
    false
}

/// Fast path for GET tree: promote Who-Is cache entries into the registry **without**
/// live BACnet I/O (live discovery can block for many seconds and must not hang the API).
fn merge_missing_field_devices_from_cache() {
    let existing = field_device_instances(&read_registry());
    let existing: std::collections::HashSet<u32> = existing.into_iter().collect();
    let mut candidates = cached_whois_instances();
    candidates.extend(whois_discovered_instances());
    candidates.sort_unstable();
    candidates.dedup();
    for inst in candidates {
        if !existing.contains(&inst) {
            let _ = ensure_field_device_shell(inst, cached_whois_address(inst));
        }
    }
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

fn sanitize_registry_for_live_mode(registry: Value) -> Value {
    registry
}

fn read_registry() -> Value {
    let path = registry_path();
    let registry = match fs::read_to_string(&path) {
        Ok(text) => {
            let parsed =
                serde_json::from_str::<Value>(&text).unwrap_or_else(|_| default_registry());
            merge_missing_drivers(parsed)
        }
        Err(_) => default_registry(),
    };
    sanitize_registry_for_live_mode(registry)
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

fn bench_device_instance() -> u32 {
    env::var("OPENFDD_BACNET_DISCOVER_LOW")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(profile_device_instance)
}

pub fn merge_live_discovery_into_registry(device_instance: u32) -> Value {
    if !bacnet_live::is_live_mode() {
        return json!({"ok": true, "skipped": true, "reason": "not live mode"});
    }
    let discovered = match bacnet_live::block_on(bacnet_live::discover_device_points_with_fallback(
        device_instance,
    )) {
        Ok(points) => points,
        Err(err) => return json!({"ok": false, "error": err}),
    };

    let mut registry = read_registry();
    registry["bacnet_config"] = bacnet_config_value();
    let points_before = collect_bacnet_points(&registry).len();

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
    let total = collect_bacnet_points(&registry).len();
    json!({
        "ok": true,
        "device_instance": device_instance,
        "points": total,
        "rows_added": total.saturating_sub(points_before),
        "total": total,
        "commandable_points": commandable_points(&registry).len(),
        "source": "rusty-bacnet"
    })
}

fn registry_pollable_point_count(registry: &Value) -> usize {
    let mut count = 0_usize;
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devs) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devs {
                    if let Some(pts) = device.get("points").and_then(|v| v.as_array()) {
                        count += pts
                            .iter()
                            .filter(|p| {
                                p.get("polling_enabled").and_then(|v| v.as_bool()) == Some(true)
                            })
                            .count();
                    }
                }
            }
        }
    }
    count
}

fn merge_ui_objects_into_registry(device_instance: u32, body: &Value, objects: &[Value]) -> Value {
    if objects.is_empty() {
        return json!({"ok": false, "error": "objects array empty"});
    }
    let device_address = body
        .get("device_address")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let replace = body
        .get("replace")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let mut discovered: Vec<Value> = Vec::new();
    for obj in objects {
        let Some(oid_str) = obj.get("object_identifier").and_then(|v| v.as_str()) else {
            continue;
        };
        let Some((ot_name, inst)) = oid_str.split_once(',') else {
            continue;
        };
        let instance: u32 = match inst.trim().parse() {
            Ok(n) => n,
            Err(_) => continue,
        };
        let name = obj
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(ot_name)
            .to_string();
        let writable = obj
            .get("commandable")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        discovered.push(json!({
            "id": format!("bacnet:{device_instance}:{}:{instance}", ot_name.trim()),
            "device_instance": device_instance,
            "object_id": [object_type_class(ot_name.trim()), instance],
            "name": name,
            "polling_enabled": true,
            "writable": writable,
            "present_value": Value::Null,
            "address": device_address,
        }));
    }

    if discovered.is_empty() {
        return json!({"ok": false, "error": "no valid BACnet objects supplied"});
    }

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

            let existing_idx = devices.iter().position(|d| {
                d.get("device_instance")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32
                    == device_instance
            });

            let mut merged_by_id: BTreeMap<String, Value> = BTreeMap::new();
            if !replace {
                if let Some(idx) = existing_idx {
                    if let Some(existing_pts) =
                        devices[idx].get("points").and_then(|v| v.as_array())
                    {
                        for p in existing_pts {
                            if let Some(id) = p.get("id").and_then(|v| v.as_str()) {
                                merged_by_id.insert(id.to_string(), p.clone());
                            }
                        }
                    }
                }
            }

            let prior_count = if replace {
                0
            } else if let Some(idx) = existing_idx {
                devices[idx]
                    .get("points")
                    .and_then(|v| v.as_array())
                    .map(|pts| pts.len())
                    .unwrap_or(0)
            } else {
                0
            };

            let discovered_count = discovered.len();
            for p in discovered {
                let id = p
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if id.is_empty() {
                    continue;
                }
                merged_by_id.insert(id, p);
            }

            let points: Vec<Value> = merged_by_id.into_values().collect();
            let rows_added = if replace {
                discovered_count
            } else {
                points.len().saturating_sub(prior_count)
            };
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
            write_registry(&registry);
            let total = collect_bacnet_points(&registry).len();
            return json!({
                "ok": true,
                "device_instance": device_instance,
                "rows_added": rows_added,
                "total": total,
                "points": total,
                "source": "ui-sync"
            });
        }
    }
    json!({"ok": false, "error": "bacnet-ip driver missing from registry"})
}

fn object_type_class(object_type: &str) -> u8 {
    match object_type {
        "analog-input" => 0,
        "analog-output" => 1,
        "analog-value" => 2,
        "binary-input" => 3,
        "binary-output" => 4,
        "binary-value" => 5,
        "multi-state-value" => 19,
        _ => 2,
    }
}

fn discovery_objects_from_points(points: &[Value]) -> Vec<Value> {
    points
        .iter()
        .filter_map(|p| {
            let id = p.get("id").and_then(|v| v.as_str())?;
            let parts: Vec<&str> = id.split(':').collect();
            if parts.len() != 4 || parts[0] != "bacnet" {
                return None;
            }
            Some(json!({
                "object_identifier": format!("{},{}", parts[2], parts[3]),
                "name": p.get("name").cloned().unwrap_or(json!(parts[2])),
                "commandable": p.get("writable").and_then(|v| v.as_bool()).unwrap_or(false),
            }))
        })
        .collect()
}

fn read_priority_array_for_point(point: &Value) -> Vec<(u8, Value)> {
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
    Vec::new()
}

fn read_priority_arrays_rpm_for_points(
    device_instance: u32,
    points: &[Value],
) -> BTreeMap<String, Vec<(u8, Value)>> {
    let mut objects = Vec::new();
    let mut id_by_key: BTreeMap<String, String> = BTreeMap::new();
    for point in points {
        let Some((dev, object_type, instance)) = bacnet_live::point_object_from_json(point) else {
            continue;
        };
        if dev != device_instance {
            continue;
        }
        let pid = point
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        id_by_key.insert(format!("{}:{}", object_type.to_raw(), instance), pid);
        objects.push((object_type, instance));
    }
    let Ok(map) = bacnet_live::block_on(bacnet_live::read_priority_arrays_rpm(
        device_instance,
        &objects,
    )) else {
        return BTreeMap::new();
    };
    let mut out = BTreeMap::new();
    for ((object_type, instance), slots) in map {
        let key = format!("{}:{}", object_type.to_raw(), instance);
        if let Some(pid) = id_by_key.get(&key) {
            out.insert(pid.clone(), slots);
        }
    }
    out
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
    prune_csv_older_than_years(path, override_retention_years());
}

fn parse_csv_timestamp(line: &str) -> Option<chrono::DateTime<Utc>> {
    let first = line.split(',').next()?.trim_matches('"');
    chrono::DateTime::parse_from_rfc3339(first)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
}

fn prune_csv_older_than_years(path: &PathBuf, years: u32) {
    if years == 0 {
        return;
    }
    let Ok(text) = fs::read_to_string(path) else {
        return;
    };
    let mut lines: Vec<&str> = text.lines().collect();
    if lines.len() <= 1 {
        return;
    }
    let header = lines.remove(0);
    let cutoff = Utc::now() - ChronoDuration::days(i64::from(years) * 365);
    lines.retain(|line| {
        if line.trim().is_empty() {
            return false;
        }
        parse_csv_timestamp(line)
            .map(|ts| ts >= cutoff)
            .unwrap_or(true)
    });
    let mut out = String::from(header);
    out.push('\n');
    for line in lines {
        out.push_str(line);
        out.push('\n');
    }
    let _ = fs::write(path, out);
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

fn whois_discovered_instances() -> Vec<u32> {
    if !bacnet_live::is_live_mode() {
        return Vec::new();
    }
    let devices = match bacnet_live::block_on(bacnet_live::whois_devices_with_range(None, None)) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let local_inst = env::var("OPENFDD_BACNET_DEVICE_INSTANCE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(599999);
    let mut out = Vec::new();
    for dev in devices {
        let Some(inst) = dev
            .get("object_identifier")
            .and_then(|o| o.get("instance"))
            .and_then(|v| v.as_u64())
            .map(|n| n as u32)
        else {
            continue;
        };
        if inst != local_inst {
            out.push(inst);
        }
    }
    out.sort_unstable();
    out.dedup();
    out
}

/// Merge cached Who-Is results into driver tree (no live I/O — safe for GET handlers).
fn ensure_field_devices_from_whois() {
    merge_missing_field_devices_from_cache();
}

fn field_device_instances(registry: &Value) -> Vec<u32> {
    let local = bacnet_server::device_instance();
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
                        let inst = inst as u32;
                        if inst != local {
                            devices.push(inst);
                        }
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
    let mut devices = field_device_instances(registry);
    if devices.is_empty() {
        ensure_field_devices_from_whois();
        devices = field_device_instances(&read_registry());
    }
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
        if bacnet_live::is_live_mode() {
            let _ = scan_once_value();
        }
        thread::sleep(Duration::from_secs(override_scan_interval_s()));
    });
}

pub fn poll_interval_s() -> u64 {
    env::var("OPENFDD_BACNET_POLL_INTERVAL_SECONDS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(60)
}

pub fn start_field_device_sync_loop(service_mode: String) {
    if service_mode != "bridge" && service_mode != "commission" {
        return;
    }
    thread::spawn(|| loop {
        ensure_field_devices_from_whois();
        thread::sleep(Duration::from_secs(30));
    });
}

pub fn start_bacnet_poll_loop(service_mode: String) {
    if service_mode != "bridge" && service_mode != "commission" {
        return;
    }
    thread::spawn(move || loop {
        if bacnet_live::is_live_mode() {
            let _ = poll_cycle_value();
        }
        thread::sleep(Duration::from_secs(poll_interval_s()));
    });
}

pub fn poll_cycle_value() -> Value {
    if let Some(err) = live_gate::bacnet_live_required("poll") {
        return err;
    }
    let mut registry = read_registry();
    if registry_pollable_point_count(&registry) == 0 {
        ensure_field_devices_from_whois();
        registry = read_registry();
        if registry_pollable_point_count(&registry) == 0 {
            let inst = bench_device_instance();
            let local = bacnet_server::device_instance();
            if inst > 0 && inst != local {
                merge_live_discovery_into_registry(inst);
                registry = read_registry();
            }
        }
    }
    let mut updated = 0_u64;
    let mut samples = 0_u64;
    let mut working = registry.clone();
    let mut all_reads: Vec<Value> = Vec::new();
    if let Some(drivers) = registry.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devs) = driver.get("devices").and_then(|v| v.as_array()) {
                for device in devs {
                    let device_instance = device
                        .get("device_instance")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0) as u32;
                    if device_instance == 0 {
                        continue;
                    }
                    let points: Vec<Value> = device
                        .get("points")
                        .and_then(|v| v.as_array())
                        .map(|pts| {
                            pts.iter()
                                .filter(|p| {
                                    p.get("polling_enabled").and_then(|v| v.as_bool()) == Some(true)
                                })
                                .cloned()
                                .collect()
                        })
                        .unwrap_or_default();
                    if points.is_empty() {
                        continue;
                    }
                    let objects: Vec<(ObjectType, u32)> = points
                        .iter()
                        .filter_map(bacnet_live::point_object_from_json)
                        .map(|(_, ot, inst)| (ot, inst))
                        .collect();
                    if let Ok(reads) = bacnet_live::block_on(bacnet_live::poll_present_values_rpm(
                        device_instance,
                        &objects,
                    )) {
                        samples += reads.len() as u64;
                        all_reads.extend(reads.iter().cloned());
                        updated += apply_poll_reads(&mut working, device_instance, &reads);
                    }
                }
            }
        }
    }
    if updated > 0 {
        write_registry(&working);
    }
    if samples > 0 && !all_reads.is_empty() {
        persist_bacnet_reads_to_historian(&all_reads);
        BACNET_POLL_SAMPLES.fetch_add(samples, Ordering::Relaxed);
        if let Ok(mut g) = BACNET_LAST_POLL.lock() {
            *g = Some(now_rfc3339());
        }
    }
    json!({
        "ok": true,
        "samples": samples,
        "points_updated": updated,
        "at": now_rfc3339(),
        "method": "ReadPropertyMultiple"
    })
}

fn apply_poll_reads(registry: &mut Value, device_instance: u32, reads: &[Value]) -> u64 {
    let mut count = 0_u64;
    let by_id: BTreeMap<String, Value> = reads
        .iter()
        .filter_map(|r| {
            r.get("id")
                .and_then(|v| v.as_str())
                .map(|id| (id.to_string(), r.clone()))
        })
        .collect();
    if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devs) = driver.get_mut("devices").and_then(|v| v.as_array_mut()) {
                for device in devs {
                    if device
                        .get("device_instance")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0) as u32
                        != device_instance
                    {
                        continue;
                    }
                    if let Some(points) = device.get_mut("points").and_then(|v| v.as_array_mut()) {
                        for point in points {
                            let pid = point.get("id").and_then(|v| v.as_str()).unwrap_or("");
                            if let Some(read) = by_id.get(pid) {
                                if let Some(pv) = read.get("present_value") {
                                    point["present_value"] = pv.clone();
                                    point["value"] = pv.clone();
                                }
                                if let Some(at) = read.get("last_read_at") {
                                    point["last_read_at"] = at.clone();
                                }
                                count += 1;
                            }
                        }
                    }
                }
            }
        }
    }
    if count > 0 {
        write_registry(registry);
    }
    count
}

pub fn scan_once_value() -> Value {
    if let Some(err) = live_gate::bacnet_live_required("override_scan") {
        return err;
    }
    let operator_priority = operator_override_priority();
    ensure_field_devices_from_whois();
    let registry = read_registry();
    let override_reg = read_override_registry();
    let (device_instance, next_rotation, next_device) = pick_scan_device(&registry, &override_reg);
    let merge = merge_live_discovery_into_registry(device_instance);
    let device_count = field_device_instances(&read_registry()).len().max(1) as u64;

    let mut scan_health = "ok".to_string();
    let mut scan_error: Option<String> = None;

    let scan_points: Vec<Value> = match bacnet_live::block_on(
        bacnet_live::discover_device_points_with_fallback(device_instance),
    ) {
        Ok(discovered) => discovered
            .into_iter()
            .filter(is_commandable_point)
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
            scan_health = "error".to_string();
            scan_error = Some(err);
            Vec::new()
        }
    };

    let pa_by_point = read_priority_arrays_rpm_for_points(device_instance, &scan_points);

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

    // Python-era parity: CI and legacy tooling expect these paths even when a scan
    // produces only operator (p8) or only supervisory overrides.
    ensure_csv_header(&export_path);
    ensure_legacy_csv_header(&legacy_all);
    ensure_legacy_csv_header(&legacy_p8);
    ensure_legacy_csv_header(&legacy_other);
    ensure_csv_header(&split_p8);
    ensure_csv_header(&split_other);

    for point in &scan_points {
        let point_id = point
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let priority_values = pa_by_point
            .get(&point_id)
            .cloned()
            .unwrap_or_else(|| read_priority_array_for_point(point));
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
        "method": "ReadPropertyMultiple(priority-array) for commandable BACnet points",
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

pub fn whois_json(body: &Value) -> String {
    if let Some(err) = live_gate::bacnet_live_required("whois") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
    let low = match body.get("low_limit").or_else(|| body.get("range_low")) {
        Some(v) => match v.as_u64() {
            Some(n) => match u32::try_from(n) {
                Ok(v) => Some(v),
                Err(_) => {
                    return serde_json::to_string(&json!({
                        "ok": false,
                        "error": "low_limit out of range for u32"
                    }))
                    .unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
                }
            },
            None => None,
        },
        None => None,
    };
    let high = match body.get("high_limit").or_else(|| body.get("range_high")) {
        Some(v) => match v.as_u64() {
            Some(n) => match u32::try_from(n) {
                Ok(v) => Some(v),
                Err(_) => {
                    return serde_json::to_string(&json!({
                        "ok": false,
                        "error": "high_limit out of range for u32"
                    }))
                    .unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
                }
            },
            None => None,
        },
        None => None,
    };
    match bacnet_live::block_on(bacnet_live::whois_devices_with_range(low, high)) {
        Ok(devices) => {
            persist_whois_discoveries(&devices);
            // Shells only — do not run live object-list here (can hang OT). Point
            // discovery is POST /api/bacnet/driver/sync-discovery or poll paths.
            merge_missing_field_devices_from_cache();
            serde_json::to_string(&devices).unwrap_or_else(|_| "[]".to_string())
        }
        Err(err) => serde_json::to_string(&json!({"ok": false, "error": err}))
            .unwrap_or_else(|_| r#"{"ok":false}"#.to_string()),
    }
}

pub fn points_json() -> String {
    if let Some(err) = live_gate::bacnet_live_required("points") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
    serde_json::to_string(&collect_bacnet_points(&read_registry()))
        .unwrap_or_else(|_| "[]".to_string())
}

pub fn point_discovery_value(body: &Value) -> Value {
    if let Some(err) = live_gate::bacnet_live_required("discovery") {
        return err;
    }
    let device_instance = body
        .get("device_instance")
        .and_then(|v| v.as_u64())
        .unwrap_or_else(|| profile_device_instance() as u64) as u32;

    match bacnet_live::block_on(bacnet_live::discover_device_points_with_fallback(
        device_instance,
    )) {
        Ok(points) => {
            let objects = discovery_objects_from_points(&points);
            json!({
                "ok": true,
                "status": "ok",
                "device_instance": device_instance,
                "points": points,
                "objects": objects,
                "result": {"objects": objects},
                "source": "rusty-bacnet"
            })
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn sync_discovery_value(body: &Value) -> Value {
    if let Some(err) = live_gate::bacnet_live_required("sync_discovery") {
        return err;
    }
    let device_instance = body
        .get("device_instance")
        .and_then(|v| v.as_u64())
        .map(|v| v as u32)
        .filter(|v| *v > 0)
        .unwrap_or_else(bench_device_instance);

    if let Some(objects) = body.get("objects").and_then(|v| v.as_array()) {
        if !objects.is_empty() {
            return merge_ui_objects_into_registry(device_instance, body, objects);
        }
    }
    merge_live_discovery_into_registry(device_instance)
}

pub fn patch_bacnet_point_value(body: &Value) -> Value {
    let point_id = body.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
    if point_id.is_empty() {
        return json!({"ok": false, "error": "point_id required"});
    }
    let mut registry = read_registry();
    let mut updated = false;
    if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devices) = driver.get_mut("devices").and_then(|v| v.as_array_mut()) {
                for device in devices.iter_mut() {
                    if let Some(points) = device.get_mut("points").and_then(|v| v.as_array_mut()) {
                        for pt in points.iter_mut() {
                            if pt.get("id").and_then(|v| v.as_str()) != Some(point_id) {
                                continue;
                            }
                            if let Some(v) = body.get("polling_enabled").and_then(|v| v.as_bool()) {
                                pt["polling_enabled"] = json!(v);
                                updated = true;
                            }
                            if let Some(v) = body.get("poll_interval_s").and_then(|v| v.as_u64()) {
                                pt["poll_interval_s"] = json!(v);
                                updated = true;
                            }
                        }
                    }
                }
            }
        }
    }
    if !updated {
        return json!({"ok": false, "error": "point not found in registry"});
    }
    write_registry(&registry);
    json!({"ok": true, "point_id": point_id, "updated": true})
}

pub fn read_present_value_json(body: &Value) -> String {
    if let Some(err) = live_gate::bacnet_live_required("read") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
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
                return serde_json::to_string(&value).unwrap_or_else(|_| "{}".to_string());
            }
            Err(err) => {
                return serde_json::to_string(&json!({"ok": false, "error": err}))
                    .unwrap_or_else(|_| r#"{"ok":false}"#.to_string())
            }
        }
    }
    serde_json::to_string(&json!({
        "ok": false,
        "error": "point_id or device_instance/object_id required"
    }))
    .unwrap_or_else(|_| r#"{"ok":false}"#.to_string())
}

pub fn driver_tree_json() -> String {
    ensure_field_devices_from_whois();
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
        "samples": BACNET_POLL_SAMPLES.load(Ordering::Relaxed),
        "enabled_points": enabled,
        "at": BACNET_LAST_POLL
            .lock()
            .ok()
            .and_then(|g| g.clone())
            .unwrap_or_else(now_rfc3339)
    })
}

fn persist_bacnet_reads_to_historian(reads: &[Value]) {
    use crate::historian::feather_store;
    use crate::historian::store;
    use crate::model::scope;
    use std::collections::BTreeMap;

    let mut wide_cols: BTreeMap<String, f64> = BTreeMap::new();
    let mut oa_t = None::<f64>;
    for read in reads {
        let val = read.get("present_value").and_then(|v| v.as_f64());
        if val.is_none() {
            continue;
        }
        let val = val.unwrap();
        oa_t = Some(val).or(oa_t);
        let col = read
            .get("name")
            .and_then(|v| v.as_str())
            .map(feather_store::column_slug)
            .or_else(|| {
                read.get("id")
                    .and_then(|v| v.as_str())
                    .map(feather_store::column_slug)
            })
            .unwrap_or_else(|| "present-value".into());
        wide_cols.insert(col, val);
    }
    let Some(oa_t) = oa_t else {
        return;
    };
    let profile = active_profile();
    let equipment_id = scope::resolve_equipment_id(Some(profile.equipment_id.as_str()))
        .unwrap_or_else(|| "equip:local-default".to_string());
    if equipment_id.is_empty() {
        return;
    }
    let ts = Utc::now().to_rfc3339();
    if !wide_cols.is_empty() {
        let site_id = scope::resolve_site_id(None).unwrap_or_else(|| "site:local".to_string());
        let _ = feather_store::write_wide_shard("bacnet", &site_id, &ts, &wide_cols);
    }
    let row = store::make_pivot_row(store::PivotSample {
        timestamp: &ts,
        equipment_id: &equipment_id,
        oa_t,
        oa_h: 0.0,
        duct_t: 0.0,
        zn_t: 0.0,
        source: "source:bacnet:poll",
        source_driver: "bacnet",
        is_simulated: false,
    });
    let _ = store::append_pivot_row(&row);
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
    crate::faults::summary_json()
        .get("active_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
}

pub fn priority_array_json(body: &Value) -> String {
    if let Some(err) = live_gate::bacnet_live_required("priority_array") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
    if let Some(point_id) = body.get("point_id").and_then(|v| v.as_str()) {
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
    serde_json::to_string(&json!({"ok": false, "error": "point not found or invalid point_id"}))
        .unwrap_or_default()
}

pub fn override_storage_meta() -> Value {
    let export_path = export_csv_path();
    json!({
        "ok": true,
        "retention_years": override_retention_years(),
        "scan_interval_s": override_scan_interval_s(),
        "export_path": export_path.display().to_string(),
        "export_row_count": count_csv_rows(&export_path),
        "priority8_path": csv_path("bacnet_priority8_overrides.csv").display().to_string(),
        "non_priority8_path": csv_path("bacnet_non_priority8_overrides.csv").display().to_string(),
        "last_scan": overrides_last_scan().get("last_scan_at").cloned().unwrap_or(json!(null))
    })
}

pub fn override_fault_alerts() -> Vec<Value> {
    let op_pri = operator_override_priority();
    let scan = read_override_registry();
    let ts = scan
        .get("last_scan_at")
        .or_else(|| scan.get("last_scan"))
        .cloned()
        .unwrap_or(json!(null));
    let mut out = Vec::new();
    let Some(events) = scan.get("overrides").and_then(|v| v.as_array()) else {
        return out;
    };
    for ev in events {
        let priority = ev.get("priority").and_then(|v| v.as_u64()).unwrap_or(0) as u8;
        if priority != op_pri {
            continue;
        }
        let point_name = ev
            .get("point")
            .or_else(|| ev.get("point_name"))
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let device_name = ev
            .get("device_name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let pid = ev
            .get("point_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let value = ev.get("value").cloned().unwrap_or(json!(null));
        out.push(json!({
            "id": format!("bacnet-override-{pid}-p{priority}"),
            "severity": "warning",
            "title": format!("OVERRIDE {device_name} — {point_name}"),
            "detail": format!("Operator priority {priority} write active (value {value})"),
            "equipment_id": device_name,
            "equipment_name": device_name,
            "source": "bacnet_override",
            "code": "BACNET_P8_OVERRIDE",
            "rule_id": "bacnet_operator_override",
            "rule_name": format!("BACnet operator override (P{priority})"),
            "first_seen_at": ts.clone(),
            "last_seen_at": ts.clone(),
            "analytics": {
                "priority": priority,
                "point_id": pid,
                "value": value
            }
        }));
    }
    out
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
    r#"{"ok":true,"dry_run":true,"note":"Set approved=true on /api/bacnet/write to execute WriteProperty on field devices"}"#
}

pub fn write_property_value(body: &Value) -> Value {
    let point_id = body.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
    let priority = body
        .get("priority")
        .and_then(|v| v.as_u64())
        .map(|p| p as u8);
    let value = body
        .get("value")
        .cloned()
        .unwrap_or(serde_json::json!(null));

    let Some((device_instance, object_type, instance)) =
        bacnet_live::point_object_from_id(point_id)
    else {
        return json!({"ok": false, "error": "point_id required (bacnet:device:type:instance)"});
    };

    if !bacnet_live::is_live_mode() {
        return json!({"ok": false, "error": "BACnet live mode required for field writes"});
    }

    let pv = json_value_to_property(&value, object_type);
    match bacnet_live::block_on(bacnet_live::write_present_value(
        device_instance,
        object_type,
        instance,
        &pv,
        priority,
    )) {
        Ok(v) => v,
        Err(e) => json!({"ok": false, "error": e}),
    }
}

fn json_value_to_property(value: &Value, object_type: ObjectType) -> PropertyValue {
    if value.is_null() {
        return PropertyValue::Null;
    }
    if let Some(n) = value.as_f64() {
        return PropertyValue::Real(n as f32);
    }
    if let Some(b) = value.as_bool() {
        return PropertyValue::Boolean(b);
    }
    if let Some(n) = value.as_u64() {
        if matches!(
            object_type,
            ObjectType::BINARY_VALUE | ObjectType::BINARY_OUTPUT
        ) {
            return PropertyValue::Enumerated(n as u32);
        }
        return PropertyValue::Unsigned(n);
    }
    PropertyValue::Real(0.0)
}

pub fn commission_status_json() -> String {
    let cfg = bacnet_config_value();
    let low = env::var("OPENFDD_BACNET_DISCOVER_LOW").unwrap_or_else(|_| "1".into());
    let high = env::var("OPENFDD_BACNET_DISCOVER_HIGH").unwrap_or_else(|_| "4194303".into());
    let bind = env::var("OPENFDD_BACNET_BIND").unwrap_or_default();
    let mode = env::var("OPENFDD_BACNET_MODE").unwrap_or_else(|_| "live".to_string());
    let service_mode = env::var("SERVICE_MODE").unwrap_or_else(|_| "bridge".into());
    let commission_agent_ok = service_mode == "commission"
        || env::var("OPENFDD_BACNET_ENABLED")
            .map(|v| v != "0" && v.to_lowercase() != "false")
            .unwrap_or(true);
    let discovery_mutations_enabled = env::var("OFDD_DISABLE_BACNET_DISCOVERY_MUTATIONS")
        .map(|v| v != "1" && v.to_lowercase() != "true")
        .unwrap_or(true);
    json!({
        "ok": true,
        "service": "bacnet-commission",
        "status": "ready",
        "config": cfg,
        "bacnet_bind": bind,
        "bacnet_mode": mode,
        "discover_range": [low, high],
        "commission_agent_ok": commission_agent_ok,
        "discovery_mutations_enabled": discovery_mutations_enabled,
        "features": ["whois","object-list","read-property","priority-array-scan","csv-override-log","rusty-bacnet-live"]
    }).to_string()
}

pub fn poll_status_json() -> String {
    let metrics = poll_metrics();
    json!({
        "ok": true,
        "service": "bacnet-poll",
        "status": "ready",
        "config": bacnet_config_value(),
        "cadence_seconds": env::var("OPENFDD_BACNET_POLL_INTERVAL_SECONDS").unwrap_or_else(|_| "60".to_string()),
        "writes_scan_cadence_seconds": env::var("OPENFDD_BACNET_SCAN_INTERVAL_SECONDS").unwrap_or_else(|_| "3600".to_string()),
        "scan_interval_seconds": env::var("OPENFDD_BACNET_SCAN_INTERVAL_SECONDS").unwrap_or_else(|_| "3600".to_string()),
        "samples": metrics.get("samples").cloned().unwrap_or(json!(0)),
        "enabled_points": metrics.get("enabled_points").cloned().unwrap_or(json!(0)),
        "last_poll": metrics.get("at").cloned().unwrap_or(Value::Null)
    }).to_string()
}

pub fn job_status_json(job_id: &str) -> Value {
    if job_id.trim().is_empty() || job_id.contains("..") || job_id.contains('/') {
        return json!({"ok": false, "error": "invalid job id"});
    }
    json!({
        "ok": false,
        "error": "job not found",
        "job_id": job_id,
        "status": "unknown"
    })
}

pub fn clear_bacnet_registry_value() -> Value {
    let registry_before = read_registry();
    let mut equipment_removed = 0_usize;
    let mut driver_points = 0_usize;
    if let Some(drivers) = registry_before.get("drivers").and_then(|v| v.as_array()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devices) = driver.get("devices").and_then(|v| v.as_array()) {
                for dev in devices {
                    if dev.get("local_server").and_then(|v| v.as_bool()) == Some(true) {
                        continue;
                    }
                    equipment_removed += 1;
                    driver_points += dev
                        .get("points")
                        .and_then(|v| v.as_array())
                        .map(|a| a.len())
                        .unwrap_or(0);
                }
            }
        }
    }
    let mut registry = registry_before;
    if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            let keep: Vec<Value> = driver
                .get("devices")
                .and_then(|v| v.as_array())
                .into_iter()
                .flatten()
                .filter(|d| d.get("local_server").and_then(|v| v.as_bool()) == Some(true))
                .cloned()
                .collect();
            driver["devices"] = json!(keep);
        }
    }
    write_registry(&registry);
    let model_sync = crate::model::commissioning::remove_bacnet_bindings_from_model();
    if model_sync.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        return json!({
            "ok": false,
            "error": model_sync
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("model sync failed after registry clear"),
            "driver_points_removed": driver_points
        });
    }
    json!({
        "ok": true,
        "message": "BACnet driver registry cleared",
        "driver_points_removed": driver_points,
        "model": {
            "points_removed": model_sync
                .get("points_removed")
                .and_then(|v| v.as_u64())
                .unwrap_or(driver_points as u64),
            "equipment_removed": model_sync
                .get("equipment_removed")
                .and_then(|v| v.as_u64())
                .unwrap_or(equipment_removed as u64)
        }
    })
}

pub fn remap_bacnet_device_value(body: &Value) -> Value {
    let Some(old_inst) = body.get("device_instance").and_then(|v| v.as_u64()) else {
        return json!({"ok": false, "error": "device_instance required"});
    };
    let Some(new_inst) = body.get("new_device_instance").and_then(|v| v.as_u64()) else {
        return json!({"ok": false, "error": "new_device_instance required"});
    };
    let new_addr = body
        .get("new_device_address")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let old_inst = old_inst as u32;
    let new_inst = new_inst as u32;
    let mut registry = read_registry();
    let mut found = false;
    if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
        for driver in drivers {
            if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
                continue;
            }
            if let Some(devices) = driver.get_mut("devices").and_then(|v| v.as_array_mut()) {
                for device in devices.iter_mut() {
                    if device.get("device_instance").and_then(|v| v.as_u64())
                        != Some(old_inst as u64)
                    {
                        continue;
                    }
                    device["device_instance"] = json!(new_inst);
                    device["name"] = json!(format!("BACnet Device {new_inst}"));
                    if !new_addr.is_empty() {
                        device["address"] = json!(new_addr);
                    }
                    if let Some(points) = device.get_mut("points").and_then(|v| v.as_array_mut()) {
                        for pt in points.iter_mut() {
                            pt["device_instance"] = json!(new_inst);
                            if !new_addr.is_empty() {
                                pt["address"] = json!(new_addr);
                            }
                        }
                    }
                    found = true;
                }
            }
        }
    }
    if !found {
        return json!({
            "ok": false,
            "error": format!("device instance {old_inst} not found in BACnet registry")
        });
    }
    write_registry(&registry);
    json!({
        "ok": true,
        "device_instance": old_inst,
        "new_device_instance": new_inst,
        "new_device_address": if new_addr.is_empty() { Value::Null } else { json!(new_addr) }
    })
}

#[cfg(test)]
mod override_export_tests {
    use super::*;

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
        crate::test_support::with_temp_workspace(|tmp| {
            let sample = json!({
                "last_scan_at": "2026-06-23T00:00:00Z",
                "last_scanned_device": 42,
                "next_device_instance": 42,
                "device_count": 1,
                "operator_priority": 8,
                "export_row_count": 2,
                "scan_health": "ok",
                "summary": {"priority8": 1, "non_priority8": 1, "total": 2}
            });
            write_override_registry(&sample);
            let loaded = read_override_registry();
            assert_eq!(loaded["last_scanned_device"], 42);
            assert_eq!(loaded["export_row_count"], 2);
            assert!(override_registry_path().starts_with(tmp));
            assert!(override_registry_path().exists());
        });
    }

    #[test]
    fn export_csv_row_marks_operator_override() {
        let point = json!({
            "device_instance": 1001,
            "address": "192.168.1.10:47808",
            "device_name": "Field Device",
            "id": "bacnet:1001:analog-output:2001",
            "name": "Demo Actuator",
            "object_id": [1, 2001],
            "unit": "%",
            "value": 55.0,
            "commandable": true
        });
        let row = export_csv_row("2026-06-23T00:00:00Z", &point, 8, &json!(55.0), 8);
        assert_eq!(row[10], "true");
        assert_eq!(row[11], "operator");
    }

    #[test]
    fn prune_csv_drops_rows_older_than_retention() {
        crate::test_support::with_temp_workspace(|_| {
            let path = export_csv_path();
            if let Some(parent) = path.parent() {
                let _ = fs::create_dir_all(parent);
            }
            let old = (Utc::now() - ChronoDuration::days(400)).to_rfc3339();
            let recent = Utc::now().to_rfc3339();
            let body = format!(
                "{OVERRIDE_EXPORT_CSV_HEADER}\n\"{old}\",\"1\",\"a\",\"d\",\"oid\",\"n\",\"ao\",\"1\",\"8\",\"55\",\"true\",\"operator\",\"%\",\"test\"\n\"{recent}\",\"1\",\"a\",\"d\",\"oid\",\"n\",\"ao\",\"1\",\"8\",\"55\",\"true\",\"operator\",\"%\",\"test\"\n"
            );
            let _ = fs::write(&path, body);
            prune_csv_older_than_years(&path, 1);
            let kept = fs::read_to_string(&path).unwrap_or_default();
            assert!(kept.contains(&recent));
            assert!(!kept.contains(&old));
        });
    }

    #[test]
    fn remap_device_updates_instance_and_address() {
        crate::test_support::with_temp_workspace(|_| {
            let mut registry = default_registry();
            if let Some(drivers) = registry.get_mut("drivers").and_then(|v| v.as_array_mut()) {
                for driver in drivers {
                    if driver.get("id").and_then(|v| v.as_str()) == Some("bacnet-ip") {
                        driver["devices"] = json!([{
                            "device_instance": 100,
                            "name": "BACnet Device 100",
                            "address": "192.168.1.10",
                            "points": [{"device_instance": 100, "object_type": "analog-input", "object_instance": 1}]
                        }]);
                    }
                }
            }
            write_registry(&registry);
            let out = remap_bacnet_device_value(&json!({
                "device_instance": 100,
                "new_device_instance": 5007,
                "new_device_address": "198.51.100.50"
            }));
            assert_eq!(out["ok"], true);
            let updated = read_registry();
            let device = &updated["drivers"][0]["devices"][0];
            let inst = device["device_instance"].as_u64().unwrap();
            assert_eq!(inst, 5007);
            assert_eq!(device["address"].as_str(), Some("198.51.100.50"));
            let pt = &device["points"][0];
            assert_eq!(pt["device_instance"].as_u64(), Some(5007));
            assert_eq!(pt["address"].as_str(), Some("198.51.100.50"));
        });
    }

    #[test]
    fn whois_shell_adds_field_device_when_live_discovery_unavailable() {
        crate::test_support::with_temp_workspace(|root| {
            let pin_ws = || std::env::set_var("OPENFDD_WORKSPACE", root);
            let prev_inst = std::env::var("OPENFDD_BACNET_DEVICE_INSTANCE").ok();
            std::env::set_var("OPENFDD_BACNET_DEVICE_INSTANCE", "599999");
            pin_ws();
            write_registry(&default_registry());
            // Generic instance + TEST-NET address — no site-specific OT hardcoding.
            let inst = 987_654_u32;
            let addr = "198.51.100.50:47808";
            let reg_path = root.join("data").join("drivers").join("bacnet").join("driver_tree.json");
            let cache = root
                .join("data")
                .join("drivers")
                .join("bacnet")
                .join("whois_discovered.json");
            let _ = fs::create_dir_all(cache.parent().unwrap());
            let _ = fs::write(
                &cache,
                serde_json::to_string_pretty(&json!({
                    "instances": [inst],
                    "devices": [{
                        "object_identifier": {"type": "device", "instance": inst},
                        "address": addr
                    }]
                }))
                .unwrap(),
            );
            pin_ws();
            assert!(ensure_field_device_shell(inst, Some(addr.to_string())));
            pin_ws();
            let registry: Value = serde_json::from_str(
                &fs::read_to_string(&reg_path).expect("registry file after whois shell"),
            )
            .expect("registry json");
            let devices = bacnet_devices_array(&registry);
            let field = devices
                .iter()
                .find(|d| d.get("device_instance").and_then(|v| v.as_u64()) == Some(inst as u64));
            assert!(field.is_some(), "Who-Is instance must appear in tree");
            assert_eq!(field.unwrap()["address"].as_str(), Some(addr));
            assert_eq!(field.unwrap()["source"].as_str(), Some("whois-shell"));
            // Second call is a no-op (already present).
            pin_ws();
            assert!(!ensure_field_device_shell(inst, None));
            // Cache-only merge must not hang / invent devices beyond Who-Is.
            pin_ws();
            merge_missing_field_devices_from_cache();
            pin_ws();
            let again: Value = serde_json::from_str(
                &fs::read_to_string(&reg_path).expect("registry after cache merge"),
            )
            .expect("registry json");
            assert!(
                bacnet_devices_array(&again)
                    .iter()
                    .any(|d| d.get("device_instance").and_then(|v| v.as_u64()) == Some(inst as u64)),
                "Who-Is shell must survive cache merge"
            );
            if let Some(p) = prev_inst {
                std::env::set_var("OPENFDD_BACNET_DEVICE_INSTANCE", p);
            } else {
                std::env::remove_var("OPENFDD_BACNET_DEVICE_INSTANCE");
            }
        });
    }

    fn bacnet_devices_array(registry: &Value) -> &[Value] {
        registry
            .get("drivers")
            .and_then(|v| v.as_array())
            .and_then(|drivers| {
                drivers
                    .iter()
                    .find(|d| d.get("id").and_then(|v| v.as_str()) == Some("bacnet-ip"))
            })
            .and_then(|d| d.get("devices"))
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
    }
}
