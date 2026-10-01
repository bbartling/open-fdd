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
        let rest_config_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../config/fieldbus/rest_devices.toml");
        let rest_devices =
            config::load_rest_devices(Some(&rest_config_path), &settings.rest).unwrap();
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
        let mut settings = load_settings();
        settings.field_devices_toml = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../config/fieldbus/field_devices.toml");
        settings.connector_tenant_id = None;
        settings.connector_building_id = None;
        settings.connector_edge_id = None;
        state_for_settings(settings)
    }

    fn test_state_for_scope(tenant: &str, building: &str, edge: &str) -> AppState {
        let mut settings = load_settings();
        settings.field_devices_toml = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../config/fieldbus/field_devices.toml");
        settings.connector_tenant_id = Some(tenant.into());
        settings.connector_building_id = Some(building.into());
        settings.connector_edge_id = Some(edge.into());
        state_for_settings(settings)
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
    async fn connector_hello_is_versioned_and_side_effect_free() {
        let state = test_state();
        let app = routes::api_routes(state.clone());
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/connector/hello")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(value["schema"], openfdd_contracts::CAPABILITIES_CONTRACT_V1);
        assert_eq!(value["version"]["service"], "openfdd-fieldbus");
        assert!(value["connectors"].is_array());
        // No handler in this route reaches BacnetClientService; this request
        // has no OT target and therefore cannot initiate discovery or a read.
        assert!(value["connectors"]
            .as_array()
            .unwrap()
            .iter()
            .all(|connector| connector["protocol"] != "write"));
        assert_eq!(state.bacnet_client.test_ot_call_count(), 0);
    }

    #[tokio::test]
    async fn connector_inventory_is_bounded_scoped_and_broker_free() {
        let state = test_state_for_scope("tenant-local", "building-local", "edge-local");
        let client = state.bacnet_client.clone();
        let app = routes::api_routes(state);
        let request = serde_json::json!({
            "schema": openfdd_contracts::CONNECTOR_INVENTORY_CONTRACT_V1,
            "request_id": uuid::Uuid::nil(),
            "scope": {
                "tenant_id": "tenant-local",
                "building_id": "building-local",
                "edge_id": "edge-local"
            },
            "protocols": ["bacnet"],
            "page_size": 2
        });
        let response = app
            .clone()
            .oneshot(
                Request::post("/api/connector/inventory")
                    .header("content-type", "application/json")
                    .body(Body::from(request.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(
            value["schema"],
            openfdd_contracts::CONNECTOR_INVENTORY_CONTRACT_V1
        );
        assert_eq!(value["provenance"], "trusted_configuration");
        assert_eq!(value["records"].as_array().unwrap().len(), 2);
        assert!(value["next_cursor"].as_str().is_some());
        let serialized = value.to_string();
        assert!(!serialized.contains("127.0.0.1"));
        assert!(!serialized.contains("47808"));
        assert_eq!(client.test_ot_call_count(), 0);

        let mut cursor = value["next_cursor"].clone();
        let mut all_records = value["records"].as_array().unwrap().clone();
        while let Some(cursor_value) = cursor.as_str() {
            let mut page_request = request.clone();
            page_request["cursor"] = serde_json::json!(cursor_value);
            let page_response = app
                .clone()
                .oneshot(
                    Request::post("/api/connector/inventory")
                        .header("content-type", "application/json")
                        .body(Body::from(page_request.to_string()))
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(page_response.status(), StatusCode::OK);
            let page_body = page_response
                .into_body()
                .collect()
                .await
                .unwrap()
                .to_bytes();
            let page: serde_json::Value = serde_json::from_slice(&page_body).unwrap();
            assert_eq!(page["revision"], value["revision"]);
            assert!(page["records"].as_array().unwrap().len() <= 2);
            all_records.extend(page["records"].as_array().unwrap().iter().cloned());
            cursor = page["next_cursor"].clone();
        }
        assert!(all_records.iter().any(|record| record["kind"] == "point"));
        assert_eq!(client.test_ot_call_count(), 0);

        let mut foreign_request = request.clone();
        foreign_request["scope"]["tenant_id"] = serde_json::json!("foreign-tenant");
        let foreign_response = app
            .clone()
            .oneshot(
                Request::post("/api/connector/inventory")
                    .header("content-type", "application/json")
                    .body(Body::from(foreign_request.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(foreign_response.status(), StatusCode::FORBIDDEN);

        let mut invalid_page = request;
        invalid_page["page_size"] = serde_json::json!(101);
        let invalid_response = app
            .oneshot(
                Request::post("/api/connector/inventory")
                    .header("content-type", "application/json")
                    .body(Body::from(invalid_page.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(invalid_response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(client.test_ot_call_count(), 0);
    }

    #[tokio::test]
    async fn connector_read_rejects_untrusted_scope_before_ot_access() {
        let state = test_state();
        let app = routes::api_routes(state.clone());
        let request = serde_json::json!({
            "schema": openfdd_contracts::READ_PROXY_CONTRACT_V1,
            "request_id": uuid::Uuid::nil(),
            "scope": {
                "tenant_id": "configured-tenant",
                "building_id": "other-building",
                "edge_id": "configured-edge"
            },
            "target": {
                "kind": "bacnet_point",
                "device_instance": 5007,
                "object_type": "analog-value",
                "object_instance": 1,
                "property_id": "present-value"
            }
        });
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/connector/read")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        assert_eq!(state.bacnet_client.test_ot_call_count(), 0);
    }

    #[tokio::test]
    async fn connector_scope_identity_matrix_counts_only_authorized_ot_reads() {
        // Missing local identity fails before inventory lookup or a BACnet
        // client operation.
        let missing_state = test_state();
        let missing_client = missing_state.bacnet_client.clone();
        let missing_response = routes::api_routes(missing_state)
            .oneshot(
                Request::post("/api/connector/read")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        serde_json::json!({
                            "schema": openfdd_contracts::READ_PROXY_CONTRACT_V1,
                            "request_id": uuid::Uuid::nil(),
                            "scope": {"tenant_id":"tenant-a","building_id":"building-a","edge_id":"edge-a"},
                            "target": {"kind":"bacnet_point","device_instance":599999,"object_type":"analog-value","object_instance":9101,"property_id":"present-value"}
                        })
                        .to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(missing_response.status(), StatusCode::FORBIDDEN);
        assert_eq!(missing_client.test_ot_call_count(), 0);

        // A foreign tenant is rejected even when the building and edge names
        // are otherwise plausible.
        let foreign_state = test_state_for_scope("tenant-a", "building-a", "edge-a");
        let foreign_client = foreign_state.bacnet_client.clone();
        let foreign_response = routes::api_routes(foreign_state)
            .oneshot(
                Request::post("/api/connector/read")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        serde_json::json!({
                            "schema": openfdd_contracts::READ_PROXY_CONTRACT_V1,
                            "request_id": uuid::Uuid::nil(),
                            "scope": {"tenant_id":"tenant-b","building_id":"building-a","edge_id":"edge-a"},
                            "target": {"kind":"bacnet_point","device_instance":599999,"object_type":"analog-value","object_instance":9101,"property_id":"present-value"}
                        })
                        .to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(foreign_response.status(), StatusCode::FORBIDDEN);
        assert_eq!(foreign_client.test_ot_call_count(), 0);

        // A correctly scoped, inventory-listed point is the only matrix entry
        // allowed to enter the BACnet client.  The loopback target is a read
        // fixture; no live equipment is contacted by this test.
        let receiver = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await.unwrap();
        let port = receiver.local_addr().unwrap().port();
        let path = std::env::temp_dir().join(format!(
            "openfdd-connector-scope-{}-{}.toml",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::write(
            &path,
            format!(
                "[[devices]]\nname=\"connector-scope-test\"\nenabled=true\ndevice_instance=599999\nhost=\"127.0.0.1\"\nport={port}\npoints=[{{object_type=\"analog-value\",object_instance=9101,point_name=\"zone-air-temp\",units=\"F\"}}]\n"
            ),
        )
        .unwrap();
        let mut settings = config::Settings {
            field_devices_toml: path.clone(),
            connector_tenant_id: Some("tenant-a".into()),
            connector_building_id: Some("building-a".into()),
            connector_edge_id: Some("edge-a".into()),
            ..config::Settings::default()
        };
        settings.bacnet_client.interface = Ipv4Addr::LOCALHOST;
        settings.bacnet_client.broadcast = Ipv4Addr::LOCALHOST;
        settings.bacnet_client.apdu_timeout_ms = 20;
        let authorized_state = state_for_settings(settings);
        let authorized_client = authorized_state.bacnet_client.clone();
        let authorized_request = Request::post("/api/connector/read")
            .header("content-type", "application/json")
            .body(Body::from(
                serde_json::json!({
                    "schema": openfdd_contracts::READ_PROXY_CONTRACT_V1,
                    "request_id": uuid::Uuid::nil(),
                    "scope": {"tenant_id":"tenant-a","building_id":"building-a","edge_id":"edge-a"},
                    "target": {"kind":"bacnet_point","device_instance":599999,"object_type":"analog-value","object_instance":9101,"property_id":"present-value"}
                })
                .to_string(),
            ))
            .unwrap();
        let authorized_response = timeout(
            Duration::from_secs(3),
            routes::api_routes(authorized_state).oneshot(authorized_request),
        )
        .await
        .expect("authorized connector read should be bounded")
        .unwrap();
        assert_eq!(authorized_client.test_ot_call_count(), 1);
        assert!(matches!(
            authorized_response.status(),
            StatusCode::BAD_GATEWAY | StatusCode::INTERNAL_SERVER_ERROR
        ));
        let _ = std::fs::remove_file(path);
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
