//! Actuation commands and acknowledgements over MQTTS.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::envelope::Protocol;
use crate::{ACK_SCHEMA_V1, COMMAND_SCHEMA_V1};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum CommandStatus {
    Accepted,
    Rejected,
    Executed,
    Expired,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct CommandEnvelope {
    pub schema: String,
    pub command_id: Uuid,
    pub issued_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
    pub site_id: String,
    pub edge_id: String,
    pub protocol: Protocol,
    pub target_id: String,
    #[cfg_attr(feature = "openapi", schema(value_type = Object))]
    pub value: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub priority: Option<u8>,
    pub approved_by: String,
    pub response_topic: String,
}

impl CommandEnvelope {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        site_id: impl Into<String>,
        edge_id: impl Into<String>,
        protocol: Protocol,
        target_id: impl Into<String>,
        value: serde_json::Value,
        approved_by: impl Into<String>,
        response_topic: impl Into<String>,
        ttl_secs: i64,
    ) -> Self {
        let now = Utc::now();
        Self {
            schema: COMMAND_SCHEMA_V1.to_string(),
            command_id: Uuid::new_v4(),
            issued_at: now,
            expires_at: now + chrono::Duration::seconds(ttl_secs.max(1)),
            site_id: site_id.into(),
            edge_id: edge_id.into(),
            protocol,
            target_id: target_id.into(),
            value,
            priority: None,
            approved_by: approved_by.into(),
            response_topic: response_topic.into(),
        }
    }

    pub fn is_expired(&self, now: DateTime<Utc>) -> bool {
        now >= self.expires_at
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema != COMMAND_SCHEMA_V1 {
            return Err(format!("unsupported command schema {}", self.schema));
        }
        if self.approved_by.trim().is_empty() {
            return Err("approved_by required".into());
        }
        if self.target_id.is_empty() {
            return Err("target_id required".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct CommandAck {
    pub schema: String,
    pub command_id: Uuid,
    pub status: CommandStatus,
    pub observed_at: DateTime<Utc>,
    pub site_id: String,
    pub edge_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

impl CommandAck {
    pub fn new(
        command: &CommandEnvelope,
        status: CommandStatus,
        detail: impl Into<Option<String>>,
    ) -> Self {
        Self {
            schema: ACK_SCHEMA_V1.to_string(),
            command_id: command.command_id,
            status,
            observed_at: Utc::now(),
            site_id: command.site_id.clone(),
            edge_id: command.edge_id.clone(),
            detail: detail.into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::envelope::Protocol;

    #[test]
    fn command_not_expired_before_deadline() {
        let cmd = CommandEnvelope::new(
            "site",
            "edge",
            Protocol::Bacnet,
            "bacnet:1:analog-value:1",
            serde_json::json!(42),
            "operator",
            "openfdd/v1/sites/site/edges/edge/acks/bacnet",
            300,
        );
        assert!(!cmd.is_expired(cmd.expires_at - chrono::Duration::seconds(1)));
    }

    #[test]
    fn command_expired_at_or_after_deadline() {
        let mut cmd = CommandEnvelope::new(
            "site",
            "edge",
            Protocol::Bacnet,
            "bacnet:1:analog-value:1",
            serde_json::json!(42),
            "operator",
            "openfdd/v1/sites/site/edges/edge/acks/bacnet",
            1,
        );
        cmd.expires_at = Utc::now() - chrono::Duration::seconds(1);
        assert!(cmd.is_expired(Utc::now()));
    }

    #[test]
    fn validate_rejects_empty_approval() {
        let mut cmd = CommandEnvelope::new(
            "site",
            "edge",
            Protocol::Bacnet,
            "bacnet:1:analog-value:1",
            serde_json::json!(42),
            "operator",
            "ack/topic",
            60,
        );
        cmd.approved_by = "  ".into();
        assert!(cmd.validate().is_err());
    }
}
