//! Read-only MQTT observation API + operator edge-kit download (H9 / AWS-style kits).

use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::{Extension, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware;
use axum::routing::{get, post};
use axum::{Json, Router};
use openfdd_mqtt::{provision_edge_kit_zip, ProvisionRequest};
use serde::Deserialize;
use serde_json::{json, Value};
use tempfile::TempDir;

use crate::auth::{self, AuthUser};
use crate::state::{AppState, MqttMonitorSnapshot};

pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/mqtt/monitor", get(snapshot))
        .route("/api/mqtt/edge-kits", post(create_edge_kit))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ))
        .with_state(state)
}

async fn snapshot(State(state): State<Arc<AppState>>) -> Json<MqttMonitorSnapshot> {
    Json(state.mqtt_monitor_snapshot())
}

#[derive(Debug, Deserialize)]
pub struct CreateEdgeKitRequest {
    pub site_id: String,
    pub edge_id: String,
    #[serde(default)]
    pub broker_host: Option<String>,
    #[serde(default)]
    pub broker_port: Option<u16>,
}

fn mqtt_ca_dir() -> PathBuf {
    if let Ok(path) = std::env::var("OPENFDD_MQTT_CA_DIR") {
        let trimmed = path.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| ".".into());
    PathBuf::from(workspace).join("deploy/mqtt/ca")
}

fn default_broker_host() -> String {
    std::env::var("OPENFDD_MQTT_HOST").unwrap_or_else(|_| "127.0.0.1".into())
}

fn default_broker_port() -> u16 {
    std::env::var("OPENFDD_MQTT_PORT")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .unwrap_or(8883)
}

async fn create_edge_kit(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    Json(body): Json<CreateEdgeKitRequest>,
) -> Result<(StatusCode, HeaderMap, Vec<u8>), (StatusCode, Json<Value>)> {
    if state.auth.required() && !user.role.can_issue_commands() {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "operator or admin role required to download edge kits"
            })),
        ));
    }

    let site_id = body.site_id.trim().to_string();
    let edge_id = body.edge_id.trim().to_string();
    if site_id.is_empty() || edge_id.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "site_id and edge_id are required"})),
        ));
    }
    if site_id.contains('/')
        || site_id.contains("..")
        || edge_id.contains('/')
        || edge_id.contains("..")
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "site_id/edge_id must be path-safe tokens"})),
        ));
    }

    let broker_host = body
        .broker_host
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .unwrap_or_else(default_broker_host);
    let broker_port = body.broker_port.unwrap_or_else(default_broker_port);
    let ca_dir = mqtt_ca_dir();

    let result = tokio::task::spawn_blocking(move || {
        let tmp = TempDir::new().map_err(|e| format!("temp dir: {e}"))?;
        // Keep CA under a stable sibling of kits when present; otherwise provision
        // will create ca/ under out_dir (tmp) and also reuse OPENFDD_MQTT_CA_DIR.
        let out_dir = tmp.path().to_path_buf();
        let ca_override = if ca_dir.join("ca.key.pem").is_file() || ca_dir.join("ca.pem").is_file() {
            Some(ca_dir)
        } else {
            None
        };
        let (filename, bytes) = provision_edge_kit_zip(&ProvisionRequest {
            out_dir: out_dir.clone(),
            site_id,
            edge_id,
            broker_host,
            broker_port,
            ca_dir: ca_override,
        })
        .map_err(|e| e.to_string())?;
        // Keep tmp alive until zip bytes are fully owned.
        drop(tmp);
        Ok::<_, String>((filename, bytes))
    })
    .await
    .map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": format!("edge kit task failed: {e}")})),
        )
    })?;

    let (filename, bytes) = result.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;

    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, "application/zip".parse().unwrap());
    let disposition = format!("attachment; filename=\"{filename}\"");
    headers.insert(
        header::CONTENT_DISPOSITION,
        disposition.parse().map_err(|_| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": "invalid edge kit filename"})),
            )
        })?,
    );
    Ok((StatusCode::OK, headers, bytes))
}
