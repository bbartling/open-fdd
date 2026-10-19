//! Explicit provider capabilities (N4).
//!
//! `latest` does not imply `fetch_history`. NF history is
//! `GET /api/v1/point/data` inside a bounded window. `POST` on that path is a
//! write and is not advertised. The NF update log stays `NotImplemented`
//! because the lab key received HTTP 403. Ace advertises every capability as
//! `NotImplemented`.

use super::http_policy::MAX_HISTORY_WINDOW;
use super::types::{
    CapabilityName, CapabilitySupport, ProviderCapability, ProviderKind, ProviderRegistration,
};

pub fn registrations() -> Vec<ProviderRegistration> {
    vec![
        ProviderRegistration {
            kind: ProviderKind::Nf,
            capabilities: capabilities_for(ProviderKind::Nf),
        },
        ProviderRegistration {
            kind: ProviderKind::AceIot,
            capabilities: capabilities_for(ProviderKind::AceIot),
        },
        ProviderRegistration {
            kind: ProviderKind::OpenMeteo,
            capabilities: capabilities_for(ProviderKind::OpenMeteo),
        },
    ]
}

pub fn capabilities_for(kind: ProviderKind) -> Vec<ProviderCapability> {
    match kind {
        ProviderKind::Nf => nf_capabilities(),
        ProviderKind::AceIot => ace_capabilities(),
        ProviderKind::OpenMeteo => meteo_capabilities(),
    }
}

fn nf_capabilities() -> Vec<ProviderCapability> {
    let max_window = MAX_HISTORY_WINDOW.num_seconds();
    vec![
        ProviderCapability {
            name: CapabilityName::Authenticate,
            support: CapabilitySupport::Implemented,
            http_method: Some("POST".into()),
            path: Some("/api/v1/auth/token".into()),
            max_window_secs: None,
            note: None,
        },
        ProviderCapability {
            name: CapabilityName::Latest,
            support: CapabilitySupport::Implemented,
            http_method: Some("POST".into()),
            path: Some("/api/v1/point/query".into()),
            max_window_secs: None,
            note: Some("latest scrape is not history coverage".into()),
        },
        ProviderCapability {
            name: CapabilityName::FetchHistory,
            support: CapabilitySupport::Implemented,
            http_method: Some("GET".into()),
            path: Some("/api/v1/point/data".into()),
            max_window_secs: Some(max_window),
            note: Some(
                "POST /api/v1/point/data is a write and is not this capability".into(),
            ),
        },
        ProviderCapability {
            name: CapabilityName::BoundedWindows,
            support: CapabilitySupport::Implemented,
            http_method: Some("GET".into()),
            path: Some("/api/v1/point/data".into()),
            max_window_secs: Some(max_window),
            note: Some(
                "history requests longer than max_window_secs are rejected before the portal is called"
                    .into(),
            ),
        },
        ProviderCapability {
            name: CapabilityName::UpdateLog,
            support: CapabilitySupport::NotImplemented,
            http_method: Some("GET".into()),
            path: Some("/api/v1/point/updates/data".into()),
            max_window_secs: None,
            note: Some(
                "lab key returned HTTP 403; the driver does not call this path".into(),
            ),
        },
    ]
}

fn meteo_capabilities() -> Vec<ProviderCapability> {
    let max_window = super::meteo::MAX_METEO_WINDOW.num_seconds();
    vec![
        ProviderCapability {
            name: CapabilityName::Authenticate,
            support: CapabilitySupport::Implemented,
            http_method: None,
            path: None,
            max_window_secs: None,
            note: Some("public API; no token exchange".into()),
        },
        ProviderCapability {
            name: CapabilityName::Latest,
            support: CapabilitySupport::Implemented,
            http_method: Some("GET".into()),
            path: Some("/v1/forecast".into()),
            max_window_secs: None,
            note: Some("empty without mapped series; history is the ingest path".into()),
        },
        ProviderCapability {
            name: CapabilityName::FetchHistory,
            support: CapabilitySupport::Implemented,
            http_method: Some("GET".into()),
            path: Some("/v1/forecast".into()),
            max_window_secs: Some(max_window),
            note: Some("allowlisted Open-Meteo series ids only".into()),
        },
        ProviderCapability {
            name: CapabilityName::BoundedWindows,
            support: CapabilitySupport::Implemented,
            http_method: Some("GET".into()),
            path: Some("/v1/forecast".into()),
            max_window_secs: Some(max_window),
            note: Some("windows longer than 48 hours are rejected before the request".into()),
        },
        ProviderCapability {
            name: CapabilityName::UpdateLog,
            support: CapabilitySupport::NotImplemented,
            http_method: None,
            path: None,
            max_window_secs: None,
            note: Some("Open-Meteo has no update log".into()),
        },
    ]
}

fn ace_capabilities() -> Vec<ProviderCapability> {
    [
        CapabilityName::Authenticate,
        CapabilityName::Latest,
        CapabilityName::FetchHistory,
        CapabilityName::BoundedWindows,
        CapabilityName::UpdateLog,
    ]
    .into_iter()
    .map(|name| ProviderCapability {
        name,
        support: CapabilitySupport::NotImplemented,
        http_method: None,
        path: None,
        max_window_secs: None,
        note: Some("Ace IoT driver stub".into()),
    })
    .collect()
}

#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "conformance tests look up one capability from the registry"
    )
)]
pub fn capability(
    caps: &[ProviderCapability],
    name: CapabilityName,
) -> Option<&ProviderCapability> {
    caps.iter().find(|cap| cap.name == name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::ace_stub::AceIotStubDriver;
    use crate::providers::error::ProviderErrorCode;
    use crate::providers::http_policy::HttpLimits;
    use crate::providers::nf::{history_http_method, NfPortalDriver};
    use crate::providers::DataProvider;
    use chrono::{Duration, Utc};

    #[test]
    fn registry_lists_nf_history_as_get_and_ace_as_not_implemented() {
        let regs = registrations();
        assert_eq!(regs.len(), 3);
        let meteo = capabilities_for(ProviderKind::OpenMeteo);
        let meteo_history = capability(&meteo, CapabilityName::FetchHistory).unwrap();
        assert_eq!(meteo_history.support, CapabilitySupport::Implemented);
        assert_eq!(meteo_history.http_method.as_deref(), Some("GET"));
        assert_eq!(meteo_history.path.as_deref(), Some("/v1/forecast"));
        assert_eq!(
            capability(&meteo, CapabilityName::UpdateLog)
                .unwrap()
                .support,
            CapabilitySupport::NotImplemented
        );
        let nf = capabilities_for(ProviderKind::Nf);
        let history = capability(&nf, CapabilityName::FetchHistory).unwrap();
        assert_eq!(history.support, CapabilitySupport::Implemented);
        assert_eq!(history.http_method.as_deref(), Some("GET"));
        assert_eq!(history.path.as_deref(), Some("/api/v1/point/data"));
        assert_eq!(
            history.max_window_secs,
            Some(MAX_HISTORY_WINDOW.num_seconds())
        );
        assert!(history.note.as_deref().unwrap().contains("POST"));
        assert_eq!(history_http_method(), "GET");
        let bounded = capability(&nf, CapabilityName::BoundedWindows).unwrap();
        assert_eq!(bounded.max_window_secs, history.max_window_secs);
        let update_log = capability(&nf, CapabilityName::UpdateLog).unwrap();
        assert_eq!(update_log.support, CapabilitySupport::NotImplemented);
        assert_eq!(
            update_log.path.as_deref(),
            Some("/api/v1/point/updates/data")
        );
        assert!(update_log.note.as_deref().unwrap().contains("403"));
        let latest = capability(&nf, CapabilityName::Latest).unwrap();
        assert_ne!(latest.path, history.path);

        let ace = capabilities_for(ProviderKind::AceIot);
        assert!(ace
            .iter()
            .all(|cap| cap.support == CapabilitySupport::NotImplemented));
        assert!(ace.iter().all(|cap| cap.http_method.is_none()));
    }

    #[tokio::test]
    async fn ace_fetch_history_and_latest_stay_not_implemented() {
        let mut ace = AceIotStubDriver::new("ace_iot:explicit");
        assert!(ace
            .capabilities()
            .iter()
            .all(|cap| cap.support == CapabilitySupport::NotImplemented));
        let from = Utc::now() - Duration::minutes(30);
        let err = DataProvider::fetch_history(&mut ace, &["point-1".into()], from, Utc::now())
            .await
            .unwrap_err();
        assert_eq!(err.code, ProviderErrorCode::NotImplemented);
        let latest = DataProvider::fetch_latest(&mut ace).await.unwrap_err();
        assert_eq!(latest, "not_implemented");
        let auth = DataProvider::authenticate(&mut ace).await.unwrap_err();
        assert_eq!(auth, "not_implemented");
        assert_eq!(
            ace.health().status,
            crate::providers::types::ProviderHealthStatus::NotImplemented
        );
    }

    #[tokio::test]
    async fn nf_history_rejects_an_unbounded_window_before_a_request() {
        let mut driver = NfPortalDriver::new(
            "nf:explicit",
            "https://portal.example",
            None,
            None,
            true,
            HttpLimits::default(),
        )
        .unwrap();
        let from = Utc::now() - Duration::hours(7);
        let err = DataProvider::fetch_history(
            &mut driver,
            &["11111111-2222-3333-4444-555555555555".into()],
            from,
            Utc::now(),
        )
        .await
        .unwrap_err();
        assert_eq!(err.code, ProviderErrorCode::Contract);
        let rendered = err.to_string();
        assert!(!rendered.contains("POST"));
        assert!(!rendered.contains("portal.example"));
    }
}
