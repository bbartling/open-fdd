//! Explicit provider capabilities (N4).
//!
//! The registry is the contract the hourly worker checks before a history read.
//! NF history is `GET /api/v1/point/data` inside a bounded window. `POST` on
//! that path is a write and is not a capability. Ace stays unimplemented.
//! Open-Meteo is declared here only after `ProviderKind` includes it (N9).

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use super::error::{ProviderError, ProviderErrorCode};
use super::hourly::{UPDATE_LOG_HTTP, UPDATE_LOG_STATUS};
use super::http_policy::{MAX_HISTORY_WINDOW, MAX_UUIDS_PER_REQUEST, MAX_UUIDS_TOTAL};
use super::types::ProviderKind;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderCapability {
    /// Latest-value scrape. This does not advance the coverage ledger.
    Latest,
    /// Bounded history read. NF implements this as GET point/data only.
    FetchHistory,
}

impl ProviderCapability {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Latest => "latest",
            Self::FetchHistory => "fetch_history",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HistoryWindowLimits {
    pub max_window_secs: i64,
    pub max_ids_per_request: usize,
    pub max_ids_total: usize,
    /// Must be `GET` for NF. A `POST` contract is rejected before any socket.
    pub http_method: String,
    pub path: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProviderContract {
    pub kind: ProviderKind,
    pub implemented: bool,
    pub capabilities: Vec<ProviderCapability>,
    pub history: Option<HistoryWindowLimits>,
    /// Set when the upstream gap log was probed and denied. NF lab key: 403.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub update_log_http: Option<u16>,
    pub update_log_status: String,
    /// Always false. Update-log 403 means this driver cannot claim gapless copy.
    pub gapless: bool,
}

pub fn nf_contract() -> ProviderContract {
    ProviderContract {
        kind: ProviderKind::Nf,
        implemented: true,
        capabilities: vec![ProviderCapability::Latest, ProviderCapability::FetchHistory],
        history: Some(HistoryWindowLimits {
            max_window_secs: MAX_HISTORY_WINDOW.num_seconds(),
            max_ids_per_request: MAX_UUIDS_PER_REQUEST,
            max_ids_total: MAX_UUIDS_TOTAL,
            http_method: "GET".into(),
            path: "/api/v1/point/data".into(),
        }),
        update_log_http: Some(UPDATE_LOG_HTTP),
        update_log_status: UPDATE_LOG_STATUS.into(),
        gapless: false,
    }
}

pub fn ace_contract() -> ProviderContract {
    ProviderContract {
        kind: ProviderKind::AceIot,
        implemented: false,
        capabilities: Vec::new(),
        history: None,
        update_log_http: None,
        update_log_status: "ace_iot_not_implemented".into(),
        gapless: false,
    }
}

/// Every `ProviderKind` has one contract. Adding a variant without a contract
/// fails this match, which is how Open-Meteo declares capabilities once merged.
pub fn contract_for(kind: ProviderKind) -> ProviderContract {
    match kind {
        ProviderKind::Nf => nf_contract(),
        ProviderKind::AceIot => ace_contract(),
    }
}

pub fn registry() -> Vec<ProviderContract> {
    [ProviderKind::Nf, ProviderKind::AceIot]
        .into_iter()
        .map(contract_for)
        .collect()
}

/// Refuse history reads the contract does not allow. No socket is opened.
pub fn require_history(
    contract: &ProviderContract,
    id_count: usize,
    from: DateTime<Utc>,
    to: DateTime<Utc>,
) -> Result<(), ProviderError> {
    if contract.gapless {
        return Err(ProviderError::contract());
    }
    if !contract.implemented
        || !contract
            .capabilities
            .contains(&ProviderCapability::FetchHistory)
    {
        return Err(ProviderError::not_implemented());
    }
    let Some(limits) = &contract.history else {
        return Err(ProviderError::not_implemented());
    };
    if limits.http_method != "GET" {
        return Err(ProviderError::contract());
    }
    if contract.kind == ProviderKind::Nf && limits.path != "/api/v1/point/data" {
        return Err(ProviderError::contract());
    }
    if limits.path.contains("updates/data") {
        return Err(ProviderError::new(ProviderErrorCode::Forbidden));
    }
    if id_count > limits.max_ids_total {
        return Err(ProviderError::contract());
    }
    if to < from || to - from > chrono::Duration::seconds(limits.max_window_secs.max(0)) {
        return Err(ProviderError::contract());
    }
    Ok(())
}

pub fn supports(contract: &ProviderContract, capability: ProviderCapability) -> bool {
    contract.implemented && contract.capabilities.contains(&capability)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, 0, 0).unwrap()
    }

    #[test]
    fn registry_is_exhaustive_and_ace_is_not_implemented() {
        let rows = registry();
        assert_eq!(rows.len(), 2);
        assert!(rows
            .iter()
            .any(|row| row.kind == ProviderKind::Nf && row.implemented));
        let ace = ace_contract();
        assert!(!ace.implemented);
        assert!(ace.capabilities.is_empty());
        assert!(ace.history.is_none());
        assert!(!ace.gapless);
        assert!(require_history(&ace, 1, ts(9), ts(10)).is_err());
        assert_eq!(
            require_history(&ace, 1, ts(9), ts(10)).unwrap_err().code,
            ProviderErrorCode::NotImplemented
        );
    }

    #[test]
    fn nf_history_is_get_point_data_inside_the_window() {
        let nf = nf_contract();
        assert!(supports(&nf, ProviderCapability::Latest));
        assert!(supports(&nf, ProviderCapability::FetchHistory));
        let limits = nf.history.as_ref().unwrap();
        assert_eq!(limits.http_method, "GET");
        assert_eq!(limits.path, "/api/v1/point/data");
        assert_ne!(limits.http_method, "POST");
        assert!(!nf.gapless);
        assert_eq!(nf.update_log_http, Some(403));
        assert!(nf.update_log_status.contains("not_gapless"));
        assert!(nf.update_log_status.contains("403"));
        assert!(require_history(&nf, 1, ts(9), ts(10)).is_ok());
        assert!(require_history(&nf, 1, ts(0), ts(9)).is_err());
        let mut posted = nf.clone();
        posted.history.as_mut().unwrap().http_method = "POST".into();
        assert_eq!(
            require_history(&posted, 1, ts(9), ts(10)).unwrap_err().code,
            ProviderErrorCode::Contract
        );
        let mut gapless = nf.clone();
        gapless.gapless = true;
        assert!(require_history(&gapless, 1, ts(9), ts(10)).is_err());
    }

    #[test]
    fn open_meteo_is_absent_until_its_kind_exists() {
        assert!(registry()
            .iter()
            .all(|row| row.kind != ProviderKind::AceIot || !row.implemented));
        let names: Vec<_> = registry()
            .iter()
            .map(|row| format!("{:?}", row.kind))
            .collect();
        assert!(!names.iter().any(|name| name.contains("OpenMeteo")));
    }
}
