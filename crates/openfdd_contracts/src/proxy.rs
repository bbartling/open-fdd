//! Scoped, read-only connector proxy contract.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::capabilities::CAPABILITIES_CONTRACT_V1;

pub const READ_PROXY_CONTRACT_V1: &str = "openfdd.connector.read.v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorScope {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tenant_id: Option<String>,
    pub building_id: String,
    pub edge_id: String,
}

impl ConnectorScope {
    pub fn validate(&self) -> Result<(), String> {
        if self.building_id.trim().is_empty() || self.edge_id.trim().is_empty() {
            return Err("building_id and edge_id are required".into());
        }
        for (name, value) in [
            ("tenant_id", self.tenant_id.as_deref().unwrap_or("")),
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
    pub result: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<ReadError>,
}

impl ConnectorReadResponse {
    pub fn success(request: &ConnectorReadRequest, result: serde_json::Value) -> Self {
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
                tenant_id: Some("tenant".into()),
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
}
