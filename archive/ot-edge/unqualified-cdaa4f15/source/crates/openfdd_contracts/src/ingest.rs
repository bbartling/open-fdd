//! Typed receipts for the authenticated local fieldbus ingest path.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const LOCAL_INGEST_RECEIPT_CONTRACT_V1: &str = "openfdd.connector.local_ingest_receipt.v1";

/// Durable outcome of one local ingest message.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum LocalIngestStatus {
    Pending,
    Committed,
    TerminalZeroEligible,
    Rejected,
    Retryable,
    Conflict,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct LocalIngestReceipt {
    pub schema: String,
    /// Authenticated tenant/building scope. This is intentionally opaque to
    /// callers; the site and edge fields below carry the public correlation.
    pub scope: String,
    pub site_id: String,
    pub edge_id: String,
    pub message_id: Uuid,
    pub status: LocalIngestStatus,
    pub duplicate: bool,
    pub eligible_points: usize,
    pub persisted_rows: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl LocalIngestReceipt {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != LOCAL_INGEST_RECEIPT_CONTRACT_V1 {
            return Err("unsupported local ingest receipt schema".into());
        }
        if self.scope.trim().is_empty()
            || self.site_id.trim().is_empty()
            || self.edge_id.trim().is_empty()
        {
            return Err("local ingest receipt scope, site_id, and edge_id are required".into());
        }
        if self.status == LocalIngestStatus::Committed && self.persisted_rows == 0 {
            return Err("committed local ingest receipt must report persisted rows".into());
        }
        if self.status == LocalIngestStatus::TerminalZeroEligible
            && (self.eligible_points != 0 || self.persisted_rows != 0)
        {
            return Err("zero-eligible receipt must report zero points and rows".into());
        }
        if matches!(
            self.status,
            LocalIngestStatus::Rejected
                | LocalIngestStatus::Retryable
                | LocalIngestStatus::Conflict
        ) && self.error.as_deref().is_none_or(str::is_empty)
        {
            return Err("failed local ingest receipt must include an error".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn receipt_roundtrip_and_terminal_state_are_typed() {
        let receipt = LocalIngestReceipt {
            schema: LOCAL_INGEST_RECEIPT_CONTRACT_V1.into(),
            scope: "tenant=t1;building=b1".into(),
            site_id: "site-1".into(),
            edge_id: "edge-1".into(),
            message_id: Uuid::new_v4(),
            status: LocalIngestStatus::TerminalZeroEligible,
            duplicate: false,
            eligible_points: 0,
            persisted_rows: 0,
            error: None,
        };
        receipt.validate().unwrap();
        let decoded: LocalIngestReceipt =
            serde_json::from_value(serde_json::to_value(&receipt).expect("receipt serializes"))
                .expect("receipt decodes");
        assert_eq!(decoded, receipt);
    }
}
