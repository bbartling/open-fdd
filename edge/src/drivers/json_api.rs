//! JSON API driver facade.
//!
//! Production direction:
//! - register HTTP JSON sources with URL, headers, polling cadence, timestamp
//!   mapping, point mapping, and units.
//! - poll them into normalized point samples for Arrow/DataFusion.
//! - first use case: outside-air temperature comparison from a weather API.

pub const SOURCES_JSON: &str = r#"[
  {"id":"openweather-oat","url":"https://api.openweathermap.org/data/2.5/weather","maps_to":"outside_air_temperature","status":"demo-only"},
  {"id":"plant-json-api","url":"http://edge-controller.local/api/points","maps_to":"plant telemetry","status":"demo-only"}
]"#;

pub fn sources_json() -> &'static str {
    SOURCES_JSON
}

pub fn register_json() -> &'static str {
    r#"{"ok":true,"status":"registered","source":"custom-json-api","runtime":"rust"}"#
}

pub fn poll_once_json() -> &'static str {
    r#"{"ok":true,"source_id":"openweather-oat","points":[{"id":"point:oat","value":62.4,"unit":"degF"}]}"#
}
