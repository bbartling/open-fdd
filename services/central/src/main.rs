//! Open-FDD Central — Normal Framework API (portal HTTPS or LAN gRPC) and CSV ingest, Timescale, REST.

mod actions;
mod actions_scope;
mod admin_cp;
mod admitted_sample;
mod afdd_scheduler;
mod analytics;
#[cfg(test)]
mod analytics_response_fixtures;
#[cfg(test)]
mod analytics_result_cache_fixtures;
mod audit;
mod auth;
mod building_sessions;
mod canonical_state;
mod capabilities;
mod contract;
mod csv_session_scope;
mod csv_site_export;
mod cutover;
mod db_lifecycle;
#[cfg(test)]
mod diagnostic_matrix_api;
mod durable_storage;
mod engineering_bundle;
mod eplus_runner;
mod fdd_registry_persist;
mod fuel;
mod haystack_rdf;
mod historian_limits;
mod ingest;
mod ingest_queue;
mod jobs;
mod lifecycle;
mod live_historian;
mod logging;
mod mapping_revision;
#[cfg(test)]
mod metering_scope_fixtures;
mod model_agent_writes;
mod models;
mod occupancy_calendar;
#[cfg(test)]
mod one_writer_fixtures;
mod openapi;
#[cfg(test)]
mod package_preflight_fixtures;
#[cfg(test)]
mod portal_inventory_fixtures;
mod providers;
#[cfg(test)]
mod rcx_row_fixtures;
mod routes;
#[cfg(test)]
mod rule_catalog_fixtures;
#[cfg(test)]
mod runtime_weekly_fixtures;
#[cfg(test)]
mod sat_pairing_fixtures;
mod series_binding;
mod si_api_response;
mod sql_anomaly;
#[cfg(test)]
mod sql_anomaly_fixtures;
mod sql_pack;
mod starter_seed;
mod state;
#[cfg(test)]
mod t1284_2_ingest_si_test;
mod tenant;
mod tenant_budget;
#[cfg(test)]
mod tenant_switch;
#[cfg(test)]
mod test_ddl;
#[cfg(test)]
mod test_env_lock;
mod timescale_analytics;
mod timescale_historian;
mod timescale_product;
mod user_store;
mod vibe21;
mod wattlab_dump;
mod zone_comfort_units;

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::middleware;
use axum::Router;
use state::AppState;
use tokio::sync::watch;
use tower_http::trace::TraceLayer;
use tracing::{info, warn};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Panic → stderr before any subscriber so Railway crash slices keep a death line.
    logging::install_panic_hook();
    logging::init_tracing("info,openfdd_central=info,security_audit=info");

    durable_storage::assert_authoritative_storage()?;
    db_lifecycle::apply_on_startup().await?;
    timescale_analytics::reconcile_catalogue_on_startup().await?;
    starter_seed::spawn();

    let state = Arc::new(AppState::new());
    // Joinable boot line for ART / Railway log windows around started_at flips (Q1a).
    info!(
        version = %routes::resolve_build_version(),
        started_at = %state.started_at.to_rfc3339(),
        "openfdd-central boot"
    );
    let afdd_runtime = afdd_scheduler::AfddSchedulerRuntime::from_env()?;
    afdd_runtime.validate_scheduled_buildings(&state)?;
    let afdd_task = afdd_scheduler::spawn(Arc::clone(&afdd_runtime));
    match jobs::recover_interrupted_runs() {
        Ok(n) if n > 0 => info!(recovered = n, "marked interrupted RUNNING jobs as FAILED"),
        Ok(_) => {}
        Err(e) => tracing::warn!(?e, "job restart recovery failed"),
    }

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let historian_flush_task =
        ingest::spawn_live_historian_flush_with_shutdown(Arc::clone(&state), shutdown_rx);
    let provider_shutdown = shutdown_tx.subscribe();
    let provider_task =
        providers::spawn_poller_with_shutdown(Arc::clone(&state), provider_shutdown);
    let session_evictor = tokio::spawn(async {
        loop {
            tokio::time::sleep(Duration::from_secs(15)).await;
            building_sessions::evict_idle();
        }
    });

    let app = Router::new()
        .merge(routes::router(Arc::clone(&state)))
        .merge(afdd_scheduler::router(
            Arc::clone(&state),
            Arc::clone(&afdd_runtime),
        ))
        .merge(sql_anomaly::router(Arc::clone(&state)))
        .merge(cutover::router())
        .merge(vibe21::router(Arc::clone(&state)))
        .merge(openapi::router())
        .layer(middleware::from_fn(contract::request_id_middleware))
        .layer(TraceLayer::new_for_http());

    let host = std::env::var("OPENFDD_CENTRAL_HOST").unwrap_or_else(|_| "0.0.0.0".into());
    let port: u16 = std::env::var("OPENFDD_CENTRAL_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8080);
    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    crate::auth::assert_bind_auth_policy(
        &host,
        state.auth.secret.as_deref(),
        state.auth.admin_password.as_deref(),
    )
    .map_err(|e| anyhow::anyhow!(e))?;
    info!(
        %addr,
        version = %routes::resolve_build_version(),
        started_at = %state.started_at.to_rfc3339(),
        auth_enabled = state.auth.required(),
        "openfdd-central listening (secrets not logged)"
    );
    let listener = tokio::net::TcpListener::bind(addr).await?;
    let signal_tx = shutdown_tx.clone();
    let (shutdown_signal_tx, shutdown_signal_rx) = tokio::sync::oneshot::channel();
    let server = axum::serve(listener, app).with_graceful_shutdown(async move {
        let signal = wait_for_shutdown_signal().await;
        let _ = shutdown_signal_tx.send(signal);
        let _ = signal_tx.send(true);
    });

    let server_result = server.await;
    let _ = shutdown_tx.send(true);
    if let Some(task) = afdd_task {
        task.abort();
    }
    session_evictor.abort();
    if let Err(error) = historian_flush_task.await {
        warn!(%error, "historian flush task ended unexpectedly during shutdown");
    }
    if let Err(error) = provider_task.await {
        warn!(%error, "provider poller task ended unexpectedly during shutdown");
    }
    let signal = shutdown_signal_rx.await.unwrap_or("shutdown");
    let audit_report =
        open_fdd_edge_prototype::auth::audit::shutdown_for_signal(signal, Duration::from_secs(5));
    if audit_report.timed_out {
        warn!(
            signal = audit_report.signal,
            "audit sink drain timed out before the process exited"
        );
    }
    server_result?;
    Ok(())
}

async fn wait_for_shutdown_signal() -> &'static str {
    #[cfg(unix)]
    {
        use tokio::signal::unix::{signal, SignalKind};
        let mut terminate = match signal(SignalKind::terminate()) {
            Ok(terminate) => terminate,
            Err(error) => {
                warn!(%error, "SIGTERM handler was not installed");
                if let Err(error) = tokio::signal::ctrl_c().await {
                    warn!(%error, "failed to install graceful shutdown signal handler");
                }
                return "SIGINT";
            }
        };
        tokio::select! {
            result = tokio::signal::ctrl_c() => {
                if let Err(error) = result {
                    warn!(%error, "failed to install graceful shutdown signal handler");
                }
                "SIGINT"
            }
            _ = terminate.recv() => "SIGTERM",
        }
    }
    #[cfg(not(unix))]
    {
        if let Err(error) = tokio::signal::ctrl_c().await {
            warn!(%error, "failed to install graceful shutdown signal handler");
        }
        "SIGINT"
    }
}
