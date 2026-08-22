//! Open-FDD Central — MQTTS ingest + REST/OpenAPI control plane.

mod actions;
mod afdd_scheduler;
mod analytics;
mod auth;
mod canonical_state;
mod contract;
mod cutover;
mod eplus_runner;
mod fuel;
mod ingest;
mod jobs;
mod live_historian;
mod models;
mod mqtt_monitor;
mod openapi;
mod routes;
mod state;
mod vibe21;
mod wattlab_dump;

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::middleware;
use axum::Router;
use state::AppState;
use tokio::sync::watch;
use tower_http::trace::TraceLayer;
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info,openfdd_central=info")),
        )
        .init();

    initialize_s3_scope_index().await?;

    let state = Arc::new(AppState::new());
    let afdd_runtime = afdd_scheduler::AfddSchedulerRuntime::from_env()?;
    let afdd_task = afdd_scheduler::spawn(Arc::clone(&afdd_runtime));
    match jobs::recover_interrupted_runs() {
        Ok(n) if n > 0 => info!(recovered = n, "marked interrupted RUNNING jobs as FAILED"),
        Ok(_) => {}
        Err(e) => tracing::warn!(?e, "job restart recovery failed"),
    }

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let ingest_task = ingest::spawn_mqtt_ingest_with_shutdown(Arc::clone(&state), shutdown_rx);

    let app = Router::new()
        .merge(routes::router(Arc::clone(&state)))
        .merge(afdd_scheduler::router(
            Arc::clone(&state),
            Arc::clone(&afdd_runtime),
        ))
        .merge(mqtt_monitor::router(Arc::clone(&state)))
        .merge(cutover::router())
        .merge(vibe21::router())
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
        auth_enabled = state.auth.required(),
        "openfdd-central listening (secrets not logged)"
    );
    let listener = tokio::net::TcpListener::bind(addr).await?;
    let signal_tx = shutdown_tx.clone();
    let server = axum::serve(listener, app).with_graceful_shutdown(async move {
        if let Err(error) = tokio::signal::ctrl_c().await {
            warn!(%error, "failed to install graceful shutdown signal handler");
        }
        let _ = signal_tx.send(true);
    });

    let server_result = server.await;
    let _ = shutdown_tx.send(true);
    if let Some(task) = afdd_task {
        task.abort();
    }
    if let Err(error) = ingest_task.await {
        warn!(%error, "MQTT ingest task ended unexpectedly during shutdown");
    }
    server_result?;
    Ok(())
}

async fn initialize_s3_scope_index() -> anyhow::Result<()> {
    let Some(buildings) = fdd_sql::refresh_s3_scope_index_from_env().await? else {
        return Ok(());
    };
    info!(
        buildings,
        "refreshed S3 historian building scope index (scratch metadata only)"
    );

    let refresh_seconds = std::env::var("OPENFDD_S3_SCOPE_REFRESH_SECONDS")
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .filter(|seconds| *seconds > 0)
        .unwrap_or(60);
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(refresh_seconds));
        interval.tick().await;
        loop {
            interval.tick().await;
            match fdd_sql::refresh_s3_scope_index_from_env().await {
                Ok(Some(buildings)) => {
                    tracing::debug!(buildings, "refreshed S3 historian building scope index")
                }
                Ok(None) => break,
                Err(error) => tracing::warn!(
                    %error,
                    "S3 historian building scope refresh failed; retaining last index"
                ),
            }
        }
    });
    Ok(())
}
