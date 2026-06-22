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
  {"object_identifier":{"type":"device","instance":1001},"vendor_id":5,"address":"192.168.1.100:47808","label":"AHU-1 Controller","protocol":"BACnet/IP"},
  {"object_identifier":{"type":"device","instance":2002},"vendor_id":359,"address":"192.168.1.101:47808","label":"VAV Floor 2 Router","protocol":"BACnet/IP"}
]"#;

const POINTS_JSON: &str = r#"[
  {"device_instance":1001,"mac":"c0a80164bac0","object_id":[0,1],"name":"AHU-1 SAT","kind":"sensor","unit":"°F","writable":false,"value":55.2,"haystack_id":"point:sat"},
  {"device_instance":1001,"mac":"c0a80164bac0","object_id":[2,4],"name":"AHU-1 SAT Setpoint","kind":"setpoint","unit":"°F","writable":true,"value":55.0,"haystack_id":"point:sat-sp"},
  {"device_instance":1001,"mac":"c0a80164bac0","object_id":[5,8],"name":"AHU-1 Fan Command","kind":"cmd","unit":"bool","writable":true,"value":1,"haystack_id":"point:fan-cmd"}
]"#;

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn overrides_dir() -> PathBuf {
    workspace_dir().join("overrides")
}

fn csv_path(name: &str) -> PathBuf {
    overrides_dir().join(name)
}

fn now_rfc3339() -> String {
    Utc::now().to_rfc3339()
}

fn bacnet_config_value() -> Value {
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
        json!({"id":"bacnet:5007:analog-input:1173","device_instance":5007,"object_id":[0,1173],"name":"Outside Air Temp","polling_enabled":true,"writable":false,"haystack_id":"point:oa-t","fdd_input":"oa-t"}),
        json!({"id":"bacnet:5007:analog-input:1168","device_instance":5007,"object_id":[0,1168],"name":"Outside Air Humidity","polling_enabled":true,"writable":false,"haystack_id":"point:oa-h","fdd_input":"oa-h"}),
        json!({"id":"bacnet:5007:analog-input:1192","device_instance":5007,"object_id":[0,1192],"name":"Discharge Air Temp","polling_enabled":true,"writable":false,"haystack_id":"point:duct-t","fdd_input":"duct-t"}),
        json!({"id":"bacnet:5007:analog-input:10014","device_instance":5007,"object_id":[0,10014],"name":"Zone Temp","polling_enabled":true,"writable":false,"haystack_id":"point:stat_zn-t","fdd_input":"stat_zn-t"}),
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
            bench5007_device(),
            {
              "device_instance":1001,
              "name":"AHU-1 Controller (simulated)",
              "address":"192.168.1.100:47808",
              "polling_enabled":true,
              "points":[
                {"id":"bacnet:1001:analog-input:1","device_instance":1001,"object_id":[0,1],"name":"AHU-1 SAT","polling_enabled":true,"writable":false,"haystack_id":"point:sat"},
                {"id":"bacnet:1001:analog-value:4","device_instance":1001,"object_id":[2,4],"name":"AHU-1 SAT Setpoint","polling_enabled":true,"writable":true,"haystack_id":"point:sat-sp"},
                {"id":"bacnet:1001:binary-value:8","device_instance":1001,"object_id":[5,8],"name":"AHU-1 Fan Command","polling_enabled":true,"writable":true,"haystack_id":"point:fan-cmd"}
              ]
            }
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
            {"id":"equip:ahu1","dis":"AHU-1","siteRef":"site:demo"}
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

fn read_registry() -> Value {
    let path = registry_path();
    match fs::read_to_string(&path) {
        Ok(text) => serde_json::from_str::<Value>(&text).unwrap_or_else(|_| default_registry()),
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

fn writable_points(registry: &Value) -> Vec<Value> {
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
                            if point
                                .get("writable")
                                .and_then(|v| v.as_bool())
                                .unwrap_or(false)
                            {
                                let mut p = point.clone();
                                if p.get("device_instance").is_none() {
                                    p["device_instance"] =
                                        device.get("device_instance").cloned().unwrap_or(json!(0));
                                }
                                if p.get("device_name").is_none() {
                                    p["device_name"] =
                                        device.get("name").cloned().unwrap_or(json!("unknown"));
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
    }
    points
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
    if name.contains("Setpoint") {
        vec![(8, json!(58.0))]
    } else if name.contains("Fan Command") {
        vec![(5, json!(1))]
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
    fs::read_to_string(path).unwrap_or_else(|_| {
        "timestamp,scan_id,device_instance,device_name,address,point_id,object_id,point_name,haystack_id,priority,priority_kind,value,source_method\n".to_string()
    })
}

pub fn start_hourly_override_scanner(service_mode: String) {
    if service_mode != "commission" {
        return;
    }
    thread::spawn(move || loop {
        let _ = scan_once_value();
        thread::sleep(Duration::from_secs(3600));
    });
}

pub fn scan_once_value() -> Value {
    let registry = read_registry();
    write_registry(&registry);

    let scan_id = format!("bacnet-scan-{}", Utc::now().timestamp());
    let ts = now_rfc3339();
    let mut events: Vec<Value> = Vec::new();
    let mut p8_count = 0;
    let mut non_p8_count = 0;

    let all_path = csv_path("bacnet_overrides.csv");
    let p8_path = csv_path("bacnet_priority8_overrides.csv");
    let other_path = csv_path("bacnet_non_priority8_overrides.csv");

    for point in writable_points(&registry) {
        let priority_values = read_priority_array_for_point(&point);
        for (priority, value) in priority_values {
            let kind = if priority == 8 {
                "operator"
            } else {
                "non_priority8"
            };
            if priority == 8 {
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

            let row = vec![
                ts.clone(),
                scan_id.clone(),
                event["device_instance"].to_string(),
                event["device_name"]
                    .as_str()
                    .unwrap_or("unknown")
                    .to_string(),
                event["address"].as_str().unwrap_or("unknown").to_string(),
                event["point_id"].as_str().unwrap_or("unknown").to_string(),
                event["object_id"].to_string(),
                event["point"].as_str().unwrap_or("unknown").to_string(),
                event["haystack_id"].as_str().unwrap_or("").to_string(),
                priority.to_string(),
                kind.to_string(),
                event["value"].to_string(),
                "ReadProperty(priority-array)".to_string(),
            ];
            append_csv(&all_path, &row);
            if priority == 8 {
                append_csv(&p8_path, &row);
            } else {
                append_csv(&other_path, &row);
            }
            events.push(event);
        }
    }

    let status = json!({
        "ok": true,
        "last_scan": ts,
        "scan_id": scan_id,
        "cadence": "hourly",
        "method": "ReadProperty(priority-array) for writable BACnet points",
        "csv": {
            "all": all_path.display().to_string(),
            "priority8": p8_path.display().to_string(),
            "non_priority8": other_path.display().to_string()
        },
        "summary": {
            "priority8": p8_count,
            "non_priority8": non_p8_count,
            "total": p8_count + non_p8_count
        },
        "overrides": events
    });

    let _ = fs::write(
        overrides_dir().join("last_scan.json"),
        serde_json::to_string_pretty(&status).unwrap_or_default(),
    );
    status
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
    let device_instance = env::var("OPENFDD_BACNET_DISCOVER_LOW")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(5007u32);

    let discovered_points = if bacnet_live::is_live_mode() {
        bacnet_live::block_on(bacnet_live::discover_device_points(device_instance)).ok()
    } else {
        None
    };

    let points = discovered_points.unwrap_or_else(bench5007_points);
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
        "devices": 1,
        "points": points.len(),
        "source": if bacnet_live::is_live_mode() { "rusty-bacnet" } else { "simulated" }
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

    r#"{"point":"AHU-1 SAT","value":55.2,"unit":"°F","source":"bacnet-simulated"}"#.to_string()
}

pub fn driver_tree_json() -> String {
    serde_json::to_string_pretty(&read_registry()).unwrap_or_else(|_| "{}".to_string())
}

pub fn overrides_json() -> String {
    let last = overrides_dir().join("last_scan.json");
    if let Ok(text) = fs::read_to_string(last) {
        text
    } else {
        serde_json::to_string_pretty(&scan_once_value()).unwrap_or_else(|_| "{}".to_string())
    }
}

pub fn overrides_csv() -> String {
    read_csv(&csv_path("bacnet_overrides.csv"))
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
