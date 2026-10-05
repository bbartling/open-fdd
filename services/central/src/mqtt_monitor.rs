//! Read-only MQTT observation API + operator edge-kit download (H9 / AWS-style kits).
//! Wave M M1: JWT SSE at GET /api/mqtt/monitor/stream (EventSource-friendly query token).

use axum::extract::{Extension, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware;
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures_util::stream::{self, Stream};
use openfdd_mqtt::{provision_edge_kit_zip, ProvisionRequest};
use serde::Deserialize;
use serde_json::{json, Value};
use std::convert::Infallible;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tempfile::TempDir;

use crate::auth::{self, AuthUser};
use crate::state::{AppState, MqttMonitorSnapshot};
use crate::tenant::{ControlPlane, TenantContext};

#[derive(Debug, Deserialize, Default)]
struct StreamAuthQuery {
    /// EventSource cannot set Authorization; accept short-lived JWT here only.
    #[serde(default)]
    access_token: Option<String>,
}

pub fn router(state: Arc<AppState>) -> Router {
    let authed = Router::new()
        .route("/api/mqtt/monitor", get(snapshot))
        .route("/api/mqtt/edge-kits", post(create_edge_kit))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ));

    Router::new()
        .route("/api/mqtt/monitor/stream", get(monitor_stream))
        .merge(authed)
        .with_state(state)
}

async fn snapshot(State(state): State<Arc<AppState>>) -> Json<MqttMonitorSnapshot> {
    Json(state.mqtt_monitor_snapshot())
}

fn authorize_monitor(
    state: &AppState,
    headers: &HeaderMap,
    query: &StreamAuthQuery,
) -> Result<AuthUser, (StatusCode, Json<Value>)> {
    if let Ok(user) = state.auth.user_from_headers(headers) {
        return Ok(user);
    }
    if let Some(token) = query
        .access_token
        .as_deref()
        .map(str::trim)
        .filter(|t| !t.is_empty())
    {
        return state.auth.verify_bearer(token).map_err(|detail| {
            (
                StatusCode::UNAUTHORIZED,
                Json(json!({"ok": false, "error": detail})),
            )
        });
    }
    Err((
        StatusCode::UNAUTHORIZED,
        Json(json!({
            "ok": false,
            "error": "Authorization: Bearer <token> or access_token query required"
        })),
    ))
}

async fn monitor_stream(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<StreamAuthQuery>,
) -> Result<Sse<impl Stream<Item = Result<Event, Infallible>>>, (StatusCode, Json<Value>)> {
    let _user = authorize_monitor(&state, &headers, &query)?;
    let stream = stream::unfold((state, true), |(state, first)| async move {
        if !first {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        let snap = state.mqtt_monitor_snapshot();
        let data = serde_json::to_string(&snap).unwrap_or_else(|_| "{}".into());
        let event = Event::default().event("mqtt").data(data);
        Some((Ok::<_, Infallible>(event), (state, false)))
    });
    Ok(Sse::new(stream).keep_alive(
        KeepAlive::new()
            .interval(Duration::from_secs(15))
            .text("ping"),
    ))
}

#[derive(Debug, Deserialize)]
pub struct CreateEdgeKitRequest {
    pub site_id: String,
    pub edge_id: String,
    #[serde(default)]
    pub broker_host: Option<String>,
    #[serde(default)]
    pub broker_port: Option<u16>,
    /// Wave N: when set, kit ACL/topics use `tenants/{tid}/buildings/{site}/…`.
    #[serde(default)]
    pub tenant_id: Option<String>,
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

/// Path-safe MQTT identity token (no wildcards / separators / newlines).
fn kit_identity_token_ok(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && !value.contains("..")
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.')
}

fn resolve_kit_scope(
    state: &AppState,
    user: &AuthUser,
    site_id: &str,
    edge_id: &str,
    requested_tenant: Option<&str>,
) -> Result<(String, String, Option<String>), (StatusCode, Json<Value>)> {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    let ctx = TenantContext::resolve_fail_closed(user, &plane);

    if !ctx.allow_building(site_id) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "site_id is outside the authenticated tenant scope"
            })),
        ));
    }

    let authorized = state.capabilities.authorized_edge_ids(&ctx);
    if !authorized.contains(edge_id) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "edge_id is not a trusted configured edge for this principal"
            })),
        ));
    }

    let Some((configured_tenant, configured_building)) =
        state.capabilities.configured_scope(edge_id)
    else {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "edge_id has no trusted connector configuration"
            })),
        ));
    };

    if configured_building != site_id {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "site_id does not match the trusted edge building"
            })),
        ));
    }

    if let Some(requested) = requested_tenant {
        if requested != configured_tenant {
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "tenant_id does not match the trusted edge tenant"
                })),
            ));
        }
    }

    // Always mint from server-derived scope — never trust caller tenant as authority.
    Ok((
        site_id.to_string(),
        edge_id.to_string(),
        Some(configured_tenant.to_string()),
    ))
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
    if !kit_identity_token_ok(&site_id) || !kit_identity_token_ok(&edge_id) {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "site_id/edge_id must be path-safe non-wildcard tokens"
            })),
        ));
    }
    let requested_tenant = body
        .tenant_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if let Some(tenant) = requested_tenant {
        if !kit_identity_token_ok(tenant) {
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({"ok": false, "error": "tenant_id must be a path-safe token"})),
            ));
        }
    }

    let (site_id, edge_id, tenant_id) =
        resolve_kit_scope(&state, &user, &site_id, &edge_id, requested_tenant)?;

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
        let ca_override = if ca_dir.join("ca.key.pem").is_file() || ca_dir.join("ca.pem").is_file()
        {
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
            tenant_id,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::{AuthConfig, AuthUser, Role};
    use crate::capabilities::{CapabilitiesAggregator, ConfiguredUpstream};
    use crate::state::AppState;
    use url::Url;

    fn state_with_edges() -> Arc<AppState> {
        let mut state = AppState::new();
        state.auth = AuthConfig {
            secret: Some("edge-kit-s04-test-secret-32chars!!".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        state.capabilities = CapabilitiesAggregator::for_tests(vec![
            ConfiguredUpstream {
                tenant_id: "legacy".into(),
                building_id: "site-a".into(),
                edge_id: "edge-a".into(),
                base_url: Url::parse("http://127.0.0.1:9/").unwrap(),
                token: None,
            },
            ConfiguredUpstream {
                tenant_id: "legacy".into(),
                building_id: "site-b".into(),
                edge_id: "edge-b".into(),
                base_url: Url::parse("http://127.0.0.1:9/").unwrap(),
                token: None,
            },
        ]);
        Arc::new(state)
    }

    #[test]
    fn kit_tokens_reject_wildcards_and_separators() {
        assert!(kit_identity_token_ok("edge-a"));
        assert!(!kit_identity_token_ok("edge/*"));
        assert!(!kit_identity_token_ok("a/b"));
        assert!(!kit_identity_token_ok("..\nedge"));
        assert!(!kit_identity_token_ok(""));
    }

    #[test]
    fn edge_kit_scope_denies_foreign_configured_edge() {
        let _lock = crate::test_env_lock::lock_env();
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        let state = state_with_edges();
        let user = AuthUser {
            sub: "ops".into(),
            role: Role::Operator,
            tenant_ids: vec![],
        };
        let err = resolve_kit_scope(&state, &user, "site-a", "edge-b", None).unwrap_err();
        assert_eq!(err.0, StatusCode::FORBIDDEN);
        let ok = resolve_kit_scope(&state, &user, "site-a", "edge-a", None).unwrap();
        assert_eq!(ok.0, "site-a");
        assert_eq!(ok.1, "edge-a");
        assert_eq!(ok.2.as_deref(), Some("legacy"));
    }

    #[test]
    fn edge_kit_scope_rejects_conflicting_caller_tenant() {
        let _lock = crate::test_env_lock::lock_env();
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        let state = state_with_edges();
        let user = AuthUser {
            sub: "ops".into(),
            role: Role::Operator,
            tenant_ids: vec![],
        };
        let err =
            resolve_kit_scope(&state, &user, "site-a", "edge-a", Some("foreign-tenant")).unwrap_err();
        assert_eq!(err.0, StatusCode::FORBIDDEN);
    }
}
