//! Pluggable HTTPS data providers (Wave-NF): NF portal first, Ace IoT stub.

pub mod ace_stub;
pub mod config;
pub mod hourly;
pub mod hourly_exec;
pub mod map;
pub mod nf;
pub mod pg_store;
pub mod poller;
pub mod store;
pub mod types;
pub mod writer;

use std::sync::Arc;

use axum::extract::State;
use axum::Extension;
use axum::Json;
use tokio::sync::watch;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tracing::warn;

use config::{load_sites_from_env, SiteConfig};
use types::{
    ProviderHealth, ProviderHealthStatus, ProviderKind, ProvidersHealthBody, SiteProviderHealth,
};

use crate::state::AppState;

pub struct Runtime {
    pub sites: Vec<SiteConfig>,
    pub(crate) health: Mutex<ProvidersHealthBody>,
    hourly: Mutex<Option<store::HourlyStore>>,
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
                    hourly_coverage: None,
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
            hourly: Mutex::new(None),
        })
    }

    /// Postgres when `OPENFDD_DATABASE_URL` is set. Memory is explicit and not
    /// durable. A configured URL that cannot be opened is unavailable — the
    /// poller must not fall back to a rolling lookback.
    pub async fn hourly_store(&self) -> store::StoreOpen {
        let mut slot = self.hourly.lock().await;
        if let Some(existing) = slot.clone() {
            return if existing.is_durable() {
                store::StoreOpen::Durable(existing)
            } else {
                store::StoreOpen::MemoryOnly(existing)
            };
        }
        match store::HourlyStore::open_from_env().await {
            store::StoreOpen::Unavailable => store::StoreOpen::Unavailable,
            opened => {
                let store = match &opened {
                    store::StoreOpen::Durable(store) | store::StoreOpen::MemoryOnly(store) => {
                        store.clone()
                    }
                    store::StoreOpen::Unavailable => return store::StoreOpen::Unavailable,
                };
                *slot = Some(store);
                opened
            }
        }
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

fn provider_tenant_ctx(user: &crate::auth::AuthUser) -> crate::tenant::TenantContext {
    let workspace = std::path::PathBuf::from(
        std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into()),
    );
    let plane = crate::tenant::ControlPlane::load_or_legacy(&workspace);
    crate::tenant::TenantContext::resolve_fail_closed(user, &plane)
}

pub async fn providers_health(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<crate::auth::AuthUser>,
) -> Json<ProvidersHealthBody> {
    let ctx = provider_tenant_ctx(&user);
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
    let ctx = provider_tenant_ctx(&user);
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
