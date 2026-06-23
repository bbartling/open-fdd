//! Project Haystack gateway facade (fixture + driver tree integration).

pub const MODEL_JSON: &str = r#"{
  "meta":{"ver":"3.0","mode":"fixture"},
  "cols":[{"name":"id"},{"name":"dis"},{"name":"site"},{"name":"equip"},{"name":"point"},{"name":"sensor"},{"name":"kind"},{"name":"unit"},{"name":"curVal"},{"name":"bacnetRef"}],
  "rows":[
    {"id":"site:demo","dis":"Demo Site","site":"M"},
    {"id":"equip:5007-bench","dis":"Device 5007 AHU Bench","equip":"M","siteRef":"site:demo","ahu":"M"},
    {"id":"point:oa-t","dis":"Outside Air Temp","point":"M","sensor":"M","kind":"Number","unit":"°F","curVal":62.0,"equipRef":"equip:5007-bench","bacnetRef":"bacnet:5007:analog-input:1173","fddInput":"oa_t"},
    {"id":"point:oa-h","dis":"Outside Air Humidity","point":"M","sensor":"M","kind":"Number","unit":"%RH","curVal":45.0,"equipRef":"equip:5007-bench","bacnetRef":"bacnet:5007:analog-input:1168","fddInput":"oa_h"},
    {"id":"point:duct-t","dis":"Discharge Air Temp","point":"M","sensor":"M","kind":"Number","unit":"°F","curVal":55.0,"equipRef":"equip:5007-bench","bacnetRef":"bacnet:5007:analog-input:1192","fddInput":"duct_t"},
    {"id":"point:zn-t","dis":"Zone Temp","point":"M","sensor":"M","kind":"Number","unit":"°F","curVal":72.0,"equipRef":"equip:5007-bench","bacnetRef":"bacnet:5007:analog-input:10014","fddInput":"zn_t"},
    {"id":"point:chwst","dis":"CHW Plant Supply Temp","point":"M","sensor":"M","kind":"Number","unit":"°F","curVal":44.8,"modbusRef":"modbus:tcp:1:40001"}
  ]
}"#;

pub fn about_json() -> &'static str {
    r#"{"serverName":"open-fdd-rust-haystack-gateway","haystackVersion":"3.0","mode":"fixture-simulation"}"#
}

pub fn ops_json() -> &'static str {
    r#"{"ops":["about","ops","read","nav"]}"#
}

pub fn model_json() -> &'static str {
    MODEL_JSON
}

pub fn import_json() -> &'static str {
    r#"{"ok":true,"preserve_ids":true,"imported":7,"mode":"fixture"}"#
}

pub fn status_json() -> &'static str {
    r#"{"ok":true,"driver":"haystack","status":"fixture","mode":"simulated-haystack-server","supported_ops":["about","ops","read","nav"],"equip":["equip:5007-bench"],"points":4}"#
}
