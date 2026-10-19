//! Pluggable HTTPS data providers (Wave-NF): NF portal first, Ace IoT stub.

pub mod ace_stub;
pub mod committed_model;
pub mod config;
pub mod error;
pub mod hourly;
pub mod hourly_exec;
pub mod http_policy;
pub mod map;
pub mod nf;
pub mod pg_store;
pub mod poller;
pub mod store;
pub mod types;
pub mod writer;

#[cfg(test)]
mod fixture_acceptance;

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
use config::{load_sites_from_env, SiteConfig, SiteConfigFailure};
use error::safe_operator_code;
use map::RoleResolver;
use types::{
    ProviderHealth, ProviderHealthStatus, ProviderKind, ProvidersHealthBody, SiteProviderHealth,
};

use crate::state::AppState;

/// Vendor HTTPS ingest driver (NF portal, future Ace IoT).
pub trait DataProvider: Send + Sync {
    /// Production poller logs this identity. Tests exercise the same trait.
    fn provider_id(&self) -> &str;
    fn kind(&self) -> ProviderKind;
    fn health(&self) -> ProviderHealth;
    /// Concrete pollers call driver history directly. These stay on the trait
    /// so the next adapter does not grow a second scheduler.
    #[expect(
        dead_code,
        reason = "NF poller uses fetch_history; trait method is the adapter contract"
    )]
    fn authenticate(&mut self) -> impl std::future::Future<Output = Result<(), String>> + Send;
    #[expect(
        dead_code,
        reason = "NF poller uses fetch_history; trait method is the adapter contract"
    )]
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
        nf::NfPortalDriver::authenticate(self)
            .await
            .map_err(|err| err.to_string())
    }

    async fn fetch_latest(&mut self) -> Result<Vec<map::RawProviderPoint>, String> {
        nf::NfPortalDriver::query_points(self, 200)
            .await
            .map_err(|err| err.to_string())
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
    pub(crate) models: StdMutex<CommittedModelStore>,
    pub(crate) health: Mutex<ProvidersHealthBody>,
    hourly: Mutex<Option<store::HourlyStore>>,
}

impl Runtime {
    pub fn from_env() -> Arc<Self> {
        let loaded = match load_sites_from_env() {
            Ok(loaded) => loaded,
            Err(code) => {
                warn!(code = %code, "OPENFDD_PROVIDER_SITES invalid; no provider sites loaded");
                config::ProviderConfigLoad {
                    sites: Vec::new(),
                    failures: Vec::new(),
                    fatal: Some(safe_operator_code(&code)),
                }
            }
        };
        if !loaded.failures.is_empty() {
            warn!(
                failed = loaded.failures.len(),
                "provider sites failed closed and will not poll"
            );
        }
        let poll_enabled = std::env::var("OPENFDD_PROVIDER_POLL")
            .ok()
            .is_some_and(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
        let mut site_health: Vec<SiteProviderHealth> = loaded
            .sites
            .iter()
            .map(|site| health_row(site, initial_status(site), None))
            .collect();
        site_health.extend(loaded.failures.iter().map(failure_row));
        let config_error = loaded.fatal.clone().or_else(|| {
            if loaded.failures.is_empty() {
                None
            } else {
                Some("provider_config_invalid".into())
            }
        });
        let mut models = CommittedModelStore::default();
        for site in &loaded.sites {
            match models.try_activate(None, &site.model) {
                Ok(report) => {
                    tracing::debug!(
                        building_id = %site.building_id,
                        revision = %report.revision_id,
                        scheduled = report.scheduled_points,
                        withheld = report.withheld_points,
                        "committed model active"
                    );
                }
                Err(err) => {
                    warn!(
                        code = %safe_operator_code(&err),
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
        for site in &loaded.sites {
            if let Some(rev) = models.active_revision(&site.tenant_id, &site.building_id) {
                tracing::debug!(building_id = %site.building_id, %rev, "active ingest revision");
            }
        }
        Arc::new(Self {
            sites: loaded.sites,
            models: StdMutex::new(models),
            health: Mutex::new(ProvidersHealthBody {
                ok: config_error.is_none(),
                poll_enabled,
                sites: site_health,
                config_error,
            }),
            hourly: Mutex::new(None),
        })
    }

    /// Live plan for this tick. A failed activation leaves the last valid plan.
    pub fn resolver_for(&self, tenant_id: &str, site_id: &str) -> RoleResolver {
        let guard = self.models.lock().unwrap_or_else(|err| err.into_inner());
        guard
            .active_plan(tenant_id, site_id)
            .map(RoleResolver::from_plan)
            .unwrap_or_default()
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
    let ctx = tenant_context_for(&user);
    Json(visible_health(
        state.providers.health_snapshot().await,
        &ctx,
    ))
}

pub async fn providers_sites(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<crate::auth::AuthUser>,
) -> Json<serde_json::Value> {
    let ctx = tenant_context_for(&user);
    let health = visible_health(state.providers.health_snapshot().await, &ctx);
    let sites: Vec<_> = state
        .providers
        .sites_config()
        .into_iter()
        .filter(|s| ctx.allow_building(&s.building_id))
        .map(|mut site| {
            site.endpoint = visible_endpoint(&site.endpoint, &ctx);
            site
        })
        .collect();
    Json(serde_json::json!({
        "ok": health.ok,
        "poll_enabled": health.poll_enabled,
        "sites": sites,
        "health": health.sites,
    }))
}

fn initial_status(site: &SiteConfig) -> ProviderHealthStatus {
    if matches!(site.kind, ProviderKind::AceIot) {
        ProviderHealthStatus::NotImplemented
    } else {
        ProviderHealthStatus::NotConfigured
    }
}

fn health_row(
    site: &SiteConfig,
    status: ProviderHealthStatus,
    message: Option<String>,
) -> SiteProviderHealth {
    SiteProviderHealth {
        building_id: site.building_id.clone(),
        provider_instance_id: site.provider_instance_id.clone(),
        provider: site.kind,
        endpoint: site.endpoint.clone(),
        poll_secs: site.poll_secs,
        mapped_points: site.resolver.mapped_count(),
        health: ProviderHealth {
            provider_id: site.provider_instance_id.clone(),
            kind: site.kind,
            status,
            message,
            last_success_at: None,
            last_error_at: None,
        },
        last_poll_at: None,
        last_ingested_points: 0,
        consecutive_errors: 0,
        hourly_coverage: None,
    }
}

fn failure_row(failure: &SiteConfigFailure) -> SiteProviderHealth {
    SiteProviderHealth {
        building_id: failure.building_id.clone(),
        provider_instance_id: String::new(),
        provider: ProviderKind::Nf,
        endpoint: "invalid".into(),
        poll_secs: 0,
        mapped_points: 0,
        health: ProviderHealth {
            provider_id: String::new(),
            kind: ProviderKind::Nf,
            status: ProviderHealthStatus::Error,
            message: Some(safe_operator_code(&failure.code)),
            last_success_at: None,
            last_error_at: None,
        },
        last_poll_at: None,
        last_ingested_points: 0,
        consecutive_errors: 0,
        hourly_coverage: None,
    }
}

fn status_is_clear(status: ProviderHealthStatus) -> bool {
    matches!(
        status,
        ProviderHealthStatus::Ok
            | ProviderHealthStatus::NotConfigured
            | ProviderHealthStatus::NotImplemented
    )
}

/// Fail closed: only buildings in the tenant context. Non-hub callers do not
/// receive origins or raw messages. MCP uses these same REST handlers.
pub fn visible_health(
    mut body: ProvidersHealthBody,
    ctx: &crate::tenant::TenantContext,
) -> ProvidersHealthBody {
    body.sites
        .retain(|site| ctx.allow_building(&site.building_id));
    let hub_view = !ctx.multi_tenant || ctx.hub_admin;
    for site in &mut body.sites {
        site.endpoint = visible_endpoint(&site.endpoint, ctx);
        site.health.message = site.health.message.as_deref().map(safe_operator_code);
    }
    if !hub_view {
        body.config_error = None;
    } else if let Some(code) = body.config_error.as_deref() {
        body.config_error = Some(safe_operator_code(code));
    }
    body.ok = body.config_error.is_none()
        && body
            .sites
            .iter()
            .all(|site| status_is_clear(site.health.status));
    body
}

fn tenant_context_for(user: &crate::auth::AuthUser) -> crate::tenant::TenantContext {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    crate::tenant::TenantContext::resolve_fail_closed(user, &plane)
}

fn visible_endpoint(endpoint: &str, ctx: &crate::tenant::TenantContext) -> String {
    if ctx.multi_tenant && !ctx.hub_admin {
        "redacted".into()
    } else {
        endpoint.to_string()
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

pub fn spawn_poller_with_shutdown(
    state: Arc<AppState>,
    shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    let runtime = Arc::clone(&state.providers);
    poller::spawn_with_shutdown(state, runtime, shutdown)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::http_policy::HttpLimits;
    use crate::tenant::TenantContext;

    fn check_provider(provider: &impl DataProvider) {
        assert!(!provider.provider_id().is_empty());
        let _ = provider.kind();
        let _ = provider.health();
    }

    #[test]
    fn data_provider_identity_is_used() {
        let nf = nf::NfPortalDriver::new(
            "nf:explicit",
            "https://portal.example",
            None,
            None,
            true,
            HttpLimits::default(),
        )
        .unwrap();
        let ace = ace_stub::AceIotStubDriver::new("ace_iot:explicit");
        check_provider(&nf);
        check_provider(&ace);
        assert_eq!(ace.provider_id(), "ace_iot:explicit");
    }

    fn site(building: &str, endpoint: &str, message: &str) -> SiteProviderHealth {
        SiteProviderHealth {
            building_id: building.into(),
            provider_instance_id: format!("nf:{building}:abc"),
            provider: ProviderKind::Nf,
            endpoint: endpoint.into(),
            poll_secs: 300,
            mapped_points: 1,
            health: ProviderHealth {
                provider_id: format!("nf:{building}:abc"),
                kind: ProviderKind::Nf,
                status: ProviderHealthStatus::Error,
                message: Some(message.into()),
                last_success_at: None,
                last_error_at: None,
            },
            last_poll_at: None,
            last_ingested_points: 0,
            consecutive_errors: 1,
            hourly_coverage: None,
        }
    }

    fn ctx(buildings: &[&str], hub: bool) -> TenantContext {
        TenantContext {
            tenant_id: if hub { None } else { Some("tenant".into()) },
            building_ids: buildings.iter().map(|s| (*s).to_string()).collect(),
            hub_admin: hub,
            multi_tenant: true,
        }
    }

    #[test]
    fn tenant_filter_hides_foreign_sites_and_raw_errors() {
        let body = ProvidersHealthBody {
            ok: true,
            poll_enabled: true,
            config_error: Some("provider_config_invalid building=SECRET".into()),
            sites: vec![
                site("SITE_A", "https://a.example", "auth_failed request_id=1"),
                site(
                    "SITE_B",
                    "https://user:CANARY@b.example/secret",
                    "CANARY-SECRET-VALUE leaked",
                ),
            ],
        };
        let a = visible_health(body.clone(), &ctx(&["SITE_A"], false));
        assert_eq!(a.sites.len(), 1);
        assert_eq!(a.sites[0].building_id, "SITE_A");
        assert_eq!(a.sites[0].endpoint, "redacted");
        assert_eq!(a.sites[0].health.message.as_deref(), Some("auth_failed"));
        assert!(a.config_error.is_none());
        let rendered = serde_json::to_string(&a).unwrap();
        assert!(!rendered.contains("SITE_B"));
        assert!(!rendered.contains("CANARY"));
        assert!(!rendered.contains("b.example"));

        let empty = visible_health(body.clone(), &ctx(&[], false));
        assert!(empty.sites.is_empty());
        assert!(empty.ok);

        let hub = visible_health(body, &ctx(&[], true));
        assert_eq!(hub.sites.len(), 2);
        assert!(hub.sites.iter().any(|s| s.endpoint.contains("b.example")));
        assert_eq!(
            hub.sites
                .iter()
                .find(|s| s.building_id == "SITE_B")
                .unwrap()
                .health
                .message
                .as_deref(),
            Some("provider_error")
        );
        assert!(!hub.ok);
    }
}
