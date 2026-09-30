//! Scoped, read-only connector proxy contract.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::capabilities::{ConnectorHelloResponse, CAPABILITIES_CONTRACT_V1};

pub const READ_PROXY_CONTRACT_V1: &str = "openfdd.connector.read.v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorScope {
    pub tenant_id: String,
    pub building_id: String,
    pub edge_id: String,
}

impl ConnectorScope {
    pub fn validate(&self) -> Result<(), String> {
        if self.tenant_id.trim().is_empty()
            || self.building_id.trim().is_empty()
            || self.edge_id.trim().is_empty()
        {
            return Err("tenant_id, building_id, and edge_id are required".into());
        }
        for (name, value) in [
            ("tenant_id", self.tenant_id.as_str()),
            ("building_id", self.building_id.as_str()),
            ("edge_id", self.edge_id.as_str()),
        ] {
            if value.contains('/') || value.contains('\\') || value.contains("..") {
                return Err(format!("{name} contains a path escape"));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReadTarget {
    ConnectorMetadata,
    BacnetPoint {
        device_instance: u32,
        object_type: String,
        object_instance: u32,
        property_id: String,
    },
    BacnetPriorityArray {
        device_instance: u32,
        object_type: String,
        object_instance: u32,
    },
}

impl ReadTarget {
    pub fn is_metadata(&self) -> bool {
        matches!(self, Self::ConnectorMetadata)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorReadRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub target: ReadTarget,
}

impl ConnectorReadRequest {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != READ_PROXY_CONTRACT_V1 {
            return Err(format!("unsupported read proxy schema {}", self.schema));
        }
        self.scope.validate()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ReadError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum ReadValueState {
    Null,
    Value,
    Error,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ReadPointResult {
    pub device_instance: u32,
    pub object_type: String,
    pub object_instance: u32,
    pub property_id: String,
    #[serde(rename = "type")]
    pub value_type: String,
    pub value: serde_json::Value,
    pub quality: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ReadPrioritySlot {
    pub priority_level: u8,
    pub state: ReadValueState,
    #[serde(rename = "type")]
    pub value_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ReadPriorityArrayResult {
    pub device_instance: u32,
    pub object_type: String,
    pub object_instance: u32,
    pub slots: Vec<ReadPrioritySlot>,
    pub state: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ConnectorReadResult {
    Metadata { hello: ConnectorHelloResponse },
    Point(ReadPointResult),
    PriorityArray(ReadPriorityArrayResult),
}

impl ConnectorReadResult {
    pub fn validate(&self) -> Result<(), String> {
        match self {
            Self::Metadata { hello } => hello.validate(),
            Self::Point(point) => {
                if point.object_type.trim().is_empty()
                    || point.property_id.trim().is_empty()
                    || point.value_type.trim().is_empty()
                    || point.value_type.len() > 64
                    || !safe_public_token(&point.object_type)
                    || !safe_public_token(&point.property_id)
                    || !safe_public_token(&point.value_type)
                    || !matches!(point.quality.as_str(), "good" | "bad")
                    || !safe_public_value(&point.value)
                {
                    return Err("invalid typed point result".into());
                }
                Ok(())
            }
            Self::PriorityArray(array) => {
                if array.slots.len() != 16
                    || array.object_type.trim().is_empty()
                    || !safe_public_token(&array.object_type)
                    || !matches!(
                        array.state.as_str(),
                        "supported" | "unsupported" | "unknown"
                    )
                {
                    return Err(
                        "priority-array result must contain exactly sixteen typed slots".into(),
                    );
                }
                let mut levels = [false; 16];
                for slot in &array.slots {
                    if !(1..=16).contains(&slot.priority_level)
                        || levels[usize::from(slot.priority_level - 1)]
                        || slot.value_type.trim().is_empty()
                        || slot.value_type.len() > 64
                        || !safe_public_token(&slot.value_type)
                        || slot.error.as_deref().is_some_and(|error| {
                            error.len() > 128 || error.chars().any(|ch| ch.is_control())
                        })
                    {
                        return Err("priority-array slot indexes must be unique P1-P16".into());
                    }
                    levels[usize::from(slot.priority_level - 1)] = true;
                    match slot.state {
                        ReadValueState::Null if slot.value.is_some() || slot.error.is_some() => {
                            return Err("NULL priority slots cannot carry a value or error".into())
                        }
                        ReadValueState::Value if slot.value.is_none() || slot.error.is_some() => {
                            return Err("value priority slots require exactly one value".into())
                        }
                        ReadValueState::Error
                            if slot.value.is_some()
                                || slot.error.as_deref().is_none_or(str::is_empty) =>
                        {
                            return Err("error priority slots require an error only".into())
                        }
                        ReadValueState::Unknown if slot.value.is_some() => {
                            return Err("unknown priority slots cannot carry a value".into())
                        }
                        _ => {}
                    }
                    if let Some(value) = &slot.value {
                        if !safe_public_value(value) {
                            return Err("priority slot value is not a public scalar".into());
                        }
                    }
                }
                Ok(())
            }
        }
    }

    pub fn validate_for_target(&self, target: &ReadTarget) -> Result<(), String> {
        self.validate()?;
        match (target, self) {
            (ReadTarget::ConnectorMetadata, Self::Metadata { .. }) => Ok(()),
            (
                ReadTarget::BacnetPoint {
                    device_instance,
                    object_type,
                    object_instance,
                    property_id,
                },
                Self::Point(point),
            ) if point.device_instance == *device_instance
                && point.object_instance == *object_instance
                && point.object_type.eq_ignore_ascii_case(object_type)
                && point.property_id.eq_ignore_ascii_case(property_id) =>
            {
                Ok(())
            }
            (
                ReadTarget::BacnetPriorityArray {
                    device_instance,
                    object_type,
                    object_instance,
                },
                Self::PriorityArray(array),
            ) if array.device_instance == *device_instance
                && array.object_instance == *object_instance
                && array.object_type.eq_ignore_ascii_case(object_type) =>
            {
                Ok(())
            }
            _ => Err("read result does not match the requested target".into()),
        }
    }
}

fn safe_public_value(value: &serde_json::Value) -> bool {
    match value {
        serde_json::Value::Null
        | serde_json::Value::Bool(_)
        | serde_json::Value::Number(_)
        | serde_json::Value::String(_) => true,
        serde_json::Value::Array(values) => values.iter().all(safe_public_value),
        serde_json::Value::Object(_) => false,
    }
}

fn safe_public_token(value: &str) -> bool {
    value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorReadResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub ok: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capability_contract: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[cfg_attr(feature = "openapi", schema(value_type = Object))]
    pub result: Option<ConnectorReadResult>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<ReadError>,
}

impl ConnectorReadResponse {
    pub fn success(request: &ConnectorReadRequest, result: ConnectorReadResult) -> Self {
        Self {
            schema: READ_PROXY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            ok: true,
            capability_contract: Some(CAPABILITIES_CONTRACT_V1.into()),
            result: Some(result),
            error: None,
        }
    }

    pub fn validate_for(&self, request: &ConnectorReadRequest) -> Result<(), String> {
        if self.schema != READ_PROXY_CONTRACT_V1
            || self.request_id != request.request_id
            || self.scope != request.scope
        {
            return Err("read proxy response correlation failed".into());
        }
        if self.ok {
            if self.result.is_none() || self.error.is_some() {
                return Err("successful read proxy response is malformed".into());
            }
            if self.capability_contract.as_deref() != Some(CAPABILITIES_CONTRACT_V1) {
                return Err("successful read proxy capability contract mismatch".into());
            }
            let result = self
                .result
                .as_ref()
                .ok_or_else(|| "successful read proxy result is missing".to_string())?;
            result.validate_for_target(&request.target)
        } else if self.result.is_some() || self.error.is_none() {
            Err("failed read proxy response is malformed".into())
        } else {
            let error = self
                .error
                .as_ref()
                .ok_or_else(|| "failed read proxy error is missing".to_string())?;
            if error.code.trim().is_empty()
                || error.code.len() > 64
                || !safe_public_token(&error.code)
                || error.message.len() > 128
                || error.message.chars().any(|ch| ch.is_control())
            {
                return Err("failed read proxy error is not a public error".into());
            }
            Ok(())
        }
    }

    pub fn failure(request: &ConnectorReadRequest, code: &str, message: impl Into<String>) -> Self {
        Self {
            schema: READ_PROXY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            ok: false,
            capability_contract: None,
            result: None,
            error: Some(ReadError {
                code: code.into(),
                message: message.into(),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(target: ReadTarget) -> ConnectorReadRequest {
        ConnectorReadRequest {
            schema: READ_PROXY_CONTRACT_V1.into(),
            request_id: Uuid::nil(),
            scope: ConnectorScope {
                tenant_id: "tenant".into(),
                building_id: "building".into(),
                edge_id: "edge".into(),
            },
            target,
        }
    }

    #[test]
    fn proxy_contract_has_only_read_targets() {
        let req = request(ReadTarget::ConnectorMetadata);
        req.validate().unwrap();
        let encoded = serde_json::to_value(&req).unwrap();
        assert_eq!(encoded["target"]["kind"], "connector_metadata");
        assert!(serde_json::from_value::<ConnectorReadRequest>(encoded).is_ok());
    }

    #[test]
    fn scope_rejects_path_escapes() {
        let mut req = request(ReadTarget::ConnectorMetadata);
        req.scope.edge_id = "../other-edge".into();
        assert!(req.validate().is_err());
    }

    #[test]
    fn successful_response_requires_typed_result_and_exact_correlation() {
        let req = request(ReadTarget::ConnectorMetadata);
        let response = ConnectorReadResponse::success(
            &req,
            ConnectorReadResult::Metadata {
                hello: ConnectorHelloResponse {
                    schema: CAPABILITIES_CONTRACT_V1.into(),
                    version: crate::capabilities::ServiceVersion {
                        service: "fieldbus".into(),
                        build: "test".into(),
                        contract: CAPABILITIES_CONTRACT_V1.into(),
                    },
                    compiled_protocols: vec![],
                    connectors: vec![],
                    recipe: crate::capabilities::RecipeObservation {
                        declared: None,
                        observed_services: vec![],
                        reconciliation: "not_declared".into(),
                    },
                    observed_at: chrono::Utc::now(),
                },
            },
        );
        response.validate_for(&req).unwrap();
    }
}
