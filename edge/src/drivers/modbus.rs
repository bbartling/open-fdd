//! Modbus driver facade.
//!
//! Production direction:
//! - use Justin's `rusty-modbus` for Modbus/TCP, RTU, RTU-over-TCP, TLS,
//!   scan/read workflows.
//! - normalize register reads into the same historian/Arrow path as BACnet.

pub const POINTS_JSON: &str = r#"[
  {"id":"modbus:tcp:1:40001","name":"CHW Plant Supply Temp","register":40001,"function":"holding_register","value":44.8,"unit":"°F"},
  {"id":"modbus:tcp:1:40002","name":"Pump Speed Command","register":40002,"function":"holding_register","value":62.0,"unit":"%"}
]"#;

pub fn points_json() -> &'static str {
    POINTS_JSON
}

pub fn scan_json() -> String {
    format!(r#"{{"ok":true,"devices":[{{"unit_id":1,"address":"192.168.1.50:502"}}],"points":{}}}"#, POINTS_JSON)
}

pub fn read_json() -> &'static str {
    r#"{"point":"CHW Plant Supply Temp","value":44.8,"unit":"°F","source":"modbus-prototype"}"#
}
