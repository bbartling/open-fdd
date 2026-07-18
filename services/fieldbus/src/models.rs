//! Request/response DTOs (mirrors `app/models.py`).

use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;
use validator::{Validate, ValidationError};

pub type DecodeLiteral = String;
pub type FunctionLiteral = String;
pub type ValueTypeLiteral = String;

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct BacnetReadRequest {
    #[validate(range(min = 0))]
    pub device_instance: u32,
    pub object_type: String,
    #[validate(range(min = 0))]
    pub object_instance: u32,
    #[serde(default = "default_present_value")]
    pub property_id: String,
}

fn default_present_value() -> String {
    "present-value".into()
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct BacnetRpmPropertySpec {
    pub property_id: String,
    pub array_index: Option<u32>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct BacnetRpmObjectSpec {
    pub object_type: String,
    #[validate(range(min = 0))]
    pub object_instance: u32,
    #[validate(length(min = 1))]
    pub properties: Vec<BacnetRpmPropertySpec>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct BacnetRpmRequest {
    pub device_instance: u32,
    #[validate(length(min = 1, max = 32))]
    pub objects: Vec<BacnetRpmObjectSpec>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct BacnetWhoisRequest {
    #[serde(default = "default_whois_low")]
    pub low: Option<u32>,
    #[serde(default = "default_whois_high")]
    pub high: Option<u32>,
}

fn default_whois_low() -> Option<u32> {
    Some(0)
}

fn default_whois_high() -> Option<u32> {
    Some(4_194_303)
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
#[validate(schema(function = "validate_bacnet_write"))]
pub struct BacnetWriteRequest {
    #[validate(range(min = 0))]
    pub device_instance: u32,
    pub object_type: String,
    #[validate(range(min = 0))]
    pub object_instance: u32,
    #[serde(default = "default_present_value")]
    pub property_id: String,
    pub value: Option<Value>,
    #[validate(range(min = 1, max = 16))]
    pub priority: Option<u8>,
    pub value_type: Option<ValueTypeLiteral>,
    #[serde(default = "default_true")]
    pub approved: bool,
}

fn default_true() -> bool {
    true
}

fn validate_bacnet_write(req: &BacnetWriteRequest) -> Result<(), ValidationError> {
    let is_release = match &req.value {
        None => true,
        Some(Value::Null) => true,
        Some(Value::String(s)) => s.trim().eq_ignore_ascii_case("null"),
        _ => false,
    };
    if is_release && req.priority.is_none() {
        return Err(ValidationError::new(
            "Releasing (null) requires a priority (1-16)",
        ));
    }
    Ok(())
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct BacnetObjectRef {
    #[validate(range(min = 0))]
    pub device_instance: u32,
    pub object_type: String,
    #[validate(range(min = 0))]
    pub object_instance: u32,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct DeviceInstanceRequest {
    #[validate(range(min = 0))]
    pub device_instance: u32,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct ServerUpdatePointsRequest {
    pub updates: std::collections::HashMap<String, Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
pub struct ModbusRegisterOp {
    #[serde(default)]
    pub address: u16,
    #[serde(default = "default_count")]
    pub count: u16,
    #[serde(default = "default_holding")]
    pub function: FunctionLiteral,
    pub decode: Option<DecodeLiteral>,
    pub scale: Option<f64>,
    pub offset: Option<f64>,
    pub label: Option<String>,
}

fn default_count() -> u16 {
    1
}

fn default_holding() -> String {
    "holding".into()
}

fn default_modbus_port() -> u16 {
    502
}

fn default_unit_id() -> u8 {
    1
}

fn default_modbus_timeout() -> f64 {
    5.0
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct ModbusReadRequest {
    pub host: String,
    #[serde(default = "default_modbus_port")]
    #[validate(range(min = 1, max = 65535))]
    pub port: u16,
    #[serde(default = "default_unit_id")]
    #[validate(range(min = 0, max = 255))]
    pub unit_id: u8,
    #[serde(default = "default_modbus_timeout")]
    #[validate(range(min = 0.5, max = 60.0))]
    pub timeout: f64,
    #[validate(length(min = 1, max = 32))]
    pub registers: Vec<ModbusRegisterOp>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct HaystackReadRequest {
    #[serde(default = "default_site_filter")]
    pub filter: String,
}

fn default_site_filter() -> String {
    "site".into()
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
pub struct HaystackNavRequest {
    pub nav_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct HaystackHisReadRequest {
    #[validate(length(min = 1, max = 64))]
    pub ids: Vec<String>,
    pub range_start: Option<String>,
    pub range_end: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct RestReadRequest {
    /// Configured device name from `rest_devices.toml` (no free-form URLs).
    #[validate(length(min = 1, max = 128))]
    pub device: String,
    /// Configured point name on that device.
    #[validate(length(min = 1, max = 256))]
    pub point: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct RestGetRequest {
    /// Configured device name from `rest_devices.toml` (no free-form URLs).
    #[validate(length(min = 1, max = 128))]
    pub device: String,
    /// Relative path joined below the device base_url (absolute URLs rejected).
    #[validate(length(min = 1, max = 2048))]
    pub path: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema, Validate)]
pub struct RestWriteRequest {
    /// Configured device name from `rest_devices.toml`.
    #[validate(length(min = 1, max = 128))]
    pub device: String,
    /// Allowlisted write binding name on that device.
    #[validate(length(min = 1, max = 256))]
    pub name: String,
    /// Numeric value substituted into the binding's body_template.
    pub value: f64,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct WeatherResponse {
    pub temp_f: f64,
    pub humidity: f64,
    pub wind_mph: f64,
    pub dewpoint_f: f64,
    pub location: String,
    pub from_api: bool,
    #[serde(default)]
    pub reason: String,
    pub updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct OkResponse {
    pub ok: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_release_requires_priority() {
        let req = BacnetWriteRequest {
            device_instance: 1,
            object_type: "analog-output".into(),
            object_instance: 1,
            property_id: "present-value".into(),
            value: None,
            priority: None,
            value_type: None,
            approved: true,
        };
        assert!(validate_bacnet_write(&req).is_err());
    }

    #[test]
    fn write_release_ok_with_priority() {
        let req = BacnetWriteRequest {
            device_instance: 5007,
            object_type: "analog-output".into(),
            object_instance: 2466,
            property_id: "present-value".into(),
            value: None,
            priority: Some(8),
            value_type: None,
            approved: true,
        };
        assert!(validate_bacnet_write(&req).is_ok());
        assert!(req.approved);
    }

    #[test]
    fn write_approved_gate() {
        let req = BacnetWriteRequest {
            device_instance: 5007,
            object_type: "analog-output".into(),
            object_instance: 2466,
            property_id: "present-value".into(),
            value: Some(serde_json::json!(55.0)),
            priority: None,
            value_type: None,
            approved: true,
        };
        assert!(req.approved);
        let unapproved = BacnetWriteRequest {
            approved: false,
            ..req
        };
        assert!(!unapproved.approved);
    }
}
