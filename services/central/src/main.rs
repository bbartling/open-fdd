//! Open-FDD Central — MQTTS ingest + REST/OpenAPI control plane.

mod auth;
mod ingest;
mod models;
mod openapi;
mod routes;
mod state;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::Router;
use state::AppState;
use tower_http::trace::TraceLayer;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info,openfdd_central=info")),
        )
        .init();

    let state = Arc::new(AppState::new());
    ingest::spawn_mqtt_ingest(Arc::clone(&state));

    let app = Router::new()
        .merge(routes::router(Arc::clone(&state)))
        .merge(openapi::router())
        .layer(TraceLayer::new_for_http());

    let host = std::env::var("OPENFDD_CENTRAL_HOST").unwrap_or_else(|_| "0.0.0.0".into());
    let port: u16 = std::env::var("OPENFDD_CENTRAL_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8080);
    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    info!(%addr, "openfdd-central listening");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
