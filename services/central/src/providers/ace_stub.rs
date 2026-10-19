//! Ace IoT driver placeholder (Wave-NF stub).
//!
//! Latest and history stay `NotImplemented`. The stub does not return an empty
//! success page.

use chrono::{DateTime, Utc};

use super::error::{ProviderError, ProviderErrorCode};
use super::map::{HistorySeries, RawProviderPoint};
use super::types::{ProviderHealth, ProviderHealthStatus, ProviderKind};

#[derive(Debug, Clone)]
pub struct AceIotStubDriver {
    provider_id: String,
}

impl AceIotStubDriver {
    pub fn new(provider_instance_id: &str) -> Self {
        Self {
            provider_id: provider_instance_id.to_string(),
        }
    }

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub fn health(&self) -> ProviderHealth {
        ProviderHealth {
            provider_id: self.provider_id.clone(),
            kind: ProviderKind::AceIot,
            status: ProviderHealthStatus::NotImplemented,
            message: Some("not_implemented".into()),
            last_success_at: None,
            last_error_at: None,
        }
    }

    pub async fn authenticate(&mut self) -> Result<(), ProviderError> {
        Err(ProviderError::not_implemented())
    }

    pub async fn query_points(&self) -> Result<Vec<RawProviderPoint>, ProviderError> {
        Err(ProviderError::not_implemented())
    }

    pub async fn fetch_history(
        &mut self,
        _uuids: &[String],
        _from: DateTime<Utc>,
        _to: DateTime<Utc>,
    ) -> Result<Vec<HistorySeries>, ProviderError> {
        Err(ProviderError::new(ProviderErrorCode::NotImplemented))
    }
}
