//! Arrow-shaped historian tables.
//!
//! The prototype serves JSON rows with the exact schema intended for Arrow:
//! ts, equip, sat, sat_sp, duct_static, duct_static_sp, oat, fan_cmd.
//! Production code should convert these into Apache Arrow arrays / RecordBatches.

pub const ARROW_ROWS_JSON: &str = r#"[
  {"ts":"2026-06-21T00:00:00Z","equip":"5007","sat":55.0,"sat_sp":55.0,"duct_static":1.20,"duct_static_sp":1.20,"oat":62.0,"fan_cmd":1.0},
  {"ts":"2026-06-21T00:05:00Z","equip":"5007","sat":66.5,"sat_sp":55.0,"duct_static":1.18,"duct_static_sp":1.20,"oat":63.0,"fan_cmd":1.0},
  {"ts":"2026-06-21T00:10:00Z","equip":"5007","sat":67.1,"sat_sp":55.0,"duct_static":1.17,"duct_static_sp":1.20,"oat":64.0,"fan_cmd":1.0},
  {"ts":"2026-06-21T00:15:00Z","equip":"5007","sat":67.3,"sat_sp":55.0,"duct_static":1.15,"duct_static_sp":1.20,"oat":65.0,"fan_cmd":1.0},
  {"ts":"2026-06-21T00:20:00Z","equip":"5007","sat":56.0,"sat_sp":55.0,"duct_static":1.80,"duct_static_sp":1.20,"oat":66.0,"fan_cmd":1.0}
]"#;

pub fn demo_rows_json() -> &'static str {
    ARROW_ROWS_JSON
}

pub fn query_json() -> &'static str {
    r#"{"ok":true,"engine":"Apache Arrow RecordBatch / DataFusion query path","rows":[{"ts":"2026-06-21T00:00:00Z","point_id":"bacnet:5007:analog-input:1173","value":62.0},{"ts":"2026-06-21T00:05:00Z","point_id":"bacnet:5007:analog-input:1173","value":63.0}]}"#
}
