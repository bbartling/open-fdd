//! Agent write path for the building model and historian purge.
//!
//! The operator UI never edits the building model. AI agents do, through
//! JWT REST (and `openfdd-mcp`). Every write here needs an operator or admin
//! token, a building in the caller's tenant scope, and `confirm: true` unless
//! the request is a `dry_run`. Each non-dry-run attempt is audited.
//!
//! Model writes forward to the existing handlers in `routes`, which keep their
//! own validation, CAS, and tenant checks.

use std::future::Future;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use fdd_tsdb::{PurgeTarget, Tsdb};
use open_fdd_edge_prototype::auth::audit::log_event;
use serde::de::DeserializeOwned;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::audit::{AuditAction, AuditChange, AuditEvent, ReasonCode};
use crate::auth::{AuthUser, Role};
use crate::routes;
use crate::state::AppState;

type ApiResult = Result<Json<Value>, (StatusCode, Json<Value>)>;

fn reject(status: StatusCode, error: &str) -> (StatusCode, Json<Value>) {
    (status, Json(json!({ "ok": false, "error": error })))
}

fn role_name(role: Role) -> &'static str {
    match role {
        Role::Viewer => "viewer",
        Role::Operator => "operator",
        Role::Admin => "admin",
    }
}

fn body_building_id(body: &Value) -> Option<String> {
    ["building_id", "site_id"]
        .iter()
        .filter_map(|k| body.get(*k).and_then(Value::as_str))
        .map(str::trim)
        .find(|s| !s.is_empty())
        .map(str::to_string)
}

/// Exact building ids only: no pattern characters reach a query.
fn valid_building_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}

fn authenticate(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<AuthUser, (StatusCode, Json<Value>)> {
    state
        .auth
        .user_from_headers(headers)
        .map_err(|_| reject(StatusCode::UNAUTHORIZED, "authentication required"))
}

fn deny_out_of_scope(
    user: &AuthUser,
    tool: &str,
    building_id: Option<&str>,
) -> Result<(), (StatusCode, Json<Value>)> {
    if !crate::tenant::multi_tenant_enabled() {
        return Ok(());
    }
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    let ctx = crate::tenant::TenantContext::resolve_fail_closed(user, &plane);
    match building_id {
        Some(b) if ctx.allow_building(b) => Ok(()),
        _ => {
            audit_model_denied(user, tool, building_id, ReasonCode::SiteScope);
            Err(reject(
                StatusCode::FORBIDDEN,
                "building not in tenant scope",
            ))
        }
    }
}

/// Caller allowed to write, and whether the request is a dry run.
struct WriteGate {
    user: AuthUser,
    building_id: Option<String>,
    dry_run: bool,
}

fn gate(
    state: &AppState,
    headers: &HeaderMap,
    body: &mut Value,
    tool: &str,
) -> Result<WriteGate, (StatusCode, Json<Value>)> {
    let user = authenticate(state, headers)?;
    let building_id = body_building_id(body);
    if !user.role.can_issue_commands() {
        audit_model_denied(
            &user,
            tool,
            building_id.as_deref(),
            ReasonCode::RoleRequired,
        );
        return Err(reject(
            StatusCode::FORBIDDEN,
            "operator or admin role required for model writes",
        ));
    }
    deny_out_of_scope(&user, tool, building_id.as_deref())?;
    let dry_run = body
        .get("dry_run")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let confirmed = body.get("confirm").and_then(Value::as_bool) == Some(true);
    if !dry_run && !confirmed {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "confirm_required",
                "detail": "send \"confirm\": true to apply this write, or \"dry_run\": true to validate",
            })),
        ));
    }
    if let Some(obj) = body.as_object_mut() {
        obj.remove("confirm");
    }
    Ok(WriteGate {
        user,
        building_id,
        dry_run,
    })
}

fn audit_model_denied(user: &AuthUser, tool: &str, building_id: Option<&str>, reason: ReasonCode) {
    let mut audit = AuditEvent::new(AuditAction::ModelWrite);
    audit
        .user(user)
        .change(AuditChange::ModelWrite {
            tool: tool.to_string(),
        })
        .deny(reason)
        .status(StatusCode::FORBIDDEN);
    if let Some(building_id) = building_id {
        audit.target_site(building_id);
    }
    audit.emit();
}

/// Typed `model.write` record for an applied or rejected semantic-meta / model write.
fn audit_model(tool: &str, gate: &WriteGate, status: StatusCode, response: &Value) {
    if gate.dry_run {
        return;
    }
    let mut audit = AuditEvent::new(AuditAction::ModelWrite);
    audit.user(&gate.user).change(AuditChange::ModelWrite {
        tool: tool.to_string(),
    });
    if let Some(building_id) = gate.building_id.as_deref() {
        audit.target_site(building_id);
    }
    if status == StatusCode::CONFLICT {
        audit.reason(ReasonCode::RevisionConflict);
    }
    let result = if status.is_success() {
        Ok(Json(response.clone()))
    } else {
        Err((status, Json(response.clone())))
    };
    audit.finish(&result).emit();
}

fn audit_historian(
    event: &str,
    tool: &str,
    gate: &WriteGate,
    status: StatusCode,
    response: &Value,
) {
    if gate.dry_run {
        return;
    }
    log_event(
        event,
        json!({
            "tool": tool,
            "sub": gate.user.sub,
            "role": role_name(gate.user.role),
            "active_tenant_id": gate.user.active_tenant_id,
            "building_id": gate.building_id,
            "status": status.as_u16(),
            "ok": status.is_success() && response.get("ok").and_then(Value::as_bool) != Some(false),
            "revision": response.get("revision").cloned().unwrap_or(Value::Null),
        }),
    );
}

async fn forward<B, F, Fut>(
    state: Arc<AppState>,
    headers: HeaderMap,
    mut body: Value,
    tool: &'static str,
    handler: F,
) -> ApiResult
where
    B: DeserializeOwned,
    F: FnOnce(State<Arc<AppState>>, HeaderMap, Json<B>) -> Fut,
    Fut: Future<Output = ApiResult>,
{
    let gate = gate(&state, &headers, &mut body, tool)?;
    let parsed: B = serde_json::from_value(body).map_err(|e| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({ "ok": false, "error": format!("invalid body: {e}") })),
        )
    })?;
    let result = handler(State(state), headers, Json(parsed)).await;
    match &result {
        Ok(Json(value)) => audit_model(tool, &gate, StatusCode::OK, value),
        Err((status, Json(value))) => audit_model(tool, &gate, *status, value),
    }
    result
}

pub async fn semantic_meta_put(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "model.semantic_meta.put",
        routes::model_semantic_meta_put,
    )
    .await
}

pub async fn overlay_put(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "model.overlay.put",
        routes::model_overlay_put,
    )
    .await
}

pub async fn equip_post(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "model.equip.upsert",
        routes::model_equip_post,
    )
    .await
}

pub async fn equip_delete(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "model.equip.delete",
        routes::model_equip_delete,
    )
    .await
}

pub async fn point_post(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "model.point.upsert",
        routes::model_point_post,
    )
    .await
}

pub async fn point_delete(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "model.point.delete",
        routes::model_point_delete,
    )
    .await
}

pub async fn package_roles_post(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    forward(
        state,
        headers,
        body,
        "csv.import.package.roles",
        routes::csv_import_package_roles,
    )
    .await
}

/// `building_id` (or `site_id`) and `confirm` are read by the write gate.
#[derive(Debug, Deserialize)]
pub struct HistorianPurgeBody {
    /// Purge every series of this equipment (exact id).
    #[serde(default)]
    pub equipment_id: Option<String>,
    /// Purge one series.
    #[serde(default)]
    pub openfdd_key: Option<String>,
}

async fn historian() -> Result<Arc<Tsdb>, (StatusCode, Json<Value>)> {
    if !crate::timescale_historian::historian_is_timescale() {
        return Err(reject(
            StatusCode::CONFLICT,
            "historian purge needs the Timescale historian",
        ));
    }
    Tsdb::shared().await.map_err(|e| {
        tracing::warn!(error = %e, "historian unavailable");
        reject(StatusCode::SERVICE_UNAVAILABLE, "historian unavailable")
    })
}

/// Delete `sample` and `point_map` rows for one equipment or one point.
/// The RDF model is not edited: the portal inventory owns it.
pub async fn historian_purge(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    let mut raw = body;
    let tool = "historian.purge";
    let gate = gate(&state, &headers, &mut raw, tool)?;
    let body: HistorianPurgeBody = serde_json::from_value(raw).map_err(|e| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({ "ok": false, "error": format!("invalid body: {e}") })),
        )
    })?;
    if gate.dry_run {
        return Err(reject(
            StatusCode::BAD_REQUEST,
            "dry_run is not supported for purge",
        ));
    }
    let Some(building_id) = gate.building_id.clone().filter(|b| valid_building_id(b)) else {
        return Err(reject(
            StatusCode::BAD_REQUEST,
            "valid building_id required",
        ));
    };
    let equipment = body
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let key = body
        .openfdd_key
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let target = match (equipment, key) {
        (Some(e), None) => PurgeTarget::Equipment(e),
        (None, Some(k)) => PurgeTarget::Point(k),
        _ => {
            return Err(reject(
                StatusCode::BAD_REQUEST,
                "send exactly one of equipment_id or openfdd_key",
            ))
        }
    };
    let tsdb = match historian().await {
        Ok(tsdb) => tsdb,
        Err((status, Json(value))) => {
            audit_historian("historian_purge", tool, &gate, status, &value);
            return Err((status, Json(value)));
        }
    };
    match tsdb.purge_historian(&building_id, target).await {
        Ok(report) => {
            if report.samples_deleted > 0 || report.point_map_deleted > 0 {
                open_fdd_edge_prototype::fdd::registry_api::mark_building_results_dirty(
                    &building_id,
                    "historian_purge",
                );
            }
            let value = json!({
                "ok": true,
                "building_id": building_id,
                "equipment_id": equipment,
                "openfdd_key": key,
                "purge": report,
            });
            log_event(
                "historian_purge",
                json!({
                    "tool": tool,
                    "sub": gate.user.sub,
                    "role": role_name(gate.user.role),
                    "active_tenant_id": gate.user.active_tenant_id,
                    "building_id": building_id,
                    "equipment_id": equipment,
                    "openfdd_key": key,
                    "keys": report.keys,
                    "samples_deleted": report.samples_deleted,
                    "point_map_deleted": report.point_map_deleted,
                    "status": 200,
                    "ok": true,
                }),
            );
            Ok(Json(value))
        }
        Err(e) => {
            tracing::warn!(%building_id, error = %e, "historian purge failed");
            let value = json!({ "ok": false, "error": "historian purge failed" });
            audit_historian(
                "historian_purge",
                tool,
                &gate,
                StatusCode::INTERNAL_SERVER_ERROR,
                &value,
            );
            Err((StatusCode::INTERNAL_SERVER_ERROR, Json(value)))
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct HistorianSiteQuery {
    #[serde(default)]
    pub building_id: Option<String>,
    #[serde(default)]
    pub site_id: Option<String>,
}

fn read_scope(
    state: &AppState,
    headers: &HeaderMap,
    query: &HistorianSiteQuery,
    tool: &str,
) -> Result<String, (StatusCode, Json<Value>)> {
    let user = authenticate(state, headers)?;
    let building_id = query
        .building_id
        .as_deref()
        .or(query.site_id.as_deref())
        .map(str::trim)
        .filter(|b| valid_building_id(b))
        .map(str::to_string)
        .ok_or_else(|| reject(StatusCode::BAD_REQUEST, "valid building_id required"))?;
    deny_out_of_scope(&user, tool, Some(&building_id))?;
    Ok(building_id)
}

/// Historian points no longer referenced by the model that still hold samples.
pub async fn historian_orphans(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<HistorianSiteQuery>,
) -> ApiResult {
    let building_id = read_scope(&state, &headers, &query, "historian.orphans")?;
    if !crate::timescale_historian::historian_is_timescale() {
        return Ok(Json(json!({
            "ok": true,
            "building_id": building_id,
            "historian": "none",
            "orphaned_points": 0,
            "equipment": [],
            "points": [],
        })));
    }
    let tsdb = historian().await?;
    let points = tsdb.orphaned_points(&building_id).await.map_err(|e| {
        tracing::warn!(%building_id, error = %e, "orphaned points query failed");
        reject(
            StatusCode::INTERNAL_SERVER_ERROR,
            "orphaned points query failed",
        )
    })?;
    let mut equipment: Vec<String> = points
        .iter()
        .filter_map(|p| p.equipment_id.clone())
        .collect();
    equipment.sort();
    equipment.dedup();
    Ok(Json(json!({
        "ok": true,
        "building_id": building_id,
        "historian": "timescale",
        "orphaned_points": points.len(),
        "equipment": equipment,
        "points": points,
    })))
}

/// Read-only device tree source: every series the historian maps for a site.
pub async fn historian_points(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<HistorianSiteQuery>,
) -> ApiResult {
    let building_id = read_scope(&state, &headers, &query, "historian.points")?;
    if !crate::timescale_historian::historian_is_timescale() {
        return Ok(Json(json!({
            "ok": true,
            "building_id": building_id,
            "historian": "none",
            "points": [],
        })));
    }
    let tsdb = historian().await?;
    let points = tsdb.historian_points(&building_id).await.map_err(|e| {
        tracing::warn!(%building_id, error = %e, "historian points query failed");
        reject(
            StatusCode::INTERNAL_SERVER_ERROR,
            "historian points query failed",
        )
    })?;
    Ok(Json(json!({
        "ok": true,
        "building_id": building_id,
        "historian": "timescale",
        "points": points,
    })))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use crate::auth::{AuthConfig, Role};
    use crate::state::AppState;

    struct EnvGuard {
        key: &'static str,
        prev: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let prev = std::env::var(key).ok();
            std::env::set_var(key, value);
            Self { key, prev }
        }

        fn unset(key: &'static str) -> Self {
            let prev = std::env::var(key).ok();
            std::env::remove_var(key);
            Self { key, prev }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match self.prev.take() {
                Some(v) => std::env::set_var(self.key, v),
                None => std::env::remove_var(self.key),
            }
        }
    }

    fn app_state(secret: &str) -> Arc<AppState> {
        let mut state = AppState::new();
        state.auth = AuthConfig {
            secret: Some(secret.into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        Arc::new(state)
    }

    fn token(state: &AppState, name: &str, role: Role) -> String {
        state
            .auth
            .issue_token_with_tenants(name, role, 60, &[])
            .expect("token")
    }

    async fn call(
        app: &axum::Router,
        method: &str,
        uri: &str,
        bearer: &str,
        body: Option<Value>,
    ) -> (StatusCode, Value) {
        let mut req = Request::builder()
            .method(method)
            .uri(uri)
            .header("authorization", format!("Bearer {bearer}"));
        let body = match body {
            Some(b) => {
                req = req.header("content-type", "application/json");
                Body::from(b.to_string())
            }
            None => Body::empty(),
        };
        let resp = app
            .clone()
            .oneshot(req.body(body).expect("request"))
            .await
            .expect("response");
        let status = resp.status();
        let bytes = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .expect("body");
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(Value::Null),
        )
    }

    fn audit_events(workspace: &std::path::Path, event: &str) -> Vec<Value> {
        let path = workspace.join("logs").join("security_audit.jsonl");
        std::fs::read_to_string(path)
            .unwrap_or_default()
            .lines()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .filter(|v| v["event"] == event)
            .collect()
    }

    fn app_with_request_ids(state: Arc<AppState>) -> axum::Router {
        crate::routes::router(state).layer(axum::middleware::from_fn(
            crate::contract::request_id_middleware,
        ))
    }

    async fn call_tracked(
        app: &axum::Router,
        bearer: &str,
        body: Value,
        qa_label: Option<&str>,
    ) -> (StatusCode, Value, String) {
        let mut req = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("authorization", format!("Bearer {bearer}"))
            .header("content-type", "application/json")
            .header("x-request-id", "client-label");
        if let Some(label) = qa_label {
            req = req.header("x-openfdd-qa-run", label);
        }
        let resp = app
            .clone()
            .oneshot(req.body(Body::from(body.to_string())).expect("request"))
            .await
            .expect("response");
        let status = resp.status();
        let server = resp
            .headers()
            .get(crate::contract::SERVER_REQUEST_ID_HEADER)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_string();
        let bytes = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .expect("body");
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(Value::Null),
            server,
        )
    }

    fn semantic_meta(building_id: &str) -> Value {
        json!({
            "schema": "openfdd_point_metadata_v1_sketch",
            "building_id": building_id,
            "points": [{
                "equipment_id": "AHU_1",
                "column": "SAT",
                "haystack_tags": ["sensor", "point", "air", "temp"],
                "unit": "°F",
                "unit_source": "package_map"
            }],
            "equipment": [{
                "equipment_id": "AHU_1",
                "haystack_tags": ["ahu", "equip"],
                "display_name": "AHU 1"
            }]
        })
    }

    fn write_qa_manifest(dir: &std::path::Path, run_id: &str) -> std::path::PathBuf {
        let path = dir.join("qa-run.json");
        std::fs::write(
            &path,
            json!({
                "run_id": run_id,
                "tenants": ["w3a-a"],
                "sites": ["W3A_META", "W3A_OWN"],
                "tool_version": "tool-w3a",
                "candidate": "sha-w3a",
                "window_start": "2020-01-01T00:00:00Z",
                "window_end": "2099-01-01T00:00:00Z"
            })
            .to_string(),
        )
        .expect("qa manifest");
        path
    }

    fn detail_for<'a>(events: &'a [Value], request_id: &str) -> &'a Value {
        &events
            .iter()
            .find(|event| event["detail"]["request_id"] == request_id)
            .unwrap_or_else(|| panic!("missing audit event {request_id}: {events:?}"))["detail"]
    }

    fn writes(bid: &str) -> Vec<(&'static str, &'static str, Value)> {
        vec![
            (
                "PUT",
                "/api/model/semantic-meta",
                json!({"building_id": bid, "meta": {"building_id": bid, "points": []}}),
            ),
            (
                "PUT",
                "/api/model/overlay",
                json!({"building_id": bid, "ttl": "@prefix ofdd: <urn:openfdd:ns#> ."}),
            ),
            (
                "POST",
                "/api/model/equip",
                json!({"building_id": bid, "equipment_id": "AHU_1", "kind": "ahu"}),
            ),
            (
                "DELETE",
                "/api/model/equip",
                json!({"building_id": bid, "equipment_id": "AHU_1"}),
            ),
            (
                "POST",
                "/api/model/point",
                json!({"building_id": bid, "equipment_id": "AHU_1", "point_id": "SAT", "role": "sat"}),
            ),
            (
                "DELETE",
                "/api/model/point",
                json!({"building_id": bid, "point_id": "SAT"}),
            ),
            (
                "POST",
                "/api/csv/import/package/roles",
                json!({"building_id": bid, "equipment_id": "AHU_1", "roles": {"sat": "sat"}}),
            ),
            (
                "POST",
                "/api/historian/purge",
                json!({"building_id": bid, "equipment_id": "AHU_1"}),
            ),
        ]
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE and the audit log path"
    )]
    async fn model_writes_need_operator_and_confirm_and_are_audited() {
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _audit = EnvGuard::unset("OPENFDD_AUDIT_LOG_PATH");
        let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
        let state = app_state("model-agent-writes-test-secret");
        let app = crate::routes::router(Arc::clone(&state));
        let bid = "W7N_AGENT_WRITES";
        let viewer = token(&state, "viewer-w7n", Role::Viewer);
        let operator = token(&state, "agent-w7n", Role::Operator);

        for (method, uri, body) in writes(bid) {
            let mut confirmed = body.clone();
            confirmed["confirm"] = json!(true);
            let (status, json) = call(&app, method, uri, &viewer, Some(confirmed)).await;
            assert_eq!(status, StatusCode::FORBIDDEN, "{method} {uri}: {json}");
            let (status, json) = call(&app, method, uri, &operator, Some(body)).await;
            assert_eq!(status, StatusCode::BAD_REQUEST, "{method} {uri}: {json}");
            assert_eq!(json["error"], "confirm_required", "{method} {uri}");
        }
        assert!(
            !workspace
                .path()
                .join("data/csv_buildings")
                .join(bid)
                .join("model_overlay.ttl")
                .exists(),
            "a denied write reached the model"
        );
        open_fdd_edge_prototype::auth::audit::flush_sink();
        let denies = audit_events(workspace.path(), "model.write");
        assert_eq!(denies.len(), 8, "every viewer write attempt is audited");
        assert!(
            denies
                .iter()
                .all(|event| event["detail"]["decision"] == "deny"
                    && event["detail"]["reason"] == "role_required"
                    && event["detail"]["schema"] == "openfdd.audit.v1"),
            "{denies:?}"
        );

        let (status, json) = call(
            &app,
            "POST",
            "/api/model/equip",
            &operator,
            Some(json!({
                "building_id": bid,
                "equipment_id": "AHU_1",
                "kind": "ahu",
                "expected_revision": 0,
                "confirm": true
            })),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{json}");
        assert_eq!(json["ok"], true, "{json}");
        let (status, json) = call(
            &app,
            "POST",
            "/api/model/equip",
            &operator,
            Some(json!({
                "building_id": bid,
                "equipment_id": "VAV_9",
                "kind": "vav",
                "dry_run": true
            })),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "dry run needs no confirm: {json}");

        open_fdd_edge_prototype::auth::audit::flush_sink();
        let events = audit_events(workspace.path(), "model.write");
        let applied: Vec<&Value> = events
            .iter()
            .filter(|event| event["detail"]["outcome"] == "ok")
            .collect();
        assert_eq!(
            applied.len(),
            1,
            "only the applied write is audited: {events:?}"
        );
        let detail = &applied[0]["detail"];
        assert_eq!(detail["schema"], "openfdd.audit.v1");
        assert_eq!(detail["action"], "model.write");
        assert_eq!(detail["change"]["kind"], "model_write");
        assert_eq!(detail["change"]["tool"], "model.equip.upsert");
        assert_eq!(detail["actor"], "agent-w7n");
        assert_eq!(detail["role"], "operator");
        assert_eq!(detail["site_id"], bid);
        assert_eq!(detail["decision"], "allow");
        assert_eq!(detail["outcome"], "ok");

        let (status, tools) = call(&app, "GET", "/api/agent/tools", &viewer, None).await;
        assert_eq!(status, StatusCode::OK);
        let names: Vec<&str> = tools["tools"]
            .as_array()
            .expect("tools")
            .iter()
            .filter_map(|t| t["name"].as_str())
            .collect();
        for name in [
            "model.semantic_meta.put",
            "model.overlay.put",
            "model.equip.upsert",
            "model.equip.delete",
            "model.point.upsert",
            "model.point.delete",
            "csv.import.package.roles",
            "historian.orphans",
            "historian.purge",
        ] {
            assert!(names.contains(&name), "missing agent tool {name}");
        }
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE and the QA manifest for semantic-meta audit"
    )]
    async fn semantic_meta_permitted_write_and_cas_conflict_share_the_server_request_id() {
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _audit = EnvGuard::unset("OPENFDD_AUDIT_LOG_PATH");
        let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
        let manifest = write_qa_manifest(workspace.path(), "server-run-w3a");
        let _qa = EnvGuard::set(
            "OPENFDD_QA_RUN_MANIFEST",
            manifest.to_str().expect("manifest path"),
        );
        let state = app_state("semantic-meta-audit-secret");
        let app = app_with_request_ids(Arc::clone(&state));
        let bid = "W3A_META";
        let meta = semantic_meta(bid);
        let operator = token(&state, "w3a-operator", Role::Operator);

        let (status, dry, dry_id) = call_tracked(
            &app,
            &operator,
            json!({"building_id": bid, "meta": meta, "dry_run": true}),
            Some("client-approved"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{dry}");
        assert!(!dry_id.is_empty());
        open_fdd_edge_prototype::auth::audit::flush_sink();
        assert!(
            audit_events(workspace.path(), "model.write")
                .iter()
                .all(|event| event["detail"]["request_id"] != dry_id),
            "dry_run is not an applied write"
        );

        let (status, published, publish_id) = call_tracked(
            &app,
            &operator,
            json!({"building_id": bid, "meta": meta, "confirm": true}),
            Some("client-approved"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{published}");
        assert_eq!(published["ok"], true, "{published}");
        let revision = published["revision"]
            .as_str()
            .expect("revision")
            .to_string();
        assert_ne!(publish_id, "client-label");
        assert_ne!(publish_id, dry_id);
        open_fdd_edge_prototype::auth::audit::flush_sink();
        let events = audit_events(workspace.path(), "model.write");
        let detail = detail_for(&events, &publish_id);
        assert_eq!(detail["schema"], "openfdd.audit.v1");
        assert_eq!(detail["action"], "model.write");
        assert_eq!(detail["decision"], "allow");
        assert_eq!(detail["outcome"], "ok");
        assert_eq!(detail["http_status"], 200);
        assert_eq!(detail["actor"], "w3a-operator");
        assert_eq!(detail["site_id"], bid);
        assert_eq!(detail["change"]["tool"], "model.semantic_meta.put");
        assert_eq!(detail["caller_request_id"], "client-label");
        assert_eq!(detail["request_id"], publish_id);
        assert_eq!(detail["qa_run"]["run_id"], "server-run-w3a");
        assert_eq!(detail["qa_run"]["server_approved"], true);
        assert_eq!(
            detail["untrusted_labels"]["claimed_qa_run"],
            "client-approved"
        );
        assert_ne!(
            detail["qa_run"]["run_id"],
            detail["untrusted_labels"]["claimed_qa_run"]
        );

        let (status, conflict, conflict_id) = call_tracked(
            &app,
            &operator,
            json!({
                "building_id": bid,
                "meta": meta,
                "confirm": true,
                "expected_revision": "stale-rev-not-current"
            }),
            Some("client-approved"),
        )
        .await;
        assert_eq!(status, StatusCode::CONFLICT, "{conflict}");
        assert_eq!(conflict["conflict"], true, "{conflict}");
        assert_ne!(conflict_id, publish_id);
        open_fdd_edge_prototype::auth::audit::flush_sink();
        let events = audit_events(workspace.path(), "model.write");
        let detail = detail_for(&events, &conflict_id);
        assert_eq!(detail["decision"], "allow");
        assert_eq!(detail["outcome"], "failed");
        assert_eq!(detail["http_status"], 409);
        assert_eq!(detail["reason"], "revision_conflict");
        assert_eq!(detail["change"]["tool"], "model.semantic_meta.put");
        assert_eq!(detail["request_id"], conflict_id);
        assert_eq!(detail["qa_run"]["run_id"], "server-run-w3a");
        let published_head = std::fs::read_to_string(
            workspace
                .path()
                .join("data/csv_buildings")
                .join(bid)
                .join("semantic_meta.json"),
        )
        .expect("published head");
        assert!(
            published_head.contains(&revision),
            "a 409 must leave the published revision in place"
        );
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE and multi-tenant scope for the foreign denial"
    )]
    async fn foreign_semantic_meta_denial_ignores_the_client_qa_label() {
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _audit = EnvGuard::unset("OPENFDD_AUDIT_LOG_PATH");
        let _mt = EnvGuard::set("OPENFDD_MULTI_TENANT", "1");
        let manifest = write_qa_manifest(workspace.path(), "server-run-w3a");
        let _qa = EnvGuard::set(
            "OPENFDD_QA_RUN_MANIFEST",
            manifest.to_str().expect("manifest path"),
        );
        let plane = crate::tenant::ControlPlane {
            tenants: vec![
                crate::tenant::TenantRecord {
                    id: "w3a-a".into(),
                    name: "A".into(),
                    building_ids: vec!["W3A_OWN".into()],
                },
                crate::tenant::TenantRecord {
                    id: "w3a-b".into(),
                    name: "B".into(),
                    building_ids: vec!["W3A_FOREIGN".into()],
                },
            ],
        };
        plane.save(workspace.path()).expect("control plane");
        let state = app_state("semantic-meta-scope-secret");
        let app = app_with_request_ids(Arc::clone(&state));
        let operator = state
            .auth
            .issue_token_with_tenants("w3a-operator", Role::Operator, 60, &["w3a-a".to_string()])
            .expect("token");
        let foreign = "W3A_FOREIGN";
        let (status, body, server_id) = call_tracked(
            &app,
            &operator,
            json!({
                "building_id": foreign,
                "meta": semantic_meta(foreign),
                "confirm": true
            }),
            Some("client-approved"),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{body}");
        assert!(
            !workspace
                .path()
                .join("data/csv_buildings")
                .join(foreign)
                .join("semantic_meta.json")
                .exists(),
            "a foreign denial must not publish"
        );
        open_fdd_edge_prototype::auth::audit::flush_sink();
        let events = audit_events(workspace.path(), "model.write");
        let detail = detail_for(&events, &server_id);
        assert_eq!(detail["decision"], "deny");
        assert_eq!(detail["reason"], "site_scope");
        assert_eq!(detail["outcome"], "failed");
        assert_eq!(detail["http_status"], 403);
        assert_eq!(detail["site_id"], foreign);
        assert_eq!(detail["actor"], "w3a-operator");
        assert_eq!(detail["qa_run"]["run_id"], "server-run-w3a");
        assert_eq!(detail["qa_run"]["server_approved"], true);
        assert_eq!(
            detail["untrusted_labels"]["claimed_qa_run"],
            "client-approved"
        );
        assert_ne!(
            detail["qa_run"]["run_id"],
            detail["untrusted_labels"]["claimed_qa_run"]
        );
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE and the audit sink path for the write-failure fixture"
    )]
    async fn permitted_semantic_meta_write_records_a_sink_failure() {
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
        let _qa = EnvGuard::unset("OPENFDD_QA_RUN_MANIFEST");
        let blocker = workspace.path().join("audit-blocker");
        std::fs::write(&blocker, b"not-a-directory").expect("blocker");
        let audit_path = blocker.join("security_audit.jsonl");
        let _audit = EnvGuard::set(
            "OPENFDD_AUDIT_LOG_PATH",
            audit_path.to_str().expect("audit path"),
        );
        let before = open_fdd_edge_prototype::auth::audit::sink_status().write_failures;
        let state = app_state("semantic-meta-sink-secret");
        let app = app_with_request_ids(Arc::clone(&state));
        let bid = "W3A_SINK";
        let operator = token(&state, "w3a-sink", Role::Operator);
        let (status, body, server_id) = call_tracked(
            &app,
            &operator,
            json!({
                "building_id": bid,
                "meta": semantic_meta(bid),
                "confirm": true
            }),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(body["ok"], true, "{body}");
        assert!(
            workspace
                .path()
                .join("data/csv_buildings")
                .join(bid)
                .join("semantic_meta.json")
                .is_file(),
            "the model write commits even when the audit sink cannot store the line"
        );
        let report = open_fdd_edge_prototype::auth::audit::reconcile_request_ids(
            std::slice::from_ref(&server_id),
        );
        assert!(
            report
                .missing_recorded_as_loss
                .iter()
                .any(|id| id == &server_id),
            "request {server_id} should be on the loss ledger: {report:?}"
        );
        assert!(
            open_fdd_edge_prototype::auth::audit::sink_status().write_failures > before,
            "a failed append increments write_failures"
        );
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_DATABASE_URL for the historian purge fixture"
    )]
    async fn historian_orphans_and_purge_over_http() {
        let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .filter(|v| !v.trim().is_empty())
        else {
            return;
        };
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _audit = EnvGuard::unset("OPENFDD_AUDIT_LOG_PATH");
        let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
        let _storage = EnvGuard::unset("OPENFDD_STORAGE_URL");
        let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
        let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
        fdd_tsdb::clear_shared_pool();

        let site = "w7n-purge-http";
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
            .expect("purge postgres");
        crate::portal_inventory_fixtures::apply_schema(&pool).await;
        for sql in [
            "DELETE FROM sample WHERE site_id = $1",
            "DELETE FROM role_map WHERE building_id = $1",
            "DELETE FROM point_map WHERE site_id = $1",
            "DELETE FROM equipment WHERE building_id = $1",
        ] {
            sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
        }
        let tsdb = fdd_tsdb::Tsdb::from_pool(pool.clone());
        let point =
            |pid: &str, equip: &str, kind: &str, role: &str| fdd_tsdb::PortalInventoryPoint {
                portal_point_id: pid.into(),
                equipment_id: equip.into(),
                equip_type: Some(kind.into()),
                role: role.into(),
                unit: None,
            };
        let all = vec![
            point("p1", "AHU_1", "ahu", "sat"),
            point("p2", "VAV_1", "vav", "zone_t"),
            point("p3", "VAV_10", "vav", "zone_t"),
        ];
        let report = tsdb
            .sync_portal_inventory(site, "nf:purge", &all, true)
            .await
            .expect("sync");
        let mut batch = fdd_tsdb::UpsertBatch::default();
        let ts = chrono::Utc::now() - chrono::Duration::hours(1);
        for key in report.keys.values() {
            batch.push(fdd_tsdb::SampleRow::new(ts, site, key.clone(), Some(1.0)));
        }
        tsdb.upsert_samples_stats(&batch).await.expect("samples");
        tsdb.sync_portal_inventory(site, "nf:purge", &all[..1], true)
            .await
            .expect("sync without VAVs");

        let state = app_state("historian-purge-http-secret");
        let app = crate::routes::router(Arc::clone(&state));
        let viewer = token(&state, "viewer-purge", Role::Viewer);
        let operator = token(&state, "operator-purge", Role::Operator);

        let (status, orphans) = call(
            &app,
            "GET",
            &format!("/api/historian/orphans?building_id={site}"),
            &viewer,
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{orphans}");
        assert_eq!(orphans["orphaned_points"], 2);
        assert_eq!(orphans["equipment"], json!(["VAV_1", "VAV_10"]));

        let purge = json!({"building_id": site, "equipment_id": "VAV_1", "confirm": true});
        let (status, _) = call(
            &app,
            "POST",
            "/api/historian/purge",
            &viewer,
            Some(purge.clone()),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        let (status, json) =
            call(&app, "POST", "/api/historian/purge", &operator, Some(purge)).await;
        assert_eq!(status, StatusCode::OK, "{json}");
        assert_eq!(json["purge"]["samples_deleted"], 1);
        assert_eq!(json["purge"]["keys"], json!(["VAV_1.zone_t"]));

        // Exact equipment id: VAV_10 is untouched by the VAV_1 purge.
        let (_, orphans) = call(
            &app,
            "GET",
            &format!("/api/historian/orphans?building_id={site}"),
            &viewer,
            None,
        )
        .await;
        assert_eq!(orphans["equipment"], json!(["VAV_10"]));
        assert_eq!(tsdb.sample_count(site).await.expect("count"), 2);

        let (status, points) = call(
            &app,
            "GET",
            &format!("/api/historian/points?building_id={site}"),
            &viewer,
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(points["points"].as_array().map(Vec::len), Some(2));

        let audit = audit_events(workspace.path(), "historian_purge");
        assert_eq!(audit.len(), 1, "{audit:?}");
        assert_eq!(audit[0]["detail"]["sub"], "operator-purge");
        assert_eq!(audit[0]["detail"]["equipment_id"], "VAV_1");

        for sql in [
            "DELETE FROM sample WHERE site_id = $1",
            "DELETE FROM role_map WHERE building_id = $1",
            "DELETE FROM point_map WHERE site_id = $1",
            "DELETE FROM equipment WHERE building_id = $1",
        ] {
            sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
        }
        fdd_tsdb::clear_shared_pool();
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE for model point overlay API"
    )]
    async fn t1406_model_point_engineer_overlay_controls() {
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _audit = EnvGuard::unset("OPENFDD_AUDIT_LOG_PATH");
        let state = app_state("t1406-point-overlay-secret");
        let app = crate::routes::router(Arc::clone(&state));
        let bid = "T1406_OVERLAY";
        let pid = "pt-oa-t";
        let operator = token(&state, "op-t1406", Role::Operator);
        let viewer = token(&state, "viewer-t1406", Role::Viewer);

        let bad_unit = json!({
            "confirm": true,
            "building_id": bid,
            "equipment_id": "AHU_1",
            "point_id": pid,
            "unit": "not_a_real_unit",
            "quantity": "absolute_temperature"
        });
        let (status, json) =
            call(&app, "POST", "/api/model/point", &operator, Some(bad_unit)).await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{json}");
        assert_eq!(json.get("ok").and_then(|v| v.as_bool()), Some(false));

        let (status, json) = call(
            &app,
            "POST",
            "/api/model/point",
            &viewer,
            Some(json!({
                "confirm": true,
                "building_id": bid,
                "equipment_id": "AHU_1",
                "point_id": pid,
                "unit": "degF",
                "quantity": "absolute_temperature"
            })),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{json}");

        let (status, json) = call(
            &app,
            "POST",
            "/api/model/point",
            &operator,
            Some(json!({
                "building_id": bid,
                "equipment_id": "AHU_1",
                "point_id": pid,
                "unit": "degF",
                "quantity": "absolute_temperature"
            })),
        )
        .await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{json}");
        assert_eq!(json["error"], "confirm_required");

        let (status, json) = call(
            &app,
            "POST",
            "/api/model/point",
            &operator,
            Some(json!({
                "confirm": true,
                "building_id": bid,
                "equipment_id": "AHU_1",
                "point_id": pid,
                "unit": "degF",
                "quantity": "absolute_temperature",
                "primary_reference": true
            })),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{json}");
        assert_eq!(json.get("revision").and_then(|v| v.as_u64()), Some(1));

        open_fdd_edge_prototype::auth::audit::flush_sink();
        let events = audit_events(workspace.path(), "model.write");
        assert!(
            events.iter().any(|event| event["detail"]["outcome"] == "ok"
                && event["detail"]["change"]["tool"] == "model.point.upsert"),
            "{events:?}"
        );

        let overlay_path = workspace
            .path()
            .join("data/csv_buildings")
            .join(bid)
            .join("model_point_engineer_overlay.json");
        assert!(
            overlay_path.is_file(),
            "engineer overlay is separate from TTL"
        );
        let store =
            open_fdd_edge_prototype::csv_ingest::model_overlay::load_engineer_point_overlay(
                overlay_path.parent().expect("parent"),
            )
            .expect("load");
        let entry = store.points.get(pid).expect("entry");
        assert_eq!(entry.unit.as_deref(), Some("degF"));
        assert!(entry.primary_reference);

        use fdd_core::sensor_sweep::sweep_assessable_sql_role;
        assert!(sweep_assessable_sql_role("oa_t", entry.unit.as_deref()));
    }
}
