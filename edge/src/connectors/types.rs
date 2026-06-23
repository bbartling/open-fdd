//! Shared connector types and normalized historian row shape.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SourceType {
    Bacnet,
    Modbus,
    Haystack,
    JsonApi,
    PostgresReadonly,
    FileImport,
    Simulation,
}

impl SourceType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Bacnet => "bacnet",
            Self::Modbus => "modbus",
            Self::Haystack => "haystack",
            Self::JsonApi => "json_api",
            Self::PostgresReadonly => "postgres_readonly",
            Self::FileImport => "file_import",
            Self::Simulation => "simulation",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw {
            "bacnet" => Some(Self::Bacnet),
            "modbus" => Some(Self::Modbus),
            "haystack" => Some(Self::Haystack),
            "json_api" | "json-api" => Some(Self::JsonApi),
            "postgres_readonly" | "postgres-readonly" => Some(Self::PostgresReadonly),
            "file_import" | "file-import" => Some(Self::FileImport),
            "simulation" => Some(Self::Simulation),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceRecord {
    pub source_id: String,
    pub source_type: String,
    pub display_name: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default)]
    pub site_id: String,
    #[serde(default)]
    pub building_id: String,
    pub config_path: String,
    #[serde(default)]
    pub health: SourceHealth,
    #[serde(default)]
    pub last_poll_at: Option<String>,
    #[serde(default)]
    pub last_backfill_at: Option<String>,
    #[serde(default)]
    pub row_count: u64,
    #[serde(default)]
    pub mapped_points: u64,
    #[serde(default)]
    pub unmapped_points: u64,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SourceHealth {
    pub status: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonApiConfig {
    pub source_id: String,
    pub display_name: String,
    #[serde(default)]
    pub site_id: String,
    #[serde(default)]
    pub building_id: String,
    pub base_url: String,
    #[serde(default)]
    pub auth: JsonApiAuth,
    #[serde(default = "default_poll_s")]
    pub polling_interval_s: u64,
    #[serde(default = "default_timeout_s")]
    pub timeout_s: u64,
    #[serde(default)]
    pub retry: RetryPolicy,
    #[serde(default)]
    pub rate_limit_per_min: u64,
    pub endpoints: Vec<JsonApiEndpoint>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct JsonApiAuth {
    #[serde(default)]
    pub auth_type: String,
    #[serde(default)]
    pub secret_ref: Option<String>,
    #[serde(default)]
    pub username_secret_ref: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonApiEndpoint {
    pub endpoint_id: String,
    pub path: String,
    #[serde(default = "default_get")]
    pub method: String,
    #[serde(default)]
    pub shape: String,
    #[serde(default)]
    pub timestamp_path: String,
    #[serde(default)]
    pub points: Vec<JsonApiPointMapping>,
    #[serde(default)]
    pub supports_history: bool,
    #[serde(default)]
    pub history_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonApiPointMapping {
    pub point_id: String,
    pub point_name: String,
    #[serde(default)]
    pub value_path: String,
    #[serde(default)]
    pub units_path: Option<String>,
    #[serde(default)]
    pub units: Option<String>,
    #[serde(default)]
    pub quality_path: Option<String>,
    #[serde(default)]
    pub equipment_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RetryPolicy {
    #[serde(default = "default_retries")]
    pub max_retries: u32,
    #[serde(default = "default_backoff_ms")]
    pub backoff_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PostgresConfig {
    pub source_id: String,
    pub display_name: String,
    #[serde(default)]
    pub site_id: String,
    #[serde(default)]
    pub building_id: String,
    pub connection_secret_ref: String,
    #[serde(default = "default_timeout_s")]
    pub query_timeout_s: u64,
    #[serde(default = "default_row_limit")]
    pub row_limit: u64,
    pub catalog_sql_path: String,
    pub current_values_sql_path: String,
    pub history_sql_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NormalizedRow {
    pub timestamp_utc: String,
    pub timestamp_local: String,
    pub timezone: String,
    pub site_id: String,
    pub building_id: String,
    pub equipment_id: String,
    pub source_id: String,
    pub source_type: String,
    pub source_protocol: String,
    pub device_id: String,
    pub point_id: String,
    pub point_name: String,
    pub value: Option<f64>,
    pub value_text: String,
    pub units: String,
    pub quality: String,
    pub source_path: String,
    pub raw_ref: String,
    pub ingested_at: String,
    pub run_id: String,
}

impl NormalizedRow {
    pub fn dedupe_key(&self) -> String {
        format!(
            "{}|{}|{}|{}",
            self.timestamp_utc, self.source_id, self.point_id, self.run_id
        )
    }

    pub fn to_json(&self) -> Value {
        json!({
            "timestamp_utc": self.timestamp_utc,
            "timestamp_local": self.timestamp_local,
            "timezone": self.timezone,
            "site_id": self.site_id,
            "building_id": self.building_id,
            "equipment_id": self.equipment_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_protocol": self.source_protocol,
            "device_id": self.device_id,
            "point_id": self.point_id,
            "point_name": self.point_name,
            "value": self.value,
            "value_text": self.value_text,
            "units": self.units,
            "quality": self.quality,
            "source_path": self.source_path,
            "raw_ref": self.raw_ref,
            "ingested_at": self.ingested_at,
            "run_id": self.run_id,
            "dedupe_key": self.dedupe_key()
        })
    }
}

fn default_poll_s() -> u64 {
    300
}
fn default_timeout_s() -> u64 {
    30
}
fn default_get() -> String {
    "GET".into()
}
fn default_retries() -> u32 {
    2
}
fn default_backoff_ms() -> u64 {
    500
}
fn default_row_limit() -> u64 {
    5000
}

pub fn redact_config_for_api(value: &Value) -> Value {
    redact_value(value)
}

fn redact_value(v: &Value) -> Value {
    match v {
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, val) in map {
                let lk = k.to_ascii_lowercase();
                if lk.contains("secret")
                    || lk.contains("password")
                    || lk.contains("token")
                    || lk.contains("connection_string")
                    || lk.contains("dsn")
                {
                    out.insert(k.clone(), json!("***REDACTED***"));
                } else {
                    out.insert(k.clone(), redact_value(val));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(redact_value).collect()),
        _ => v.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_secret_refs_in_config() {
        let cfg = json!({
            "auth": {"secret_ref": "MY_TOKEN", "auth_type": "bearer"},
            "connection_secret_ref": "POSTGRES_DSN"
        });
        let red = redact_config_for_api(&cfg);
        assert_eq!(red["auth"]["secret_ref"], "***REDACTED***");
        assert_eq!(red["connection_secret_ref"], "***REDACTED***");
    }
}
