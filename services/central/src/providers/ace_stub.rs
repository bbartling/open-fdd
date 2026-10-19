//! Ace IoT driver placeholder (Wave-NF stub).

use super::map::RawProviderPoint;
use super::types::{ProviderHealth, ProviderHealthStatus, ProviderKind};

#[derive(Debug, Clone)]
pub struct AceIotStubDriver {
    provider_id: String,
}

impl AceIotStubDriver {
    pub fn new(building_id: &str) -> Self {
        Self {
            provider_id: format!("ace_iot:{building_id}"),
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
            message: Some("Ace IoT driver stub — configure NF or wait for Ace driver".into()),
            last_success_at: None,
            last_error_at: None,
        }
    }

    pub async fn authenticate(&mut self) -> Result<(), String> {
        Err("ace_iot driver not implemented".into())
    }

    pub async fn query_points(&self) -> Result<Vec<RawProviderPoint>, String> {
        Ok(Vec::new())
    }
}
