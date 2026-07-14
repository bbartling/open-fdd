//! Batched Haystack-style telemetry envelopes for MQTTS.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::SCHEMA_V1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum Protocol {
    Bacnet,
    Modbus,
    Haystack,
    JsonApi,
    Weather,
    Mixed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum Quality {
    #[default]
    Good,
    Uncertain,
    Bad,
    Stale,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum ValueKind {
    Number,
    Bool,
    String,
    Null,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct SchemaVersion {
    pub name: String,
}

impl Default for SchemaVersion {
    fn default() -> Self {
        Self {
            name: SCHEMA_V1.to_string(),
        }
    }
}

/// One point sample inside a batched telemetry envelope.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct TelemetryPoint {
    /// Canonical ID, e.g. `bacnet:5007:analog-input:1001` or `equip:ahu-1:oa_t`.
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<ValueKind>,
    #[serde(default)]
    #[cfg_attr(feature = "openapi", schema(value_type = Object))]
    pub value: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    #[serde(default)]
    pub quality: Quality,
    /// Extensible Haystack-style marker/reference tags.
    #[serde(default, skip_serializing_if = "serde_json::Map::is_empty")]
    #[cfg_attr(feature = "openapi", schema(value_type = Object))]
    pub tags: serde_json::Map<String, serde_json::Value>,
}

/// Versioned batched telemetry message published by fieldbus.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct TelemetryEnvelope {
    pub schema: String,
    pub message_id: Uuid,
    pub sequence: u64,
    pub observed_at: DateTime<Utc>,
    pub site_id: String,
    pub edge_id: String,
    pub protocol: Protocol,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub device_id: Option<String>,
    pub points: Vec<TelemetryPoint>,
}

impl TelemetryEnvelope {
    pub fn new(
        site_id: impl Into<String>,
        edge_id: impl Into<String>,
        protocol: Protocol,
        sequence: u64,
        points: Vec<TelemetryPoint>,
    ) -> Self {
        Self {
            schema: SCHEMA_V1.to_string(),
            message_id: Uuid::new_v4(),
            sequence,
            observed_at: Utc::now(),
            site_id: site_id.into(),
            edge_id: edge_id.into(),
            protocol,
            device_id: None,
            points,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema != SCHEMA_V1 {
            return Err(format!("unsupported schema {}", self.schema));
        }
        if self.site_id.is_empty() || self.edge_id.is_empty() {
            return Err("site_id and edge_id required".into());
        }
        if self.points.is_empty() {
            return Err("points must be non-empty".into());
        }
        for p in &self.points {
            if p.id.is_empty() {
                return Err("point id required".into());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_json() {
        let env = TelemetryEnvelope::new(
            "site-a",
            "edge-1",
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "bacnet:599999:analog-value:9101".into(),
                display_name: Some("outside-air-temperature".into()),
                kind: Some(ValueKind::Number),
                value: serde_json::json!(72.5),
                unit: Some("°F".into()),
                quality: Quality::Good,
                tags: serde_json::json!({"sensor": true, "air": true})
                    .as_object()
                    .cloned()
                    .unwrap_or_default(),
            }],
        );
        env.validate().unwrap();
        let s = serde_json::to_string(&env).unwrap();
        let back: TelemetryEnvelope = serde_json::from_str(&s).unwrap();
        assert_eq!(back.points[0].id, env.points[0].id);
    }
}
