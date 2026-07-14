//! BACnet live wire I/O removed from central.
//! Live BACnet is owned exclusively by `openfdd-fieldbus` over MQTTS.

#![allow(dead_code)]

use serde_json::Value;

pub fn is_live_mode() -> bool {
    false
}

pub fn whois(_low: u32, _high: u32) -> Result<Value, String> {
    Err(moved())
}

pub fn read_present_value(
    _device: u32,
    _object_type: &str,
    _instance: u32,
) -> Result<Value, String> {
    Err(moved())
}

fn moved() -> String {
    "BACnet wire I/O moved to openfdd-fieldbus (MQTTS)".into()
}
