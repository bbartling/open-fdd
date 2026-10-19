//! Compiled provider registry.
//!
//! Every driver either implements bounded `fetch_history` or declares that
//! call unsupported. The hourly scheduler reads this registry before it polls.
//! Open-Meteo joins the list when its driver is compiled (PR #1296).

use chrono::{DateTime, Utc};

use super::http_policy::MAX_HISTORY_WINDOW;
use super::types::{CapabilitySupport, HistoryCapability, ProviderCapabilities, ProviderKind};

/// `false` until `providers/meteo.rs` from PR #1296 is in this crate.
pub const OPEN_METEO_LINKED: bool = false;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderDescriptor {
    pub kind: ProviderKind,
    pub capabilities: ProviderCapabilities,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HistoryRequest {
    pub point_ids: Vec<String>,
    pub from: DateTime<Utc>,
    pub to: DateTime<Utc>,
}

pub fn capabilities_for(kind: ProviderKind) -> ProviderCapabilities {
    match kind {
        ProviderKind::Nf => nf_capabilities(),
        ProviderKind::AceIot => ace_capabilities(),
    }
}

pub fn descriptors() -> Vec<ProviderDescriptor> {
    // When PR #1296 links Open-Meteo, add `ProviderKind::OpenMeteo` here and
    // flip `OPEN_METEO_LINKED`. `capabilities_for` is exhaustive, so the new
    // variant cannot compile without an explicit history declaration.
    let linked = [ProviderKind::Nf, ProviderKind::AceIot];
    let mut rows: Vec<ProviderDescriptor> = linked
        .into_iter()
        .map(|kind| ProviderDescriptor {
            kind,
            capabilities: capabilities_for(kind),
        })
        .collect();
    if let Some(meteo) = open_meteo_descriptor() {
        if OPEN_METEO_LINKED {
            rows.push(meteo);
        }
    }
    rows
}

/// PR #1296's Open-Meteo driver is not compiled on this branch.
/// The declaration below is the contract that driver must publish:
/// `latest` supported (mapped series only), `catalog` unsupported,
/// `fetch_history` GET on the allowlisted archive/forecast origin with
/// `max_window_secs` of 48 hours (`meteo::MAX_METEO_WINDOW`).
fn open_meteo_descriptor() -> Option<ProviderDescriptor> {
    None
}

fn nf_capabilities() -> ProviderCapabilities {
    ProviderCapabilities {
        latest: CapabilitySupport::Supported,
        catalog: CapabilitySupport::Supported,
        fetch_history: HistoryCapability {
            support: CapabilitySupport::Supported,
            method: Some("GET".into()),
            path: Some("/api/v1/point/data".into()),
            max_window_secs: Some(MAX_HISTORY_WINDOW.num_seconds()),
            reason: None,
        },
    }
}

fn ace_capabilities() -> ProviderCapabilities {
    ProviderCapabilities {
        latest: CapabilitySupport::Unsupported,
        catalog: CapabilitySupport::Unsupported,
        fetch_history: HistoryCapability {
            support: CapabilitySupport::Unsupported,
            method: None,
            path: None,
            max_window_secs: None,
            reason: Some("not_implemented".into()),
        },
    }
}

pub fn history_supported(caps: &ProviderCapabilities) -> bool {
    caps.fetch_history.support == CapabilitySupport::Supported
        && caps.fetch_history.method.as_deref() == Some("GET")
        && caps
            .fetch_history
            .max_window_secs
            .is_some_and(|secs| secs > 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_declares_nf_get_history_and_ace_not_implemented() {
        let rows = descriptors();
        assert_eq!(rows.len(), if OPEN_METEO_LINKED { 3 } else { 2 });
        let nf = rows
            .iter()
            .find(|row| row.kind == ProviderKind::Nf)
            .unwrap();
        assert_eq!(nf.capabilities.latest, CapabilitySupport::Supported);
        assert_eq!(nf.capabilities.catalog, CapabilitySupport::Supported);
        assert!(history_supported(&nf.capabilities));
        assert_eq!(nf.capabilities.fetch_history.method.as_deref(), Some("GET"));
        assert_eq!(
            nf.capabilities.fetch_history.path.as_deref(),
            Some("/api/v1/point/data")
        );
        assert_eq!(
            nf.capabilities.fetch_history.max_window_secs,
            Some(MAX_HISTORY_WINDOW.num_seconds())
        );

        let ace = rows
            .iter()
            .find(|row| row.kind == ProviderKind::AceIot)
            .unwrap();
        assert_eq!(ace.capabilities.latest, CapabilitySupport::Unsupported);
        assert_eq!(
            ace.capabilities.fetch_history.support,
            CapabilitySupport::Unsupported
        );
        assert_eq!(
            ace.capabilities.fetch_history.reason.as_deref(),
            Some("not_implemented")
        );
        assert!(!history_supported(&ace.capabilities));
        assert!(open_meteo_descriptor().is_none());
    }

    #[test]
    fn every_compiled_kind_has_one_descriptor() {
        for kind in [ProviderKind::Nf, ProviderKind::AceIot] {
            let matches = descriptors()
                .into_iter()
                .filter(|row| row.kind == kind)
                .count();
            assert_eq!(matches, 1);
            let _ = capabilities_for(kind);
        }
    }
}
