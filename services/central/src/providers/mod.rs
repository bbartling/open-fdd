//! Pluggable HTTPS data providers (Wave-NF): NF portal first, Ace IoT stub.

pub mod ace_stub;
pub mod config;
pub mod map;
pub mod nf;
pub mod poller;
pub mod types;
pub mod writer;

use std::sync::Arc;

use axum::extract::State;
use axum::Extension;
use axum::Json;
use tokio::sync::Mutex;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tracing::warn;

use config::{load_sites_from_env, SiteConfig};
use types::{
    ProviderHealth, ProviderHealthStatus, ProviderKind, ProvidersHealthBody, SiteProviderHealth,
};

use crate::state::AppState;

/// Vendor HTTPS ingest driver (NF portal, future Ace IoT).
pub trait DataProvider: Send + Sync {
    fn provider_id(&self) -> &str;
    fn kind(&self) -> ProviderKind;
    fn health(&self) -> ProviderHealth;
    fn authenticate(&mut self) -> impl std::future::Future<Output = Result<(), String>> + Send;
    fn fetch_latest(
        &mut self,
    ) -> impl std::future::Future<Output = Result<Vec<map::RawProviderPoint>, String>> + Send;
}

impl DataProvider for nf::NfPortalDriver {
    fn provider_id(&self) -> &str {
        nf::NfPortalDriver::provider_id(self)
    }

    fn kind(&self) -> ProviderKind {
        ProviderKind::Nf
    }

    fn health(&self) -> ProviderHealth {
        self.health(ProviderHealthStatus::Ok, None)
    }

    async fn authenticate(&mut self) -> Result<(), String> {
        nf::NfPortalDriver::authenticate(self).await
    }

    async fn fetch_latest(&mut self) -> Result<Vec<map::RawProviderPoint>, String> {
        nf::NfPortalDriver::query_points(self, 200).await
    }
}

impl DataProvider for ace_stub::AceIotStubDriver {
    fn provider_id(&self) -> &str {
        ace_stub::AceIotStubDriver::provider_id(self)
    }

    fn kind(&self) -> ProviderKind {
        ProviderKind::AceIot
    }

    fn health(&self) -> ProviderHealth {
        ace_stub::AceIotStubDriver::health(self)
    }

    async fn authenticate(&mut self) -> Result<(), String> {
        ace_stub::AceIotStubDriver::authenticate(self).await
    }

    async fn fetch_latest(&mut self) -> Result<Vec<map::RawProviderPoint>, String> {
        ace_stub::AceIotStubDriver::query_points(self).await
    }
}

pub struct Runtime {
    pub sites: Vec<SiteConfig>,
    pub(crate) health: Mutex<ProvidersHealthBody>,
}

impl Runtime {
    pub fn from_env() -> Arc<Self> {
        let sites = match load_sites_from_env() {
            Ok(s) => s,
            Err(err) => {
                warn!(%err, "OPENFDD_PROVIDER_SITES invalid; no provider sites loaded");
                Vec::new()
            }
        };
        let poll_enabled = std::env::var("OPENFDD_PROVIDER_POLL")
            .ok()
            .is_some_and(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
        let site_health: Vec<SiteProviderHealth> = sites
            .iter()
            .map(|site| {
                let status = if matches!(site.kind, ProviderKind::AceIot) {
                    ProviderHealthStatus::NotImplemented
                } else if site.client_id.is_none() && site.endpoint.contains("normal-online.net") {
                    ProviderHealthStatus::NotConfigured
                } else {
                    ProviderHealthStatus::NotConfigured
                };
                SiteProviderHealth {
                    building_id: site.building_id.clone(),
                    provider: site.kind,
                    endpoint: site.endpoint.clone(),
                    poll_secs: site.poll_secs,
                    mapped_points: site.resolver.mapped_count(),
                    health: ProviderHealth {
                        provider_id: provider_id_for_site(site),
                        kind: site.kind,
                        status,
                        message: None,
                        last_success_at: None,
                        last_error_at: None,
                    },
                    last_poll_at: None,
                    last_ingested_points: 0,
                    consecutive_errors: 0,
                }
            })
            .collect();
        Arc::new(Self {
            sites,
            health: Mutex::new(ProvidersHealthBody {
                ok: true,
                poll_enabled,
                sites: site_health,
            }),
        })
    }

    pub async fn health_snapshot(&self) -> ProvidersHealthBody {
        self.health.lock().await.clone()
    }

    pub fn sites_config(&self) -> Vec<SiteConfigSummary> {
        self.sites
            .iter()
            .map(|s| SiteConfigSummary {
                building_id: s.building_id.clone(),
                provider: s.kind,
                endpoint: s.endpoint.clone(),
                poll_secs: s.poll_secs,
                mapped_points: s.resolver.mapped_count(),
                client_id_configured: s.client_id.is_some(),
            })
            .collect()
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SiteConfigSummary {
    pub building_id: String,
    pub provider: ProviderKind,
    pub endpoint: String,
    pub poll_secs: u64,
    pub mapped_points: usize,
    pub client_id_configured: bool,
}

pub async fn providers_health(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<crate::auth::AuthUser>,
) -> Json<ProvidersHealthBody> {
    let ctx = crate::tenant::TenantContext::resolve_fail_closed(
        &user,
        &state.control_plane.read().await.clone(),
    );
    let mut body = state.providers.health_snapshot().await;
    body.sites.retain(|s| ctx.allow_building(&s.building_id));
    // Do not leak foreign-site endpoints/errors; strip messages for non-hub when MT on.
    if ctx.multi_tenant && !ctx.hub_admin {
        for site in &mut body.sites {
            if let Some(msg) = site.health.message.as_mut() {
                *msg = truncate_safe(msg, 120);
            }
        }
    }
    Json(body)
}

pub async fn providers_sites(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<crate::auth::AuthUser>,
) -> Json<serde_json::Value> {
    let ctx = crate::tenant::TenantContext::resolve_fail_closed(
        &user,
        &state.control_plane.read().await.clone(),
    );
    let sites: Vec<_> = state
        .providers
        .sites_config()
        .into_iter()
        .filter(|s| ctx.allow_building(&s.building_id))
        .collect();
    let mut health = state.providers.health_snapshot().await;
    health.sites.retain(|s| ctx.allow_building(&s.building_id));
    Json(serde_json::json!({
        "ok": true,
        "poll_enabled": health.poll_enabled,
        "sites": sites,
        "health": health.sites,
    }))
}

fn truncate_safe(s: &str, max: usize) -> String {
    let mut out = String::new();
    for (i, ch) in s.chars().enumerate() {
        if i >= max {
            out.push('…');
            break;
        }
        out.push(ch);
    }
    out
}

fn provider_id_for_site(site: &SiteConfig) -> String {
    match site.kind {
        ProviderKind::Nf => format!("nf:{}", site.building_id),
        ProviderKind::AceIot => format!("ace_iot:{}", site.building_id),
    }
}

pub fn spawn_poller_with_shutdown(
    state: Arc<AppState>,
    shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    let runtime = Arc::clone(&state.providers);
    poller::spawn_with_shutdown(state, runtime, shutdown)
}
