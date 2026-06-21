//! Project Haystack gateway facade.
//!
//! This replaces the custom Niagara WebSocket direction:
//!
//! Niagara / BAS server -> Project Haystack read/nav/ops -> Rust gateway ->
//! Open-FDD model + Arrow tables + DataFusion SQL FDD.
//!
//! Production direction:
//! - use `rusty-haystack` client/server crates.
//! - support `about`, `ops`, `read`, `nav`, and authenticated remote servers.
//! - map Haystack refs to BACnet/Modbus/JSON point references.

pub const MODEL_JSON: &str = r#"{
  "meta":{"ver":"3.0"},
  "cols":[{"name":"id"},{"name":"dis"},{"name":"site"},{"name":"equip"},{"name":"point"},{"name":"bacnetRef"},{"name":"modbusRef"}],
  "rows":[
    {"id":"site:demo","dis":"Demo Site","site":"M"},
    {"id":"equip:ahu1","dis":"AHU-1","equip":"M","siteRef":"site:demo"},
    {"id":"point:sat","dis":"AHU-1 SAT","point":"M","sensor":"M","bacnetRef":"analog-input:1"},
    {"id":"point:chwst","dis":"CHW Plant Supply Temp","point":"M","sensor":"M","modbusRef":"40001"}
  ]
}"#;

pub fn about_json() -> &'static str {
    r#"{"serverName":"open-fdd-rust-haystack-gateway","haystackVersion":"3.0","mode":"Niagara integration via Project Haystack"}"#
}

pub fn ops_json() -> &'static str {
    r#"{"ops":["about","ops","read","nav"]}"#
}

pub fn model_json() -> &'static str {
    MODEL_JSON
}

pub fn import_json() -> &'static str {
    r#"{"ok":true,"preserve_ids":true,"imported":4}"#
}

pub fn status_json() -> &'static str {
    r#"{"ok":true,"driver":"haystack","status":"online","replaces":"Niagara tab","supported_ops":["about","ops","read","nav"],"model_only":true}"#
}
