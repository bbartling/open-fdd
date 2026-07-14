//! Open-FDD fieldbus — pure Rust axum entrypoint + MQTTS publisher.

mod auth;
mod config;
mod error;
mod models;
mod mqtt_bridge;
mod openapi;
mod openapi_bench;
mod openapi_paths;
mod routes;
mod services;
mod state;

use std::sync::Arc;

use axum::middleware;
use config::load_settings;
use services::{
    bacnet_client::BacnetClientService, bacnet_server::BacnetServerManager,
    haystack::HaystackService, poll::PollEngine, weather::WeatherService,
};
use state::AppState;
use tower_http::trace::TraceLayer;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info,openfdd_fieldbus=info")),
        )
        .init();

    let settings = Arc::new(load_settings());
    run(settings).await
}

async fn run(
    settings: Arc<config::Settings>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let bacnet_server = Arc::new(BacnetServerManager::new((*settings).clone()));
    bacnet_server.start().await.map_err(std::io::Error::other)?;

    let weather = Arc::new(WeatherService::new(
        (*settings).clone(),
        Arc::clone(&bacnet_server),
    ));
    weather.start().await.map_err(std::io::Error::other)?;

    let bacnet_client =
        Arc::new(BacnetClientService::new((*settings).clone()).map_err(std::io::Error::other)?);
    let poll_engine = Arc::new(PollEngine::new(
        (*settings).clone(),
        Arc::clone(&bacnet_client),
    ));
    poll_engine.start().await;

    let haystack = Arc::new(HaystackService::new(settings.haystack.clone()));

    mqtt_bridge::spawn_if_configured(
        Arc::clone(&settings),
        Arc::clone(&poll_engine),
        Arc::clone(&bacnet_client),
    )
    .await;

    let api_key = auth::api_key();
    let api_key_opt = if api_key.is_empty() {
        None
    } else {
        info!("API key auth enabled");
        Some(api_key)
    };

    let state = AppState {
        settings: Arc::clone(&settings),
        api_key: api_key_opt,
        bacnet_server,
        bacnet_client,
        poll_engine,
        weather,
        haystack,
    };

    info!(
        "openfdd-fieldbus started (HTTP {}:{})",
        settings.http_host, settings.http_port
    );

    let mut app = routes::api_routes(state.clone());
    if settings.openapi_enabled {
        app = app.merge(routes::openapi_routes(state.clone()));
    }
    app = app
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth::auth_middleware,
        ))
        .layer(TraceLayer::new_for_http());

    let listener =
        tokio::net::TcpListener::bind(format!("{}:{}", settings.http_host, settings.http_port))
            .await?;

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal(
            state.weather.clone(),
            state.poll_engine.clone(),
            state.bacnet_server.clone(),
            state.haystack.clone(),
        ))
        .await?;

    Ok(())
}

async fn shutdown_signal(
    weather: Arc<WeatherService>,
    poll_engine: Arc<PollEngine>,
    bacnet_server: Arc<BacnetServerManager>,
    haystack: Arc<HaystackService>,
) {
    let _ = tokio::signal::ctrl_c().await;
    info!("Shutting down...");
    haystack.close().await;
    poll_engine.stop().await;
    weather.stop().await;
    let _ = bacnet_server.stop().await;
    info!("openfdd-fieldbus stopped");
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use super::*;
    use crate::routes;

    fn test_state() -> AppState {
        std::env::set_var(
            "OPENFDD_FIELDBUS_CONFIG_DIR",
            format!("{}/../../config/fieldbus", env!("CARGO_MANIFEST_DIR")),
        );
        let settings = Arc::new(load_settings());
        let bacnet_server = Arc::new(BacnetServerManager::new((*settings).clone()));
        let bacnet_client = Arc::new(BacnetClientService::new((*settings).clone()).unwrap());
        let poll_engine = Arc::new(PollEngine::new(
            (*settings).clone(),
            Arc::clone(&bacnet_client),
        ));
        let weather = Arc::new(WeatherService::new(
            (*settings).clone(),
            Arc::clone(&bacnet_server),
        ));
        let haystack = Arc::new(HaystackService::new(settings.haystack.clone()));
        AppState {
            settings,
            api_key: None,
            bacnet_server,
            bacnet_client,
            poll_engine,
            weather,
            haystack,
        }
    }

    #[tokio::test]
    async fn health_endpoint_ok() {
        let app = routes::api_routes(test_state());
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(v["ok"], true);
    }

    #[tokio::test]
    async fn root_lists_service_metadata() {
        let app = routes::api_routes(test_state());
        let response = app
            .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }
}
