//! Isolated process entrypoints for the Phase 5B connector split.
//!
//! This module deliberately keeps the two startup graphs separate. The
//! BACnet/Modbus graph constructs the hosted BACnet server, BACnet client,
//! poll engine, and priority scanner; it never constructs HaystackService.
//! The Haystack graph constructs only its outbound Haystack client and a TCP
//! management listener; it never constructs a BACnet service or exposes a
//! BACnet/Modbus route.

use std::collections::BTreeMap;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

use axum::{
    extract::State,
    middleware,
    routing::{get, post},
    Json, Router,
};
use chrono::Utc;
use openfdd_connector_runtime::{auth_middleware, require_api_key_for_bind, AuthState};
use openfdd_contracts::{
    CapabilityState, ConnectorAction, ConnectorCapability, ConnectorHelloResponse,
    ConnectorProtocol, ConnectorScope, DeliveryStatus, RecipeKind, RecipeObservation,
    ServiceIdentity, ServiceVersion, CAPABILITIES_CONTRACT_V1,
};
use openfdd_contracts::{
    HaystackAboutRequest, HaystackCatalogRequest, HaystackCurrentReadRequest,
    HaystackHistoryReadRequest, HaystackNavRequest,
};
use openfdd_mqtt::TelemetrySpool;
use serde_json::{json, Value};
use tokio::sync::Mutex as AsyncMutex;
use tokio::task::JoinHandle;
use tracing::info;
use tracing_subscriber::prelude::*;

use crate::config::{self, Settings, SettingsProfile};
use crate::error::{ApiError, ApiResult};
use crate::routes;
use crate::services::{
    bacnet_client::BacnetClientService, bacnet_server::BacnetServerManager,
    haystack::HaystackService, mqtt_publish_ledger::MqttPublishLedger, poll::PollEngine,
    priority_scan::PriorityScanService, rest::RestClientService,
    telemetry_control::TelemetryControl, weather::WeatherService,
};
use crate::state::AppState;

/// State owned by the Haystack process. Keeping this type independent from
/// AppState makes accidental construction of BACnet services impossible.
#[derive(Clone)]
pub struct HaystackState {
    pub settings: Arc<Settings>,
    pub api_key: Option<String>,
    pub haystack: Arc<HaystackService>,
    pub identity: ServiceIdentity,
    pub manual_sequence: Arc<AtomicU64>,
    pub manual_spool: Arc<AsyncMutex<Option<TelemetrySpool>>>,
    pub manual_gate: Arc<AsyncMutex<()>>,
    pub manual_results: Arc<AsyncMutex<BTreeMap<uuid::Uuid, (String, Value)>>>,
}

fn check_haystack_scope(state: &HaystackState, scope: &ConnectorScope) -> ApiResult<()> {
    scope.validate().map_err(ApiError::BadRequest)?;
    let matches = [
        (
            state.settings.connector_tenant_id.as_deref(),
            scope.tenant_id.as_str(),
        ),
        (
            state.settings.connector_building_id.as_deref(),
            scope.building_id.as_str(),
        ),
        (
            state.settings.connector_edge_id.as_deref(),
            scope.edge_id.as_str(),
        ),
    ]
    .into_iter()
    .all(|(expected, actual)| expected.is_some_and(|value| value == actual));
    if matches {
        Ok(())
    } else {
        Err(ApiError::Forbidden(
            "Haystack scope is outside this connector".into(),
        ))
    }
}

fn build_version() -> String {
    let base = env!("CARGO_PKG_VERSION");
    let sha = std::env::var("OPENFDD_GIT_SHA")
        .or_else(|_| std::env::var("GIT_SHA"))
        .or_else(|_| std::env::var("OPENFDD_FIELDBUS_GIT_SHA"))
        .unwrap_or_default();
    let sha: String = sha
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .take(12)
        .collect();
    if sha.is_empty() {
        base.to_string()
    } else {
        format!("{base}+{sha}")
    }
}

fn configured_api_key() -> Option<String> {
    [
        "OPENFDD_CONNECTOR_API_KEY",
        "OPENFDD_FIELDBUS_API_KEY",
        "RUSTY_GATEWAY_API_KEY",
    ]
    .into_iter()
    .find_map(|name| {
        std::env::var(name)
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    })
}

fn configured_connector_api_key() -> Option<String> {
    std::env::var("OPENFDD_CONNECTOR_API_KEY")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn recipe_for(profile: openfdd_contracts::ConnectorServiceProfile) -> Result<RecipeKind, String> {
    let default = match profile {
        openfdd_contracts::ConnectorServiceProfile::BacnetModbus => RecipeKind::EdgeBacnetModbus,
        openfdd_contracts::ConnectorServiceProfile::Haystack => RecipeKind::EdgeHaystack,
    };
    let recipe = std::env::var("OPENFDD_CONNECTOR_RECIPE")
        .or_else(|_| std::env::var("OPENFDD_RECIPE"))
        .or_else(|_| std::env::var("OPENFDD_BUILD_RECIPE"))
        .map(|raw| RecipeKind::parse(&raw))
        .unwrap_or(Ok(default))?;
    if recipe.permits_profile(profile) {
        Ok(recipe)
    } else {
        Err(format!(
            "recipe '{}' does not permit {}",
            recipe.as_str(),
            profile.service_name()
        ))
    }
}

fn identity_for(
    profile: openfdd_contracts::ConnectorServiceProfile,
) -> Result<ServiceIdentity, String> {
    let identity = ServiceIdentity::new(profile, build_version(), recipe_for(profile)?);
    identity.validate()?;
    Ok(identity)
}

fn init_tracing(service: &str) {
    let filter = tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| {
        tracing_subscriber::EnvFilter::new(format!("{service}=info,security_audit=info"))
    });
    tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer())
        .init();
}

fn app_key_state(host: &str, api_key: Option<String>) -> Result<AuthState, String> {
    require_api_key_for_bind(host, api_key.as_deref())?;
    Ok(AuthState::new(api_key))
}

fn require_connector_api_key(api_key: Option<String>, service: &str) -> Result<String, String> {
    api_key
        .filter(|key| !key.trim().is_empty())
        .ok_or_else(|| format!("{service} requires a non-empty OPENFDD_CONNECTOR_API_KEY"))
}

fn split_health_routes() -> Router<AppState> {
    async fn health(State(state): State<AppState>) -> Json<Value> {
        let poll = state.poll_engine.status().await;
        let scanner = state.priority_scan.status().ok();
        let identity = state.service_identity.clone();
        Json(json!({
            "ok": true,
            "service": identity.as_ref().map(|value| value.service.as_str()).unwrap_or("openfdd-fieldbus"),
            "profile": "bacnet_modbus",
            "process_id": identity.as_ref().map(|value| value.process_id),
            "git_sha": config::git_sha(),
            "poll": poll,
            "scanner": scanner,
        }))
    }

    Router::new()
        .route("/health", get(health))
        .route("/api/health", get(health))
}

/// Build the profile-specific BACnet/Modbus management router. There is no
/// Haystack merge in this function, so /haystack/* is absent by construction.
pub fn bacnet_modbus_router(state: AppState) -> Router {
    Router::new()
        .merge(split_health_routes())
        .merge(routes::bacnet::split_read_router())
        .merge(routes::telemetry::split_status_router())
        .merge(routes::connector::router())
        .with_state(state)
}

fn delivery_state() -> (DeliveryStatus, DeliveryStatus) {
    // The split hello cannot claim a durable historian receipt merely because
    // a transport is configured. Central receipts remain a later observation.
    let enabled = std::env::var("OPENFDD_MQTT_ENABLED").is_ok_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    });
    if enabled {
        (DeliveryStatus::Checking, DeliveryStatus::Unknown)
    } else {
        (DeliveryStatus::Disabled, DeliveryStatus::Disabled)
    }
}

fn haystack_hello(state: &HaystackState) -> ConnectorHelloResponse {
    let (mqtt, durable) = delivery_state();
    let configured = config::haystack_connector_configured(&state.settings)
        && state.haystack.has_trusted_catalog();
    let (readiness, source_health, detail) = if configured {
        (
            CapabilityState::Checking,
            CapabilityState::Checking,
            "trusted Haystack catalog and explicit credentials are loaded; readiness requires an explicit request probe"
                .to_string(),
        )
    } else {
        (
            CapabilityState::NotConfigured,
            CapabilityState::NotConfigured,
            "Haystack endpoint is not configured".to_string(),
        )
    };
    let connector = ConnectorCapability {
        protocol: ConnectorProtocol::Haystack,
        compiled: true,
        configured,
        enabled: configured,
        readiness,
        source_health,
        mqtt_connection: mqtt,
        durable_delivery: durable,
        supported_actions: vec![ConnectorAction::MetadataRead, ConnectorAction::PointRead],
        detail: Some(detail),
    };
    ConnectorHelloResponse {
        schema: CAPABILITIES_CONTRACT_V1.into(),
        version: ServiceVersion {
            service: state.identity.service.clone(),
            build: state.identity.version.build.clone(),
            contract: CAPABILITIES_CONTRACT_V1.into(),
        },
        compiled_protocols: vec![ConnectorProtocol::Haystack],
        connectors: vec![connector],
        recipe: RecipeObservation {
            declared: None,
            configured_services: vec!["fieldbus".into()],
            observed_services: vec!["fieldbus".into()],
            unobserved_services: vec![],
            reconciliation: "not_declared".into(),
        },
        service_identity: Some(state.identity.clone()),
        observed_at: Utc::now(),
    }
}

async fn haystack_health(State(state): State<HaystackState>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "service": state.identity.service,
        "profile": "haystack",
        "process_id": state.identity.process_id,
        "git_sha": config::git_sha(),
        "udp_sockets": 0,
    }))
}

async fn haystack_api_health(State(state): State<HaystackState>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "service": state.identity.service,
        "profile": "haystack",
        "process_id": state.identity.process_id,
    }))
}

async fn haystack_hello_route(State(state): State<HaystackState>) -> Json<ConnectorHelloResponse> {
    Json(haystack_hello(&state))
}

async fn haystack_catalog(
    State(state): State<HaystackState>,
    Json(request): Json<HaystackCatalogRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackCatalogResponse>> {
    check_haystack_scope(&state, &request.scope)?;
    Ok(Json(
        state
            .haystack
            .catalog_page(&request)
            .map_err(ApiError::BadRequest)?,
    ))
}

async fn haystack_about(
    State(state): State<HaystackState>,
    Json(request): Json<HaystackAboutRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackAboutResponse>> {
    check_haystack_scope(&state, &request.scope)?;
    Ok(Json(
        state
            .haystack
            .about_typed(&request)
            .await
            .map_err(ApiError::Upstream)?,
    ))
}

async fn haystack_read(
    State(state): State<HaystackState>,
    Json(request): Json<HaystackCurrentReadRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackCurrentReadResponse>> {
    check_haystack_scope(&state, &request.scope)?;
    Ok(Json(
        state
            .haystack
            .current_read_typed(&request)
            .await
            .map_err(|error| {
                if error.contains("trusted catalog") || error.contains("public key") {
                    ApiError::Forbidden(error)
                } else {
                    ApiError::Upstream(error)
                }
            })?,
    ))
}

async fn haystack_manual_telemetry(
    State(state): State<HaystackState>,
    Json(request): Json<HaystackCurrentReadRequest>,
) -> ApiResult<Json<Value>> {
    let _operation = state.manual_gate.lock().await;
    request.validate().map_err(ApiError::BadRequest)?;
    check_haystack_scope(&state, &request.scope)?;
    let signature = serde_json::to_string(&request)
        .map_err(|_| ApiError::BadRequest("invalid request".into()))?;
    if let Some((saved_signature, result)) = state
        .manual_results
        .lock()
        .await
        .get(&request.request_id)
        .cloned()
    {
        if saved_signature != signature {
            return Err(ApiError::BadRequest(
                "request_id is already bound to different parameters".into(),
            ));
        }
        return Ok(Json(result));
    }
    let retained = crate::mqtt_bridge::lookup_manual_local(
        &request.scope.edge_id,
        request.request_id,
        &request.scope.building_id,
        &signature,
        &state.manual_spool,
    )
    .await
    .map_err(|error| {
        if error.contains("already bound to different parameters") {
            ApiError::BadRequest(error)
        } else {
            ApiError::Upstream(error)
        }
    })?;
    let envelope = match retained {
        Some(crate::mqtt_bridge::ManualOperationRecord::Completed(record)) => {
            let status = match record.status {
                openfdd_mqtt::SpoolTerminalStatus::Committed => "committed",
                openfdd_mqtt::SpoolTerminalStatus::Terminal => "terminal",
            };
            return Ok(Json(json!({
                "schema": "openfdd.connector.haystack.telemetry.v1",
                "message_id": record.envelope.message_id,
                "sequence": record.envelope.sequence,
                "status": status,
                "reason": record.reason,
                "point_count": record.envelope.points.len(),
                "completed_at": record.completed_at,
            })));
        }
        Some(crate::mqtt_bridge::ManualOperationRecord::Expired(record)) => {
            return Ok(Json(json!({
                "schema": "openfdd.connector.haystack.telemetry.v1",
                "message_id": record.message_id,
                "status": "expired",
                "reason": record.reason,
                "detail": "manual operation identity expired from the bounded completion journal; submit a new request_id",
                "expired_at": record.retired_at,
            })));
        }
        Some(crate::mqtt_bridge::ManualOperationRecord::Pending(record)) => record.envelope,
        None => {
            crate::mqtt_bridge::reserve_manual_local(
                &request.scope.edge_id,
                request.request_id,
                &signature,
                &state.manual_spool,
            )
            .await
            .map_err(|error| {
                if error.contains("already bound to different parameters") {
                    ApiError::BadRequest(error)
                } else {
                    ApiError::Upstream(error)
                }
            })?;
            let response = state
                .haystack
                .current_read_typed(&request)
                .await
                .map_err(ApiError::Upstream)?;
            let sequence = state
                .manual_sequence
                .fetch_add(1, Ordering::Relaxed)
                .saturating_add(1);
            state
                .haystack
                .telemetry_envelope_from_current(&request, &response, sequence)
                .map_err(ApiError::BadRequest)?
        }
    };
    let outcome = crate::mqtt_bridge::send_manual_local(
        &request.scope.building_id,
        &envelope,
        &signature,
        &state.manual_spool,
    )
    .await
    .map_err(|error| {
        if error.contains("already bound to different parameters") {
            ApiError::BadRequest(error)
        } else {
            ApiError::Upstream(error)
        }
    })?;
    let (status, reason) = match outcome {
        crate::mqtt_bridge::LocalDeliveryOutcome::Durable => ("committed", None),
        crate::mqtt_bridge::LocalDeliveryOutcome::Quarantined(reason) => ("terminal", Some(reason)),
        crate::mqtt_bridge::LocalDeliveryOutcome::Pending => ("pending", None),
    };
    let result = json!({
        "schema": "openfdd.connector.haystack.telemetry.v1",
        "message_id": envelope.message_id,
        "sequence": envelope.sequence,
        "status": status,
        "reason": reason,
        "point_count": envelope.points.len(),
        "completed_at": Utc::now(),
    });
    if !matches!(outcome, crate::mqtt_bridge::LocalDeliveryOutcome::Pending) {
        let mut results = state.manual_results.lock().await;
        if results.len() >= 1024 {
            let oldest = results
                .iter()
                .min_by_key(|(_, (_, result))| {
                    result
                        .get("completed_at")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string()
                })
                .map(|(request_id, _)| *request_id);
            if let Some(oldest) = oldest {
                results.remove(&oldest);
            }
        }
        results.insert(request.request_id, (signature, result.clone()));
    }
    Ok(Json(result))
}

async fn haystack_nav(
    State(state): State<HaystackState>,
    Json(request): Json<HaystackNavRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackNavResponse>> {
    check_haystack_scope(&state, &request.scope)?;
    Ok(Json(
        state
            .haystack
            .nav_typed(&request)
            .await
            .map_err(ApiError::Upstream)?,
    ))
}

async fn haystack_his_read(
    State(state): State<HaystackState>,
    Json(request): Json<HaystackHistoryReadRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackHistoryReadResponse>> {
    check_haystack_scope(&state, &request.scope)?;
    Ok(Json(
        state
            .haystack
            .history_read_typed(&request)
            .await
            .map_err(|error| {
                if error.contains("trusted catalog") || error.contains("public key") {
                    ApiError::Forbidden(error)
                } else {
                    ApiError::Upstream(error)
                }
            })?,
    ))
}

/// Build the profile-specific Haystack router. Only the TCP management routes
/// and outbound Haystack operations are present; no BACnet or Modbus router is
/// merged here.
pub fn haystack_router(state: HaystackState) -> Router {
    Router::new()
        .route("/health", get(haystack_health))
        .route("/api/health", get(haystack_api_health))
        .route("/api/connector/hello", get(haystack_hello_route))
        .route("/haystack/catalog", post(haystack_catalog))
        .route("/haystack/about", post(haystack_about))
        .route("/haystack/read", post(haystack_read))
        .route("/haystack/telemetry", post(haystack_manual_telemetry))
        .route("/haystack/nav", post(haystack_nav))
        .route("/haystack/his-read", post(haystack_his_read))
        .route("/api/haystack/catalog", post(haystack_catalog))
        .route("/api/haystack/about", post(haystack_about))
        .route("/api/haystack/read", post(haystack_read))
        .route("/api/haystack/telemetry", post(haystack_manual_telemetry))
        .route("/api/haystack/nav", post(haystack_nav))
        .route("/api/haystack/his-read", post(haystack_his_read))
        .with_state(state)
}

/// Start the BACnet/Modbus split process. It owns the only BACnet socket and
/// all read-only polling/priority history in this process.
pub async fn run_bacnet_modbus() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenvy::dotenv().ok();
    init_tracing("openfdd_bacnet_modbus");
    let identity = identity_for(openfdd_contracts::ConnectorServiceProfile::BacnetModbus)
        .map_err(std::io::Error::other)?;
    let settings = Arc::new(config::load_settings_for(SettingsProfile::BacnetModbus));
    let api_key = configured_api_key();
    let _auth_state =
        app_key_state(&settings.http_host, api_key.clone()).map_err(std::io::Error::other)?;

    let bacnet_server = Arc::new(BacnetServerManager::new((*settings).clone()));
    bacnet_server.start().await.map_err(std::io::Error::other)?;
    let weather = Arc::new(WeatherService::new(
        (*settings).clone(),
        Arc::clone(&bacnet_server),
    ));
    // Weather mirroring remains a legacy compatibility concern. The split
    // BACnet/Modbus process owns fieldbus reads, polling, and the priority
    // scanner without starting an unrelated outbound weather loop.
    let bacnet_client =
        Arc::new(BacnetClientService::new((*settings).clone()).map_err(std::io::Error::other)?);
    let poll_engine = Arc::new(PollEngine::new(
        (*settings).clone(),
        Arc::clone(&bacnet_client),
    ));
    poll_engine.start().await;
    let rest = Arc::new(
        RestClientService::from_config(settings.rest.clone(), Vec::new())
            .map_err(std::io::Error::other)?,
    );
    let telemetry = Arc::new(TelemetryControl::new(
        Arc::clone(&poll_engine),
        Arc::clone(&weather),
        Arc::clone(&rest),
    ));
    telemetry.apply_persisted_on_boot().await;
    let publish_ledger = Arc::new(MqttPublishLedger::default());
    crate::mqtt_bridge::spawn_if_configured(
        Arc::clone(&settings),
        Arc::clone(&poll_engine),
        Arc::clone(&bacnet_client),
        Arc::clone(&rest),
        Arc::clone(&telemetry),
        Arc::clone(&publish_ledger),
    )
    .await;
    let priority_scan = PriorityScanService::from_settings(&settings, Arc::clone(&bacnet_client))
        .map_err(std::io::Error::other)?;
    let priority_scan_task = priority_scan.spawn();
    let state = AppState {
        settings: Arc::clone(&settings),
        api_key,
        bacnet_server,
        bacnet_client,
        poll_engine,
        weather,
        haystack: None,
        rest,
        telemetry,
        priority_scan,
        publish_ledger,
        service_identity: Some(identity),
    };
    let app = bacnet_modbus_router(state.clone()).layer(middleware::from_fn_with_state(
        _auth_state,
        split_auth_middleware,
    ));
    let listener =
        tokio::net::TcpListener::bind(format!("{}:{}", settings.http_host, settings.http_port))
            .await?;
    info!(
        service = "openfdd-bacnet-modbus",
        http = %listener.local_addr()?,
        "split connector started"
    );
    axum::serve(listener, app)
        .with_graceful_shutdown(bacnet_shutdown(
            state.weather.clone(),
            state.poll_engine.clone(),
            state.bacnet_server.clone(),
            priority_scan_task,
        ))
        .await?;
    Ok(())
}

async fn split_auth_middleware(
    State(state): State<AuthState>,
    request: axum::extract::Request,
    next: axum::middleware::Next,
) -> axum::response::Response {
    auth_middleware(State(state), request, next).await
}

async fn bacnet_shutdown(
    weather: Arc<WeatherService>,
    poll_engine: Arc<PollEngine>,
    bacnet_server: Arc<BacnetServerManager>,
    priority_scan_task: Option<JoinHandle<()>>,
) {
    let _ = tokio::signal::ctrl_c().await;
    if let Some(task) = priority_scan_task {
        task.abort();
    }
    poll_engine.stop().await;
    weather.stop().await;
    let _ = bacnet_server.stop().await;
    info!(service = "openfdd-bacnet-modbus", "split connector stopped");
}

/// Start the Haystack process. The function does not construct any BACnet,
/// Modbus, weather, poll, MQTT, or priority scanner service.
pub async fn run_haystack() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenvy::dotenv().ok();
    init_tracing("openfdd_haystack");
    let identity = identity_for(openfdd_contracts::ConnectorServiceProfile::Haystack)
        .map_err(std::io::Error::other)?;
    let settings = Arc::new(config::load_settings_for(SettingsProfile::Haystack));
    let api_key = require_connector_api_key(configured_connector_api_key(), "openfdd-haystack")
        .map_err(std::io::Error::other)?;
    let _auth_state =
        app_key_state(&settings.http_host, Some(api_key.clone())).map_err(std::io::Error::other)?;
    validate_haystack_settings(&settings).map_err(std::io::Error::other)?;
    validate_haystack_ingest_mode().map_err(std::io::Error::other)?;
    let haystack = Arc::new(HaystackService::new(settings.haystack.clone()));
    let state = HaystackState {
        settings: Arc::clone(&settings),
        api_key: Some(api_key),
        haystack,
        identity,
        manual_sequence: Arc::new(AtomicU64::new(0)),
        manual_spool: Arc::new(AsyncMutex::new(None)),
        manual_gate: Arc::new(AsyncMutex::new(())),
        manual_results: Arc::new(AsyncMutex::new(BTreeMap::new())),
    };
    let app = haystack_router(state.clone()).layer(middleware::from_fn_with_state(
        _auth_state,
        split_auth_middleware,
    ));
    let listener =
        tokio::net::TcpListener::bind(format!("{}:{}", settings.http_host, settings.http_port))
            .await?;
    info!(
        service = "openfdd-haystack",
        http = %listener.local_addr()?,
        "split connector started"
    );
    axum::serve(listener, app)
        .with_graceful_shutdown(haystack_shutdown(state.haystack.clone()))
        .await?;
    Ok(())
}

fn validate_haystack_settings(settings: &Settings) -> Result<(), String> {
    if !settings.haystack_configured {
        return Err("openfdd-haystack requires an explicit Haystack endpoint".into());
    }
    validate_haystack_base_url(&settings.haystack.base_url)?;
    if settings.haystack.username.trim().is_empty() || settings.haystack.password.trim().is_empty()
    {
        return Err("openfdd-haystack requires explicit Haystack credentials".into());
    }
    let Some(path) = settings.haystack.catalog_path.as_deref() else {
        return Err("openfdd-haystack requires a trusted catalog path".into());
    };
    config::load_haystack_catalog(Some(path))
        .map(|_| ())
        .map_err(|error| format!("invalid trusted Haystack catalog: {error}"))
}

fn validate_haystack_ingest_mode() -> Result<(), String> {
    validate_haystack_ingest_mode_value(
        &std::env::var("OPENFDD_INGEST_MODE").unwrap_or_else(|_| "local_fieldbus".into()),
    )
}

fn validate_haystack_ingest_mode_value(raw: &str) -> Result<(), String> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "local_fieldbus" => Ok(()),
        "mqtts" | "dual" => Err(
            "openfdd-haystack only permits authenticated local_fieldbus delivery; mqtts and dual are rejected"
                .into(),
        ),
        _ => Err("invalid Haystack ingest mode (expected local_fieldbus)".into()),
    }
}

fn validate_haystack_base_url(raw: &str) -> Result<(), String> {
    let url = url::Url::parse(raw).map_err(|error| format!("invalid Haystack URL: {error}"))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err("Haystack endpoint must use http(s) and include a host".into());
    }
    if url.username() != ""
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Haystack endpoint must not contain credentials, query, or fragment".into());
    }
    Ok(())
}

async fn haystack_shutdown(haystack: Arc<HaystackService>) {
    let _ = tokio::signal::ctrl_c().await;
    haystack.close().await;
    info!(service = "openfdd-haystack", "split connector stopped");
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{HaystackAuthMode, HaystackCatalog, HaystackCatalogEntry, HaystackSettings};
    use axum::body::Body;
    use axum::extract::Query;
    use axum::http::{HeaderMap, Request, StatusCode};
    use axum::response::{IntoResponse, Response};
    use axum::routing::get;
    use axum::{Json, Router};
    use bytes::Bytes;
    use http_body_util::BodyExt;
    use openfdd_contracts::{
        HaystackCurrentReadRequest, LocalIngestReceipt, LocalIngestStatus,
        HAYSTACK_READ_CONTRACT_V1, LOCAL_INGEST_RECEIPT_CONTRACT_V1,
    };
    use std::collections::BTreeMap;
    use std::path::PathBuf;
    use std::sync::Mutex;
    use tokio::net::TcpListener;
    use tower::ServiceExt;

    fn bacnet_state() -> AppState {
        let settings = Settings {
            field_devices_toml: PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../config/fieldbus/field_devices.toml"),
            objects_csv: PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../config/fieldbus/objects.csv"),
            ..Settings::default()
        };
        let settings = Arc::new(settings);
        let bacnet_server = Arc::new(BacnetServerManager::new((*settings).clone()));
        let bacnet_client = Arc::new(BacnetClientService::new((*settings).clone()).unwrap());
        let poll_engine = Arc::new(PollEngine::new((*settings).clone(), bacnet_client.clone()));
        let weather = Arc::new(WeatherService::new(
            (*settings).clone(),
            bacnet_server.clone(),
        ));
        let rest =
            Arc::new(RestClientService::from_config(settings.rest.clone(), Vec::new()).unwrap());
        let telemetry = Arc::new(TelemetryControl::new(
            poll_engine.clone(),
            weather.clone(),
            rest.clone(),
        ));
        let priority_scan = PriorityScanService::for_tests(
            &settings,
            bacnet_client.clone(),
            std::env::temp_dir().join(format!("openfdd-split-test-{}.json", std::process::id())),
        )
        .unwrap();
        let identity = ServiceIdentity::new(
            openfdd_contracts::ConnectorServiceProfile::BacnetModbus,
            "test",
            RecipeKind::EdgeBacnetModbus,
        );
        AppState {
            settings,
            api_key: None,
            bacnet_server,
            bacnet_client,
            poll_engine,
            weather,
            haystack: None,
            rest,
            telemetry,
            priority_scan,
            publish_ledger: Arc::new(MqttPublishLedger::default()),
            service_identity: Some(identity),
        }
    }

    fn haystack_state() -> HaystackState {
        let settings = Settings {
            haystack_configured: false,
            ..Settings::default()
        };
        let identity = ServiceIdentity::new(
            openfdd_contracts::ConnectorServiceProfile::Haystack,
            "test",
            RecipeKind::EdgeHaystack,
        );
        HaystackState {
            settings: Arc::new(settings.clone()),
            api_key: None,
            haystack: Arc::new(HaystackService::new(settings.haystack)),
            identity,
            manual_sequence: Arc::new(AtomicU64::new(0)),
            manual_spool: Arc::new(AsyncMutex::new(None)),
            manual_gate: Arc::new(AsyncMutex::new(())),
            manual_results: Arc::new(AsyncMutex::new(BTreeMap::new())),
        }
    }

    async fn status(router: Router, method: axum::http::Method, uri: &str) -> StatusCode {
        router
            .oneshot(
                Request::builder()
                    .method(method)
                    .uri(uri)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap()
            .status()
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize process environment while exercising the manual sink"
    )]
    async fn manual_haystack_route_builds_envelope_and_uses_authenticated_local_sink() {
        static ENV_LOCK: Mutex<()> = Mutex::new(());
        let _env = ENV_LOCK.lock().unwrap_or_else(|error| error.into_inner());
        let keys = [
            "OPENFDD_LOCAL_CENTRAL_URL",
            "OPENFDD_LOCAL_INGEST_TOKEN",
            "OPENFDD_TENANT_ID",
            "OPENFDD_BUILDING_ID",
        ];
        let saved: Vec<_> = keys
            .iter()
            .map(|key| (*key, std::env::var(key).ok()))
            .collect();
        let restore = || {
            for (key, value) in saved {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        };
        std::env::set_var("OPENFDD_LOCAL_INGEST_TOKEN", "manual-token");
        std::env::set_var("OPENFDD_TENANT_ID", "tenant");
        std::env::set_var("OPENFDD_BUILDING_ID", "building");

        async fn zinc_read(
            headers: HeaderMap,
            Query(query): Query<BTreeMap<String, String>>,
        ) -> Response {
            if headers
                .get("authorization")
                .and_then(|value| value.to_str().ok())
                != Some("Basic dXNlcjpwYXNz")
                || query.get("filter").map(String::as_str) != Some("id == @point-1")
            {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            }
            (
                StatusCode::OK,
                "ver:\"3.0\"\nid,curVal,ts\n@point-1 \"SAT\",72.5°F,2026-10-02T12:00:00-05:00 New_York\n",
            )
                .into_response()
        }

        let upstream_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let upstream_address = upstream_listener.local_addr().unwrap();
        let upstream = tokio::spawn(async move {
            axum::serve(
                upstream_listener,
                Router::new().route("/read", get(zinc_read)),
            )
            .await
            .unwrap();
        });

        let captured = Arc::new(Mutex::new(
            Vec::<openfdd_contracts::TelemetryEnvelope>::new(),
        ));
        async fn central_ingest(
            axum::extract::State(captured): axum::extract::State<
                Arc<Mutex<Vec<openfdd_contracts::TelemetryEnvelope>>>,
            >,
            headers: HeaderMap,
            body: Bytes,
        ) -> Json<LocalIngestReceipt> {
            assert_eq!(
                headers
                    .get("authorization")
                    .and_then(|value| value.to_str().ok()),
                Some("Bearer manual-token")
            );
            let envelope: openfdd_contracts::TelemetryEnvelope =
                serde_json::from_slice(&body).unwrap();
            let message_id = envelope.message_id;
            let points = envelope.points.len();
            let mut captured = captured.lock().unwrap();
            captured.push(envelope.clone());
            let pending = captured.len() == 1;
            Json(LocalIngestReceipt {
                schema: LOCAL_INGEST_RECEIPT_CONTRACT_V1.into(),
                scope: "tenant=tenant;building=building".into(),
                site_id: envelope.site_id,
                edge_id: envelope.edge_id,
                message_id,
                status: if pending {
                    LocalIngestStatus::Pending
                } else {
                    LocalIngestStatus::Committed
                },
                duplicate: false,
                eligible_points: if pending { 0 } else { points },
                persisted_rows: if pending { 0 } else { points },
                error: None,
            })
        }

        let central_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let central_address = central_listener.local_addr().unwrap();
        std::env::set_var(
            "OPENFDD_LOCAL_CENTRAL_URL",
            format!("http://{central_address}"),
        );
        let captured_for_server = Arc::clone(&captured);
        let central = tokio::spawn(async move {
            axum::serve(
                central_listener,
                Router::new()
                    .route("/api/ingest/local", axum::routing::post(central_ingest))
                    .with_state(captured_for_server),
            )
            .await
            .unwrap();
        });

        let settings = HaystackSettings {
            base_url: format!("http://{upstream_address}/"),
            username: "user".into(),
            password: "pass".into(),
            auth_mode: HaystackAuthMode::Basic,
            ..HaystackSettings::default()
        };
        let haystack = HaystackService::with_catalog(
            settings,
            HaystackCatalog {
                revision: "manual-v1".into(),
                entries: vec![HaystackCatalogEntry {
                    public_key: "point-1".into(),
                    kind: openfdd_contracts::HaystackRecordKind::Point,
                    display_name: "SAT".into(),
                    equipment_key: Some("ahu-1".into()),
                    role: Some("sat".into()),
                    unit: Some("°F".into()),
                    source_ref: "point-1".into(),
                    nav_ref: None,
                }],
            },
        );
        let settings = Settings {
            connector_tenant_id: Some("tenant".into()),
            connector_building_id: Some("building".into()),
            connector_edge_id: Some("edge".into()),
            haystack_configured: true,
            ..Settings::default()
        };
        let state = HaystackState {
            settings: Arc::new(settings),
            api_key: Some("management-key".into()),
            haystack: Arc::new(haystack),
            identity: ServiceIdentity::new(
                openfdd_contracts::ConnectorServiceProfile::Haystack,
                "test",
                RecipeKind::EdgeHaystack,
            ),
            manual_sequence: Arc::new(AtomicU64::new(0)),
            manual_spool: Arc::new(AsyncMutex::new(None)),
            manual_gate: Arc::new(AsyncMutex::new(())),
            manual_results: Arc::new(AsyncMutex::new(BTreeMap::new())),
        };
        let request = HaystackCurrentReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: uuid::Uuid::new_v4(),
            scope: ConnectorScope {
                tenant_id: "tenant".into(),
                building_id: "building".into(),
                edge_id: "edge".into(),
            },
            public_keys: vec!["point-1".into()],
        };
        let app = haystack_router(state).layer(middleware::from_fn_with_state(
            AuthState::new(Some("management-key".into())),
            split_auth_middleware,
        ));
        let unauthorized = app
            .clone()
            .oneshot(
                Request::post("/api/haystack/telemetry")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(unauthorized.status(), StatusCode::UNAUTHORIZED);
        let forbidden = app
            .clone()
            .oneshot(
                Request::post("/api/haystack/telemetry")
                    .header("authorization", "Bearer wrong-key")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(forbidden.status(), StatusCode::FORBIDDEN);
        let response = app
            .clone()
            .oneshot(
                Request::post("/api/haystack/telemetry")
                    .header("authorization", "Bearer management-key")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let result: serde_json::Value = serde_json::from_slice(
            &axum::body::to_bytes(response.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(result["status"], "pending");
        assert_eq!(result["message_id"], request.request_id.to_string());
        assert_eq!(result["point_count"], 1);
        let retry = app
            .oneshot(
                Request::post("/api/haystack/telemetry")
                    .header("authorization", "Bearer management-key")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(retry.status(), StatusCode::OK);
        let retry_result: serde_json::Value = serde_json::from_slice(
            &axum::body::to_bytes(retry.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(retry_result["status"], "committed");
        assert_eq!(retry_result["message_id"], result["message_id"]);
        let captured = captured.lock().unwrap();
        assert_eq!(captured.len(), 2);
        assert_eq!(captured[0], captured[1]);
        let envelope = captured[1].clone();
        assert_eq!(envelope.protocol, openfdd_contracts::Protocol::Haystack);
        assert_eq!(envelope.points[0].unit.as_deref(), Some("°F"));
        assert_eq!(
            envelope.points[0].observed_at.unwrap().to_rfc3339(),
            "2026-10-02T17:00:00+00:00"
        );
        central.abort();
        upstream.abort();
        restore();
    }

    #[tokio::test]
    async fn process_route_surfaces_are_disjoint() {
        let bacnet = bacnet_modbus_router(bacnet_state());
        assert_eq!(
            status(bacnet.clone(), axum::http::Method::GET, "/").await,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            status(bacnet.clone(), axum::http::Method::GET, "/haystack/about").await,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            status(bacnet, axum::http::Method::GET, "/bacnet/poll/status").await,
            StatusCode::OK
        );

        let bacnet = bacnet_modbus_router(bacnet_state());
        for (method, uri) in [
            (axum::http::Method::POST, "/bacnet/write"),
            (axum::http::Method::POST, "/bacnet/write-dry-run"),
            (axum::http::Method::POST, "/bacnet/whois"),
            (axum::http::Method::POST, "/bacnet/whois-router"),
            (axum::http::Method::POST, "/bacnet/supervisory"),
            (axum::http::Method::POST, "/bacnet/server/update"),
            (axum::http::Method::POST, "/api/bacnet/read"),
            (axum::http::Method::POST, "/api/bacnet/point-discovery"),
            (axum::http::Method::POST, "/modbus/read"),
            (axum::http::Method::POST, "/telemetry/suspend"),
            (axum::http::Method::POST, "/telemetry/resume"),
            (axum::http::Method::POST, "/weather/refresh"),
        ] {
            assert_eq!(
                status(bacnet.clone(), method.clone(), uri).await,
                StatusCode::NOT_FOUND,
                "split BACnet process must reject {method} {uri}"
            );
        }
        assert_eq!(
            status(bacnet, axum::http::Method::GET, "/api/health").await,
            StatusCode::OK
        );

        let haystack = haystack_router(haystack_state());
        assert_eq!(
            status(haystack.clone(), axum::http::Method::GET, "/").await,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            status(haystack.clone(), axum::http::Method::POST, "/bacnet/whois").await,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            status(haystack.clone(), axum::http::Method::POST, "/modbus/read").await,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            status(haystack, axum::http::Method::GET, "/api/connector/hello").await,
            StatusCode::OK
        );
    }

    #[test]
    fn haystack_process_rejects_non_http_endpoints() {
        assert!(validate_haystack_base_url("udp://127.0.0.1:47808").is_err());
        assert!(validate_haystack_base_url("https://example.test/haystack").is_ok());
    }

    #[test]
    fn haystack_process_requires_endpoint_and_api_key() {
        let settings = Settings::default();
        assert!(validate_haystack_settings(&settings).is_err());
        assert!(require_connector_api_key(None, "openfdd-haystack").is_err());

        let mut configured = settings;
        configured.haystack_configured = true;
        configured.haystack.base_url = "https://example.test/haystack".into();
        assert!(validate_haystack_settings(&configured).is_err());
        assert_eq!(
            require_connector_api_key(Some(" split-test-key ".into()), "openfdd-haystack").unwrap(),
            " split-test-key ".to_string()
        );
    }

    #[test]
    fn haystack_process_rejects_mqtt_delivery_modes() {
        assert!(validate_haystack_ingest_mode_value("mqtts").is_err());
        assert!(validate_haystack_ingest_mode_value("dual").is_err());
        assert!(validate_haystack_ingest_mode_value("local_fieldbus").is_ok());
    }

    #[test]
    fn haystack_scope_is_exactly_bound_before_outbound_calls() {
        let mut state = haystack_state();
        let mut settings = (*state.settings).clone();
        settings.connector_tenant_id = Some("tenant-a".into());
        settings.connector_building_id = Some("building-a".into());
        settings.connector_edge_id = Some("edge-a".into());
        state.settings = Arc::new(settings);
        let scope = ConnectorScope {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
        };
        assert!(check_haystack_scope(&state, &scope).is_ok());
        let mut foreign = scope.clone();
        foreign.edge_id = "edge-b".into();
        assert!(check_haystack_scope(&state, &foreign).is_err());
    }

    #[test]
    fn split_hellos_have_honest_identity_and_modbus_state() {
        let state = bacnet_state();
        let hello = routes::connector::hello_response(&state);
        hello.validate().unwrap();
        assert_eq!(hello.version.service, "openfdd-bacnet-modbus");
        let modbus = hello
            .connectors
            .iter()
            .find(|connector| connector.protocol == ConnectorProtocol::Modbus)
            .unwrap();
        assert_eq!(modbus.readiness, CapabilityState::NotConfigured);
        assert!(!modbus.enabled);
        assert!(modbus
            .detail
            .as_deref()
            .unwrap()
            .contains("inventory contract"));

        let haystack = haystack_hello(&haystack_state());
        haystack.validate().unwrap();
        assert_eq!(haystack.version.service, "openfdd-haystack");
    }

    #[tokio::test]
    async fn haystack_health_does_not_claim_an_ot_socket() {
        let response = haystack_router(haystack_state())
            .oneshot(
                Request::builder()
                    .uri("/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let value: Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(value["udp_sockets"], 0);
    }
}
