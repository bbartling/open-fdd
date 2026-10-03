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
    haystack::HaystackService, mqtt_publish_ledger::MqttPublishLedger, poll::PollEngine,
    rest::RestClientService, telemetry_control::TelemetryControl, weather::WeatherService,
};
use state::AppState;
use tower_http::trace::TraceLayer;
use tracing::info;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,openfdd_fieldbus=info,security_audit=info"));
    let json = matches!(
        std::env::var("OPENFDD_LOG_FORMAT")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "json" | "jsonl" | "structured"
    );
    if json {
        tracing_subscriber::registry()
            .with(filter)
            .with(
                fmt::layer()
                    .json()
                    .with_current_span(true)
                    .with_span_list(false),
            )
            .init();
    } else {
        tracing_subscriber::registry()
            .with(filter)
            .with(fmt::layer())
            .init();
    }
}

fn is_loopback_http_host(host: &str) -> bool {
    matches!(
        host.trim().to_ascii_lowercase().as_str(),
        "127.0.0.1" | "localhost" | "::1"
    )
}

/// Fail-closed: non-loopback management bind requires OPENFDD_FIELDBUS_API_KEY.
fn require_api_key_for_bind(
    http_host: &str,
    api_key: String,
) -> Result<Option<String>, Box<dyn std::error::Error + Send + Sync>> {
    if api_key.is_empty() {
        if !is_loopback_http_host(http_host) {
            tracing::error!(
                target: "security_audit",
                event = "fieldbus_auth_open_bind_refused",
                http_host = %http_host,
                "refusing non-loopback management bind without OPENFDD_FIELDBUS_API_KEY"
            );
            return Err(format!(
                "OPENFDD_FIELDBUS_API_KEY required when HTTP bind is not loopback (host={http_host})"
            )
            .into());
        }
        tracing::warn!(
            target: "security_audit",
            event = "fieldbus_auth_open_loopback",
            "API key unset — management open on loopback only"
        );
        return Ok(None);
    }
    info!("API key auth enabled");
    Ok(Some(api_key))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenvy::dotenv().ok();
    init_tracing();

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

    // REST/JSON driver (#540): startup fails loudly when an enabled device
    // references a missing secret env var.
    let rest_devices =
        config::load_rest_devices(None, &settings.rest).map_err(std::io::Error::other)?;
    let rest = Arc::new(
        RestClientService::from_config(settings.rest.clone(), rest_devices)
            .map_err(std::io::Error::other)?,
    );
    rest.start().await;

    let telemetry = Arc::new(TelemetryControl::new(
        Arc::clone(&poll_engine),
        Arc::clone(&weather),
        Arc::clone(&rest),
    ));
    telemetry.apply_persisted_on_boot().await;

    let publish_ledger = Arc::new(MqttPublishLedger::default());
    mqtt_bridge::spawn_if_configured(
        Arc::clone(&settings),
        Arc::clone(&poll_engine),
        Arc::clone(&bacnet_client),
        Arc::clone(&rest),
        Arc::clone(&telemetry),
        Arc::clone(&publish_ledger),
    )
    .await;

    let api_key_opt = require_api_key_for_bind(&settings.http_host, auth::api_key())?;

    let state = AppState {
        settings: Arc::clone(&settings),
        api_key: api_key_opt,
        bacnet_server,
        bacnet_client,
        poll_engine,
        weather,
        haystack,
        rest,
        telemetry,
        publish_ledger,
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
            state.rest.clone(),
        ))
        .await?;

    Ok(())
}

async fn shutdown_signal(
    weather: Arc<WeatherService>,
    poll_engine: Arc<PollEngine>,
    bacnet_server: Arc<BacnetServerManager>,
    haystack: Arc<HaystackService>,
    rest: Arc<RestClientService>,
) {
    let _ = tokio::signal::ctrl_c().await;
    info!("Shutting down...");
    haystack.close().await;
    rest.stop().await;
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
    use std::net::Ipv4Addr;
    use std::time::{SystemTime, UNIX_EPOCH};
    use tokio::net::UdpSocket;
    use tokio::time::{timeout, Duration};
    use tower::ServiceExt;

    use super::*;
    use crate::routes;

    fn state_for_settings(raw_settings: config::Settings) -> AppState {
        let settings = Arc::new(raw_settings);
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
        let rest_devices = config::load_rest_devices(None, &settings.rest).unwrap();
        let rest =
            Arc::new(RestClientService::from_config(settings.rest.clone(), rest_devices).unwrap());
        let telemetry = Arc::new(TelemetryControl::new(
            Arc::clone(&poll_engine),
            Arc::clone(&weather),
            Arc::clone(&rest),
        ));
        AppState {
            settings,
            api_key: None,
            bacnet_server,
            bacnet_client,
            poll_engine,
            weather,
            haystack,
            rest,
            telemetry,
            publish_ledger: Arc::new(MqttPublishLedger::default()),
        }
    }

    fn test_state() -> AppState {
        std::env::set_var(
            "OPENFDD_FIELDBUS_CONFIG_DIR",
            format!("{}/../../config/fieldbus", env!("CARGO_MANIFEST_DIR")),
        );
        state_for_settings(load_settings())
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
    async fn publish_ledger_route_reports_acks() {
        let state = test_state();
        state
            .publish_ledger
            .record_ack(4, 2, &["RTU_01".to_string()]);
        let app = routes::api_routes(state);
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/mqtt/publish-ledger")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(v["publish_acks"], 1);
        assert_eq!(v["recent"][0]["equipment_ids"][0], "RTU_01");
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

    #[tokio::test]
    async fn bacnet_write_approval_gate_keeps_omitted_and_false_requests_off_wire() {
        let receiver = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
            .await
            .expect("bind approval-gate receiver");
        let port = receiver.local_addr().expect("receiver address").port();
        let path = std::env::temp_dir().join(format!(
            "openfdd-bacnet-approval-test-{}-{}.toml",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("system clock after epoch")
                .as_nanos()
        ));
        std::fs::write(
            &path,
            format!(
                "[[devices]]\nname = \"approval-gate-test\"\nenabled = true\ndevice_instance = 5010\nhost = \"127.0.0.1\"\nport = {port}\npoints = []\n"
            ),
        )
        .expect("write approval-gate catalog");

        let mut settings = config::Settings {
            field_devices_toml: path.clone(),
            ..config::Settings::default()
        };
        settings.bacnet_client.interface = Ipv4Addr::LOCALHOST;
        settings.bacnet_client.broadcast = Ipv4Addr::LOCALHOST;
        settings.bacnet_client.read_bind_port = 0;
        settings.bacnet_client.whois_bind_port = 0;
        let app = routes::api_routes(state_for_settings(settings));

        let base = serde_json::json!({
            "device_instance": 5010,
            "object_type": "analog-value",
            "object_instance": 7,
            "property_id": "present-value",
            "value": 0.0,
            "priority": 8,
            "value_type": "real"
        });
        for approved in [None, Some(false)] {
            let mut body = base.clone();
            if let Some(approved) = approved {
                body["approved"] = serde_json::json!(approved);
            }
            let response = app
                .clone()
                .oneshot(
                    Request::post("/bacnet/write")
                        .header("content-type", "application/json")
                        .body(Body::from(body.to_string()))
                        .expect("build write request"),
                )
                .await
                .expect("approval-gate response");
            assert_eq!(response.status(), StatusCode::OK);
            let result: serde_json::Value =
                serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes())
                    .expect("decode dry-run response");
            assert_eq!(result["ok"], true);
            assert_eq!(result["outcome"], "dry_run");
            assert_eq!(result["skipped"], "not approved");
            let mut datagram = [0u8; 2048];
            assert!(
                timeout(Duration::from_millis(30), receiver.recv_from(&mut datagram))
                    .await
                    .is_err(),
                "omitted/false approval must not send a BACnet datagram"
            );
        }

        for body in [
            serde_json::json!({
                "device_instance": 5010,
                "object_type": "analog-value",
                "object_instance": 7,
                "property_id": "present-value",
                "value": i64::MAX,
                "value_type": "signed",
                "approved": true,
            }),
            serde_json::json!({
                "device_instance": 5010,
                "object_type": "analog-value",
                "object_instance": 7,
                "property_id": "present-value",
                "value": null,
                "approved": true,
            }),
        ] {
            let response = app
                .clone()
                .oneshot(
                    Request::post("/bacnet/write")
                        .header("content-type", "application/json")
                        .body(Body::from(body.to_string()))
                        .expect("build invalid write request"),
                )
                .await
                .expect("invalid-write response");
            assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
            let mut datagram = [0u8; 2048];
            assert!(
                timeout(Duration::from_millis(30), receiver.recv_from(&mut datagram))
                    .await
                    .is_err(),
                "invalid numeric/NULL writes must fail before any BACnet datagram"
            );
        }
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn loopback_hosts_recognized() {
        assert!(is_loopback_http_host("127.0.0.1"));
        assert!(is_loopback_http_host("LOCALHOST"));
        assert!(is_loopback_http_host("::1"));
        assert!(!is_loopback_http_host("0.0.0.0"));
        assert!(!is_loopback_http_host("192.168.1.10"));
    }

    #[test]
    fn non_loopback_without_key_refused() {
        let err = require_api_key_for_bind("0.0.0.0", String::new()).unwrap_err();
        assert!(err.to_string().contains("OPENFDD_FIELDBUS_API_KEY"));
    }

    #[test]
    fn loopback_without_key_allowed() {
        assert!(require_api_key_for_bind("127.0.0.1", String::new())
            .unwrap()
            .is_none());
    }

    #[test]
    fn key_present_allows_any_bind() {
        let key = require_api_key_for_bind("0.0.0.0", "test-key".into())
            .unwrap()
            .expect("key");
        assert_eq!(key, "test-key");
    }
}
