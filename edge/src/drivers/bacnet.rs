//! Central BACnet facade (registry JSON helpers only).
//! Live Who-Is / Read / Write / poll moved to `openfdd-fieldbus` over MQTTS.

use serde_json::{json, Value};

pub const OVERRIDE_EXPORT_CSV_HEADER: &str = "scanned_at,device_instance,device_address,device_label,object_identifier,object_name,object_type,present_value,priority_level,priority_value,operator_override,override_kind,units,source";

fn moved_json() -> Value {
    json!({
        "ok": false,
        "error": "BACnet wire I/O moved to openfdd-fieldbus",
        "hint": "Run openfdd-fieldbus and transport telemetry via MQTTS to openfdd-central"
    })
}

fn moved_str() -> String {
    moved_json().to_string()
}

pub fn override_scan_interval_s() -> u64 {
    3600
}
pub fn override_retention_years() -> u32 {
    3
}
pub fn operator_override_priority() -> u8 {
    8
}
pub fn override_kind(priority: u8, operator_priority: u8) -> &'static str {
    if priority == operator_priority {
        "operator"
    } else {
        "other"
    }
}
pub fn is_operator_override(priority: u8, operator_priority: u8) -> bool {
    priority == operator_priority
}

pub fn bacnet_config_value() -> Value {
    json!({
        "mode": "fieldbus",
        "wire": "mqtts",
        "local_udp": false
    })
}

#[derive(Debug, Clone)]
pub struct FieldDeviceRouting {
    pub device_instance: u32,
    pub address: String,
}

pub fn field_device_routing(_device_instance: u32) -> Option<FieldDeviceRouting> {
    None
}
pub fn registry_device_address(_device_instance: u32) -> Option<String> {
    None
}
pub fn field_device_instances_from_registry() -> Vec<u32> {
    vec![]
}
pub fn commission_owns_bacnet_poll() -> bool {
    false
}
pub fn cached_field_device_address(_device_instance: u32) -> Option<String> {
    None
}
pub fn merge_live_discovery_into_registry(_device_instance: u32) -> Value {
    moved_json()
}
pub fn overrides_summary_json() -> Value {
    json!({
        "ok": true,
        "overrides": [],
        "operator_priority": operator_override_priority(),
        "note": "edge overrides now live on fieldbus"
    })
}
pub fn start_hourly_override_scanner(_service_mode: String) {}
pub fn poll_interval_s() -> u64 {
    60
}
pub fn start_field_device_sync_loop(_service_mode: String) {}
pub fn start_bacnet_poll_loop(_service_mode: String) {}
pub fn poll_cycle_value() -> Value {
    moved_json()
}
pub fn scan_once_value() -> Value {
    json!({
        "ok": true,
        "summary": { "total": 0, "operator": 0, "other": 0 },
        "note": "override scan runs on openfdd-fieldbus; edge stub returns empty summary"
    })
}
pub fn whois_json(_body: &Value) -> String {
    moved_str()
}
pub fn points_json() -> String {
    json!({ "ok": true, "points": [], "hint": "use central /api/edges shadow" }).to_string()
}
pub fn point_discovery_value(_body: &Value) -> Value {
    moved_json()
}
pub fn sync_discovery_value(_body: &Value) -> Value {
    moved_json()
}
pub fn patch_bacnet_point_value(_body: &Value) -> Value {
    moved_json()
}
pub fn read_present_value_json(_body: &Value) -> String {
    moved_str()
}
pub fn driver_tree_json() -> String {
    json!({
        "ok": true,
        "drivers": [{
            "id": "bacnet-ip",
            "devices": [{
                "device_instance": 599999,
                "device_name": "OpenFDD",
                "local_server": true,
                "note": "hosted by openfdd-fieldbus"
            }]
        }],
        "hint": "migrate registry with scripts/migrate_driver_tree_to_fieldbus.py"
    })
    .to_string()
}
pub fn read_registry_value() -> Value {
    json!({ "ok": true, "registry": { "devices": [] } })
}
pub fn overrides_last_scan() -> Value {
    json!({ "ok": true, "rows": [] })
}
pub fn poll_metrics() -> Value {
    json!({ "ok": true, "cycles": 0, "moved_to": "fieldbus" })
}
pub fn count_discovered_devices(_registry: &Value) -> u64 {
    0
}
pub fn count_field_devices(_registry: &Value) -> u64 {
    0
}
pub fn active_fault_count() -> u64 {
    0
}
pub fn priority_array_json(_body: &Value) -> String {
    moved_str()
}
pub fn override_storage_meta() -> Value {
    json!({ "ok": true })
}
pub fn override_fault_alerts() -> Vec<Value> {
    vec![]
}
pub fn overrides_csv() -> String {
    format!("{OVERRIDE_EXPORT_CSV_HEADER}\n")
}
pub fn priority8_csv() -> String {
    format!("{OVERRIDE_EXPORT_CSV_HEADER}\n")
}
pub fn non_priority8_csv() -> String {
    format!("{OVERRIDE_EXPORT_CSV_HEADER}\n")
}
pub fn write_dry_run_json() -> &'static str {
    r#"{"ok":true,"dry_run":true,"hint":"use fieldbus /bacnet/write-dry-run"}"#
}
pub fn write_property_value(_body: &Value) -> Value {
    moved_json()
}
pub fn commission_status_json() -> String {
    let mode = std::env::var("OPENFDD_BACNET_MODE").unwrap_or_else(|_| "fieldbus".into());
    json!({
        "ok": true,
        "role": "retired",
        "fieldbus": "openfdd-fieldbus",
        "config": {
            "mode": mode,
            "wire": "mqtts",
            "note": "UDP BACnet is owned by openfdd-fieldbus"
        }
    })
    .to_string()
}
pub fn poll_status_json() -> String {
    json!({ "ok": true, "running": false, "moved_to": "fieldbus" }).to_string()
}
pub fn job_status_json(_job_id: &str) -> Value {
    json!({ "ok": false, "error": "jobs retired" })
}
pub fn clear_bacnet_registry_value() -> Value {
    json!({ "ok": true, "cleared": true })
}
pub fn remap_bacnet_device_value(_body: &Value) -> Value {
    moved_json()
}
