//! Pluggable HTTPS data providers (Wave-NF): NF portal first, Ace IoT stub.

pub mod ace_stub;
pub mod committed_model;
pub mod config;
pub mod map;
pub mod nf;
pub mod poller;
pub mod types;
pub mod writer;

use std::sync::Arc;
use std::sync::Mutex as StdMutex;

use axum::extract::State;
use axum::Extension;
use axum::Json;
use tokio::sync::watch;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tracing::warn;

use committed_model::CommittedModelStore;
use config::{load_sites_from_env, SiteConfig};
use map::RoleResolver;
use types::{
    ProviderHealth, ProviderHealthStatus, ProviderKind, ProvidersHealthBody, SiteProviderHealth,
};

use crate::state::AppState;

/// Identity and health for a vendor HTTPS ingest driver.
/// Poll loops call the concrete authenticate and query methods.
pub trait DataProvider: Send + Sync {
    fn provider_id(&self) -> &str;
    fn kind(&self) -> ProviderKind;
    fn health(&self) -> ProviderHealth;
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
}

pub struct Runtime {
    pub sites: Vec<SiteConfig>,
    pub(crate) models: StdMutex<CommittedModelStore>,
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
        let mut models = CommittedModelStore::default();
        for site in &sites {
            match models.try_activate(None, &site.model) {
                Ok(report) => {
                    tracing::debug!(
                        building_id = %site.building_id,
                        revision = %report.revision_id,
                        previous = report.previous_revision_id.as_deref().unwrap_or(""),
                        added = report.added_source_ids.len(),
                        removed = report.removed_source_ids.len(),
                        remapped = report.remapped_source_ids.len(),
                        scheduled = report.scheduled_points,
                        withheld = report.withheld_points,
                        "committed model active"
                    );
                }
                Err(err) => {
                    warn!(
                        %err,
                        building_id = %site.building_id,
                        "committed model did not activate"
                    );
                }
            }
        }
        let compiled = models.compile_count();
        if compiled > 0 {
            tracing::info!(compiled, "committed ingest plans compiled");
        }
        for site in &sites {
            if let Some(rev) = models.active_revision(&site.tenant_id, &site.building_id) {
                tracing::debug!(building_id = %site.building_id, %rev, "active ingest revision");
            }
        }
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
                }
            })
            .collect();
        Arc::new(Self {
            sites,
            models: StdMutex::new(models),
            health: Mutex::new(ProvidersHealthBody {
                ok: true,
                poll_enabled,
                sites: site_health,
            }),
        })
    }

    pub fn resolver_for(&self, tenant_id: &str, site_id: &str) -> RoleResolver {
        let guard = self.models.lock().unwrap_or_else(|err| err.into_inner());
        guard
            .active_plan(tenant_id, site_id)
            .map(RoleResolver::from_plan)
            .unwrap_or_default()
    }

    pub async fn health_snapshot(&self) -> ProvidersHealthBody {
        self.health.lock().await.clone()
    }

    pub fn sites_config(&self) -> Vec<SiteConfigSummary> {
        self.sites
            .iter()
            .map(|s| SiteConfigSummary {
                building_id: s.building_id.clone(),
                tenant_id: s.tenant_id.clone(),
                provider_instance_id: s.provider_instance_id.clone(),
                model_revision: s.resolver.model_revision().map(str::to_string),
                provider: s.kind,
                endpoint: s.endpoint.clone(),
                poll_secs: s.poll_secs,
                mapped_points: s.resolver.mapped_count(),
                client_id_configured: s.client_id.is_some(),
            })
            .collect()
    }
}

/// Reads the driver through `DataProvider` so poll health uses the same id the driver owns.
pub fn driver_identity(driver: &impl DataProvider) -> String {
    let health = driver.health();
    format!(
        "{} {:?} {:?}",
        driver.provider_id(),
        driver.kind(),
        health.status
    )
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SiteConfigSummary {
    pub building_id: String,
    pub tenant_id: String,
    pub provider_instance_id: String,
    pub model_revision: Option<String>,
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
    let ctx = tenant_context_for_user(&user);
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
    let ctx = tenant_context_for_user(&user);
    let sites: Vec<_> = state
        .providers
        .sites_config()
        .into_iter()
        .filter(|s| ctx.allow_building(&s.building_id))
        .collect();
    let withheld = {
        let models = state
            .providers
            .models
            .lock()
            .unwrap_or_else(|err| err.into_inner());
        sites
            .iter()
            .filter_map(|site| {
                let plan = models.active_plan(&site.tenant_id, &site.building_id)?;
                if plan.tenant_id != site.tenant_id || plan.site_id != site.building_id {
                    return None;
                }
                let points: Vec<_> = plan
                    .withheld
                    .iter()
                    .map(|held| {
                        serde_json::json!({
                            "provider_instance_id": held.provider_instance_id,
                            "equipment_id": held.equipment_id,
                            "semantic_point_id": held.semantic_point_id,
                            "source_point_id": held.source_point_id,
                            "reason": held.reason,
                        })
                    })
                    .collect();
                Some(serde_json::json!({
                    "building_id": site.building_id,
                    "schema": plan.schema,
                    "points": points,
                }))
            })
            .collect::<Vec<_>>()
    };
    let mut health = state.providers.health_snapshot().await;
    health.sites.retain(|s| ctx.allow_building(&s.building_id));
    Json(serde_json::json!({
        "ok": true,
        "poll_enabled": health.poll_enabled,
        "sites": sites,
        "withheld": withheld,
        "health": health.sites,
    }))
}

fn tenant_context_for_user(user: &crate::auth::AuthUser) -> crate::tenant::TenantContext {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    crate::tenant::TenantContext::resolve_fail_closed(user, &plane)
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
