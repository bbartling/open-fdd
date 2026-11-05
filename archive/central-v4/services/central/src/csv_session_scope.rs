//! Role, tenant, and object scope for the CSV session routes.
//!
//! Reads, plan, preflight, execute, delete, fusion preview, and the session
//! list use one gate: operator or admin, active tenant, and the session's own
//! tenant. Execute stages a package for Timescale and does not write Arrow or
//! Parquet history. A denied caller does not stage files or start an action.

use axum::body::Bytes;
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use serde_json::{json, Value};

use crate::audit::{AuditAction, AuditChange, AuditEvent, HandlerResult, ReasonCode, TargetType};
use crate::auth::AuthUser;
use crate::state::AppState;
use crate::tenant::TenantContext;

const ROLE_ERROR: &str = "operator or admin role required";

fn tenant_context(user: &AuthUser) -> TenantContext {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    TenantContext::resolve_fail_closed(user, &plane)
}

fn exact_building_id(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty()
        || !trimmed
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return None;
    }
    Some(trimmed.to_string())
}

fn authorize(
    state: &AppState,
    headers: &HeaderMap,
    audit: &mut AuditEvent,
) -> Result<(AuthUser, TenantContext), (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(headers).map_err(|detail| {
        audit.deny(ReasonCode::from_auth_detail(&detail));
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": detail})),
        )
    })?;
    audit.user(&user);
    if !user.role.can_issue_commands() {
        audit.deny(ReasonCode::RoleRequired);
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": ROLE_ERROR})),
        ));
    }
    let ctx = tenant_context(&user);
    Ok((user, ctx))
}

fn session_visible(ctx: &TenantContext, session: &Value) -> bool {
    if !ctx.multi_tenant || ctx.hub_admin {
        return true;
    }
    let Some(active) = ctx.tenant_id.as_deref() else {
        return false;
    };
    open_fdd_edge_prototype::csv_ingest::session::session_tenant_id(session) == Some(active)
}

fn ensure_session(
    ctx: &TenantContext,
    session: &Value,
    audit: &mut AuditEvent,
) -> Result<(), (StatusCode, Json<Value>)> {
    if session_visible(ctx, session) {
        if let Some(building) =
            open_fdd_edge_prototype::csv_ingest::session::session_building_id(session)
        {
            audit.target_site(building);
        }
        return Ok(());
    }
    audit.deny(ReasonCode::TenantScope);
    Err((
        StatusCode::FORBIDDEN,
        Json(json!({"ok": false, "error": "session not in tenant scope"})),
    ))
}

fn load_visible(
    ctx: &TenantContext,
    session_id: &str,
    audit: &mut AuditEvent,
) -> Result<Value, (StatusCode, Json<Value>)> {
    let Some(session) = open_fdd_edge_prototype::csv_ingest::session::load_session(session_id)
    else {
        audit.reason(ReasonCode::NotFound);
        return Err((
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": "session not found"})),
        ));
    };
    ensure_session(ctx, &session, audit)?;
    Ok(session)
}

fn ensure_building(
    ctx: &TenantContext,
    building_id: &str,
    audit: &mut AuditEvent,
) -> Result<String, (StatusCode, Json<Value>)> {
    let Some(building_id) = exact_building_id(building_id) else {
        audit.reason(ReasonCode::InvalidRequest);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid building id"})),
        ));
    };
    audit.target_site(&building_id);
    if ctx.multi_tenant && !ctx.allow_building(&building_id) {
        audit.deny(ReasonCode::SiteScope);
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "building not in tenant scope",
                "building_id": building_id,
            })),
        ));
    }
    Ok(building_id)
}

fn stamp_for(
    user: &AuthUser,
    ctx: &TenantContext,
) -> open_fdd_edge_prototype::csv_ingest::session::SessionStamp {
    open_fdd_edge_prototype::csv_ingest::session::SessionStamp {
        owner_sub: user.sub.clone(),
        tenant_id: if ctx.multi_tenant {
            ctx.tenant_id.clone()
        } else {
            None
        },
    }
}

fn emit(audit: &mut AuditEvent, result: HandlerResult) -> HandlerResult {
    audit.finish(&result).emit();
    result
}

fn session_id_of(body: &Value) -> Option<String> {
    body.get("session_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

fn planned_building(body: &Value) -> Option<String> {
    body.get("plan")
        .and_then(|plan| plan.get("output_dataset_name"))
        .or_else(|| body.get("output_dataset_name"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

pub async fn preview(state: &AppState, headers: &HeaderMap, body: Bytes) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route();
    let result = preview_inner(state, headers, body, &mut audit).await;
    emit(&mut audit, result)
}

async fn preview_inner(
    state: &AppState,
    headers: &HeaderMap,
    body: Bytes,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (user, ctx) = authorize(state, headers, audit)?;
    let ct = headers
        .get(axum::http::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let stamp = stamp_for(&user, &ctx);
    let result = if ct.contains("application/json") {
        let value: Value = serde_json::from_slice(&body).unwrap_or(json!({}));
        if let Some(sid) = session_id_of(&value) {
            audit.target(TargetType::Route, &sid);
            load_visible(&ctx, &sid, audit)?;
        }
        open_fdd_edge_prototype::csv_ingest::preview_json_handler_stamped(&value, Some(&stamp))
    } else if let Some(sid) = open_fdd_edge_prototype::csv_ingest::staged_session_hint(&ct, &body)
        .ok()
        .flatten()
    {
        audit.target(TargetType::Route, &sid);
        load_visible(&ctx, &sid, audit)?;
        open_fdd_edge_prototype::csv_ingest::preview_handler_stamped(&ct, &body, None, Some(&stamp))
    } else {
        open_fdd_edge_prototype::csv_ingest::preview_handler_stamped(&ct, &body, None, Some(&stamp))
    };
    if let Some(sid) = result.get("session_id").and_then(|v| v.as_str()) {
        audit.target(TargetType::Route, sid);
    }
    Ok(Json(result))
}

pub async fn plan(state: &AppState, headers: &HeaderMap, body: Value) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route();
    let result = plan_inner(state, headers, body, &mut audit).await;
    emit(&mut audit, result)
}

async fn plan_inner(
    state: &AppState,
    headers: &HeaderMap,
    body: Value,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    let Some(sid) = session_id_of(&body) else {
        audit.reason(ReasonCode::InvalidRequest);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "session_id required"})),
        ));
    };
    audit.target(TargetType::Route, &sid);
    load_visible(&ctx, &sid, audit)?;
    let Some(building) = planned_building(&body) else {
        audit.reason(ReasonCode::SiteRequired);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "output_dataset_name required"})),
        ));
    };
    let building = ensure_building(&ctx, &building, audit)?;
    let result = open_fdd_edge_prototype::csv_ingest::plan_handler(&body);
    if result.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        if let Some(mut session) = open_fdd_edge_prototype::csv_ingest::session::load_session(&sid)
        {
            session["building_id"] = json!(building);
            let _ = open_fdd_edge_prototype::csv_ingest::session::save_session(&sid, &session);
        }
    }
    Ok(Json(result))
}

pub async fn preflight(state: &AppState, headers: &HeaderMap, body: Value) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route();
    let result = preflight_inner(state, headers, body, &mut audit).await;
    emit(&mut audit, result)
}

async fn preflight_inner(
    state: &AppState,
    headers: &HeaderMap,
    body: Value,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    let Some(sid) = session_id_of(&body) else {
        audit.reason(ReasonCode::InvalidRequest);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "session_id required"})),
        ));
    };
    audit.target(TargetType::Route, &sid);
    load_visible(&ctx, &sid, audit)?;
    Ok(Json(
        open_fdd_edge_prototype::csv_ingest::preflight_handler(&body),
    ))
}

pub async fn execute(state: &AppState, headers: &HeaderMap, body: Value) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::PackageImport);
    audit.target_route();
    let result = execute_inner(state, headers, body, &mut audit).await;
    emit(&mut audit, result)
}

async fn execute_inner(
    state: &AppState,
    headers: &HeaderMap,
    body: Value,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    let Some(sid) = session_id_of(&body) else {
        audit.reason(ReasonCode::InvalidRequest);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "session_id required"})),
        ));
    };
    audit.target(TargetType::Route, &sid);
    let session = load_visible(&ctx, &sid, audit)?;
    let Some(building) =
        open_fdd_edge_prototype::csv_ingest::session::session_building_id(&session)
    else {
        audit.reason(ReasonCode::SiteRequired);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "output_dataset_name required"})),
        ));
    };
    let building = ensure_building(&ctx, building, audit)?;
    let staged = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::execute_handler(&body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("session task: {e}")}));
    if staged.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        abort_staged(staged.get("package_root").and_then(|v| v.as_str()));
        audit.reason(ReasonCode::InvalidRequest);
        return Ok(Json(staged));
    }
    let staged_building = staged
        .get("building_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if staged_building != building {
        abort_staged(staged.get("package_root").and_then(|v| v.as_str()));
        audit.deny(ReasonCode::SiteScope);
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "building not in tenant scope"})),
        ));
    }
    if !crate::timescale_historian::historian_is_timescale() {
        abort_staged(staged.get("package_root").and_then(|v| v.as_str()));
        mark_session(&sid, "planned", &json!({"ok": false}));
        audit.reason(ReasonCode::HistorianError);
        return Ok(Json(json!({
            "ok": false,
            "error": "Timescale historian is not configured",
            "arrow": false,
            "parquet": false,
            "building_id": building,
        })));
    }
    let package_root = staged
        .get("package_root")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let sql_root = std::env::var("OPENFDD_SQL_ROOT").unwrap_or_else(|_| "sql/fdd".into());
    let seeded = match fdd_tsdb::Tsdb::connect_from_env().await {
        Ok(tsdb) => fdd_tsdb::seed_package_dir(
            &tsdb,
            std::path::Path::new(&package_root),
            &building,
            std::path::Path::new(&sql_root),
        )
        .await
        .map_err(|err| format!("{err:#}")),
        Err(err) => Err(format!("{err:#}")),
    };
    let rows = match seeded {
        Ok(rows) => rows,
        Err(err) => {
            abort_staged(Some(package_root.as_str()));
            mark_session(&sid, "planned", &json!({"ok": false}));
            audit.reason(ReasonCode::HistorianError);
            return Ok(Json(json!({
                "ok": false,
                "error": format!("timescale seed failed: {err:#}"),
                "arrow": false,
                "parquet": false,
                "building_id": building,
            })));
        }
    };
    let equipment_written = staged
        .get("equipment_written")
        .and_then(|v| v.as_u64())
        .and_then(|n| usize::try_from(n).ok())
        .unwrap_or(0);
    let live = match open_fdd_edge_prototype::csv_ingest::package::commit_staged_package(
        std::path::Path::new(&package_root),
        rows,
        equipment_written,
    ) {
        Ok(live) => live,
        Err(err) => {
            abort_staged(Some(package_root.as_str()));
            mark_session(&sid, "planned", &json!({"ok": false}));
            audit.reason(ReasonCode::StorageError);
            return Ok(Json(json!({
                "ok": false,
                "error": err,
                "arrow": false,
                "parquet": false,
                "building_id": building,
            })));
        }
    };
    let result = json!({
        "ok": true,
        "session_id": sid,
        "building_id": building,
        "package_root": live.display().to_string(),
        "total_rows": rows,
        "equipment_written": equipment_written,
        "historian": "timescale",
        "arrow": false,
        "parquet": false,
        "needs_timescale_seed": false,
    });
    mark_session(&sid, "executed", &result);
    let action_id = crate::actions::start_action(
        "csv_session_execute",
        "CSV session import",
        Some(json!({
            "building_id": building,
            "dataset_id": building,
            "tenant_id": ctx.tenant_id,
            "session_id": sid,
        })),
    )
    .ok();
    if let Some(ref aid) = action_id {
        let _ = crate::actions::finish_action(aid, "ok", Some(result.clone()));
    }
    audit.change(AuditChange::Package {
        rows: Some(rows),
        equipment: Some(equipment_written as u64),
    });
    let mut body = result;
    if let Some(obj) = body.as_object_mut() {
        obj.insert("action_id".into(), json!(action_id));
    }
    Ok(Json(body))
}

fn abort_staged(package_root: Option<&str>) {
    let Some(root) = package_root else {
        return;
    };
    open_fdd_edge_prototype::csv_ingest::package::abort_staged_package(std::path::Path::new(root));
}

fn mark_session(session_id: &str, status: &str, result: &Value) {
    let Some(mut session) = open_fdd_edge_prototype::csv_ingest::session::load_session(session_id)
    else {
        return;
    };
    session["status"] = json!(status);
    session["result"] = result.clone();
    let _ = open_fdd_edge_prototype::csv_ingest::session::save_session(session_id, &session);
}

pub async fn list(state: &AppState, headers: &HeaderMap, limit: usize) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route();
    let result = list_inner(state, headers, limit, &mut audit).await;
    emit(&mut audit, result)
}

async fn list_inner(
    state: &AppState,
    headers: &HeaderMap,
    limit: usize,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    let listed =
        open_fdd_edge_prototype::csv_ingest::session::list_sessions_where(limit, |session| {
            session_visible(&ctx, session)
        });
    Ok(Json(listed))
}

pub async fn latest(state: &AppState, headers: &HeaderMap) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route();
    let result = latest_inner(state, headers, &mut audit).await;
    emit(&mut audit, result)
}

async fn latest_inner(
    state: &AppState,
    headers: &HeaderMap,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    Ok(Json(
        open_fdd_edge_prototype::csv_ingest::session::latest_planned_where(|session| {
            session_visible(&ctx, session)
        }),
    ))
}

pub async fn get(state: &AppState, headers: &HeaderMap, session_id: String) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route().target(TargetType::Route, &session_id);
    let result = get_inner(state, headers, session_id, &mut audit).await;
    emit(&mut audit, result)
}

async fn get_inner(
    state: &AppState,
    headers: &HeaderMap,
    session_id: String,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    let session = load_visible(&ctx, &session_id, audit)?;
    Ok(Json(json!({"ok": true, "session": session})))
}

pub async fn delete(state: &AppState, headers: &HeaderMap, session_id: String) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::DatasetDelete);
    audit.target_route().target(TargetType::Route, &session_id);
    let result = delete_inner(state, headers, session_id, &mut audit).await;
    emit(&mut audit, result)
}

async fn delete_inner(
    state: &AppState,
    headers: &HeaderMap,
    session_id: String,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    load_visible(&ctx, &session_id, audit)?;
    Ok(Json(
        open_fdd_edge_prototype::csv_ingest::delete_session_handler(&session_id),
    ))
}

pub async fn fusion(
    state: &AppState,
    headers: &HeaderMap,
    session_id: String,
    limit: Option<usize>,
) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::SiteAccess);
    audit.target_route().target(TargetType::Route, &session_id);
    let result = fusion_inner(state, headers, session_id, limit, &mut audit).await;
    emit(&mut audit, result)
}

async fn fusion_inner(
    state: &AppState,
    headers: &HeaderMap,
    session_id: String,
    limit: Option<usize>,
    audit: &mut AuditEvent,
) -> HandlerResult {
    let (_user, ctx) = authorize(state, headers, audit)?;
    load_visible(&ctx, &session_id, audit)?;
    let cap = open_fdd_edge_prototype::csv_ingest::fusion_preview_limit_from_query(
        limit.map(|n| n.to_string()).as_deref(),
    );
    Ok(Json(
        open_fdd_edge_prototype::csv_ingest::fusion_preview_handler(&session_id, cap),
    ))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use axum::Router;
    use base64::Engine;
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use crate::auth::{self, Role};
    use crate::test_env_lock::{lock_env, WorkspaceEnv};
    use crate::user_store::{UserRecord, UserStore};

    const TENANT_A: &str = "w4a_tenant_a";
    const TENANT_B: &str = "w4a_tenant_b";
    const SITE_A: &str = "w4a_site_a";
    const SITE_B: &str = "w4a_site_b";
    const EQUIPMENT: &str = "AHU_1";

    struct EnvHold {
        prev: Vec<(&'static str, Option<String>)>,
    }

    impl EnvHold {
        fn set(pairs: &[(&'static str, Option<&str>)]) -> Self {
            let prev = pairs
                .iter()
                .map(|(key, value)| {
                    let old = std::env::var(key).ok();
                    match value {
                        Some(v) => std::env::set_var(key, v),
                        None => std::env::remove_var(key),
                    }
                    (*key, old)
                })
                .collect();
            Self { prev }
        }
    }

    impl Drop for EnvHold {
        fn drop(&mut self) {
            for (key, value) in &self.prev {
                match value {
                    Some(v) => std::env::set_var(key, v),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    fn user(username: &str, role: &str, tenants: &[&str]) -> UserRecord {
        UserRecord {
            username: username.into(),
            user_id: String::new(),
            role: role.into(),
            tenant_ids: tenants.iter().map(|t| (*t).to_string()).collect(),
            password_env: None,
            password: Some("scope-test".into()),
            disabled: false,
            session_version: 0,
        }
    }

    fn marker(root: &std::path::Path, site: &str) -> std::path::PathBuf {
        root.join("data/csv_buildings")
            .join(site)
            .join(EQUIPMENT)
            .join("marker.txt")
    }

    fn write_marker(root: &std::path::Path, site: &str) {
        let path = marker(root, site);
        std::fs::create_dir_all(path.parent().expect("marker parent")).unwrap();
        std::fs::write(&path, site).unwrap();
    }

    fn legacy_history(root: &std::path::Path) -> bool {
        let mut stack = vec![root.to_path_buf()];
        while let Some(dir) = stack.pop() {
            let Ok(rd) = std::fs::read_dir(&dir) else {
                continue;
            };
            for ent in rd.flatten() {
                let path = ent.path();
                if path.is_dir() {
                    stack.push(path);
                    continue;
                }
                let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if name == "history.parquet" || name == "data.arrow" {
                    return true;
                }
            }
        }
        false
    }

    struct Snap {
        marker_a: String,
        marker_b: String,
        session_a: String,
        session_b: String,
        actions: String,
        outside: String,
    }

    fn snap(root: &std::path::Path, session_a: &str, session_b: &str) -> Snap {
        let read = |path: &std::path::Path| std::fs::read_to_string(path).unwrap_or_default();
        Snap {
            marker_a: read(&marker(root, SITE_A)),
            marker_b: read(&marker(root, SITE_B)),
            session_a: read(
                &root
                    .join("data/csv_import_sessions")
                    .join(session_a)
                    .join("session.json"),
            ),
            session_b: read(
                &root
                    .join("data/csv_import_sessions")
                    .join(session_b)
                    .join("session.json"),
            ),
            actions: read(&root.join("data/actions/log.jsonl")),
            outside: read(&root.join("sentinels.txt")),
        }
    }

    fn assert_same(before: &Snap, after: &Snap, label: &str) {
        assert_eq!(before.marker_a, after.marker_a, "{label} marker a");
        assert_eq!(before.marker_b, after.marker_b, "{label} marker b");
        assert_eq!(before.session_a, after.session_a, "{label} session a");
        assert_eq!(before.session_b, after.session_b, "{label} session b");
        assert_eq!(before.actions, after.actions, "{label} actions");
        assert_eq!(before.outside, after.outside, "{label} outside");
    }

    async fn call(
        app: &Router,
        method: &str,
        path: &str,
        token: Option<&str>,
        body: Option<&Value>,
    ) -> (StatusCode, Value) {
        let mut builder = Request::builder().method(method).uri(path);
        if let Some(token) = token {
            builder = builder.header("authorization", format!("Bearer {token}"));
        }
        let request = if let Some(body) = body {
            builder
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap()
        } else {
            builder.body(Body::empty()).unwrap()
        };
        let response = app.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        let parsed = serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({}));
        (status, parsed)
    }

    fn csv_body() -> Value {
        let csv = "timestamp_utc,sat,unit_id\n2024-06-01T00:00:00Z,70,AHU_1\n2024-06-01T00:05:00Z,71,AHU_1\n";
        json!({
            "files": [{
                "filename": "history.csv",
                "content_base64": base64::engine::general_purpose::STANDARD.encode(csv.as_bytes())
            }]
        })
    }

    fn plan_body(session_id: &str, building: &str) -> Value {
        json!({
            "session_id": session_id,
            "plan": {
                "mode": "append",
                "output_dataset_name": building,
                "ambiguous_policy": "first",
                "fill_policy": "none",
                "files": [{
                    "filename": "history.csv",
                    "timestamp_column": "timestamp_utc",
                    "timezone": "UTC",
                    "value_columns": ["sat"],
                    "equipment_id_column": "unit_id"
                }]
            }
        })
    }

    async fn sample_sum(pool: &sqlx::PgPool, site: &str) -> f64 {
        sqlx::query_scalar::<_, Option<f64>>(
            "SELECT COALESCE(SUM(val), 0) FROM sample WHERE site_id = $1",
        )
        .bind(site)
        .fetch_one(pool)
        .await
        .unwrap()
        .unwrap_or(0.0)
    }

    async fn equipment_names(pool: &sqlx::PgPool, site: &str) -> Vec<String> {
        sqlx::query_scalar::<_, String>(
            "SELECT equipment_id FROM equipment WHERE building_id = $1 ORDER BY equipment_id",
        )
        .bind(site)
        .fetch_all(pool)
        .await
        .unwrap()
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE for the session scope matrix"
    )]
    async fn csv_session_routes_use_role_tenant_and_object_scope() {
        let _lock = lock_env();
        let workspace = tempfile::tempdir().unwrap();
        let _ws = WorkspaceEnv::set(workspace.path());
        let audit = workspace.path().join("security_audit.jsonl");
        let pg_url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let _env = EnvHold::set(&[
            ("OPENFDD_MULTI_TENANT", Some("1")),
            ("OPENFDD_CSV_STRICT", Some("0")),
            ("OPENFDD_HISTORIAN", Some("timescale")),
            ("OPENFDD_DATABASE_URL", pg_url.as_deref()),
            ("OPENFDD_AUDIT_LOG_PATH", Some(audit.to_str().unwrap())),
            ("OPENFDD_STORAGE_URL", None),
            ("OPENFDD_PARQUET_ROOT", None),
        ]);

        let plane = crate::tenant::ControlPlane {
            tenants: vec![
                crate::tenant::TenantRecord {
                    id: TENANT_A.into(),
                    name: "A".into(),
                    building_ids: vec![SITE_A.into()],
                },
                crate::tenant::TenantRecord {
                    id: TENANT_B.into(),
                    name: "B".into(),
                    building_ids: vec![SITE_B.into()],
                },
            ],
        };
        plane.save(workspace.path()).unwrap();
        let mut store = UserStore::default();
        for record in [
            user("viewer-a", "viewer", &[TENANT_A]),
            user("operator-a", "operator", &[TENANT_A]),
            user("viewer-b", "viewer", &[TENANT_B]),
            user("operator-b", "operator", &[TENANT_B]),
            user("operator-both", "operator", &[TENANT_A, TENANT_B]),
            user("operator-gone", "operator", &[TENANT_A]),
            user("operator-off", "operator", &[TENANT_A]),
        ] {
            store.upsert(record).unwrap();
        }
        store.save(workspace.path()).unwrap();
        write_marker(workspace.path(), SITE_A);
        write_marker(workspace.path(), SITE_B);
        std::fs::write(workspace.path().join("sentinels.txt"), "unchanged").unwrap();

        let pool = if let Some(url) = pg_url.as_deref() {
            let pool = sqlx::postgres::PgPoolOptions::new()
                .max_connections(2)
                .connect(url)
                .await
                .unwrap();
            crate::portal_inventory_fixtures::apply_schema(&pool).await;
            for (site, val) in [(SITE_A, 55.0), (SITE_B, 65.0)] {
                sqlx::query("DELETE FROM sample WHERE site_id = $1")
                    .bind(site)
                    .execute(&pool)
                    .await
                    .unwrap();
                sqlx::query("DELETE FROM equipment WHERE building_id = $1")
                    .bind(site)
                    .execute(&pool)
                    .await
                    .unwrap();
                sqlx::query(
                    "INSERT INTO site(site_id, dis, timezone, enabled) VALUES ($1, $1, 'UTC', true)
                     ON CONFLICT (site_id) DO NOTHING",
                )
                .bind(site)
                .execute(&pool)
                .await
                .unwrap();
                sqlx::query(
                    "INSERT INTO building(building_id, site_id, dis, timezone) VALUES ($1, $1, $1, 'UTC')
                     ON CONFLICT (building_id) DO NOTHING",
                )
                .bind(site)
                .execute(&pool)
                .await
                .unwrap();
                sqlx::query(
                    "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu')",
                )
                .bind(site)
                .bind(EQUIPMENT)
                .execute(&pool)
                .await
                .unwrap();
                sqlx::query(
                    "INSERT INTO sample(ts, site_id, openfdd_key, val) VALUES ('2024-01-01T00:00:00Z', $1, $2, $3)",
                )
                .bind(site)
                .bind(format!("{EQUIPMENT}.sat"))
                .bind(val)
                .execute(&pool)
                .await
                .unwrap();
            }
            Some(pool)
        } else {
            None
        };

        let mut state = crate::state::AppState::new();
        state.auth = auth::AuthConfig {
            secret: Some("csv-session-scope-test-secret-value".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = crate::routes::router(Arc::clone(&state)).layer(axum::middleware::from_fn(
            crate::contract::request_id_middleware,
        ));
        let token = |sub: &str, role: Role, tenants: &[String]| {
            state
                .auth
                .issue_token_with_tenants(sub, role, 600, tenants)
                .unwrap()
        };
        let a = vec![TENANT_A.to_string()];
        let b = vec![TENANT_B.to_string()];
        let viewer_a = token("viewer-a", Role::Viewer, &a);
        let operator_a = token("operator-a", Role::Operator, &a);
        let viewer_b = token("viewer-b", Role::Viewer, &b);
        let operator_b = token("operator-b", Role::Operator, &b);
        let both_a = token("operator-both", Role::Operator, &a);
        let both_b = token("operator-both", Role::Operator, &b);
        let admin = token("admin", Role::Admin, &[]);
        let deleted = token("operator-gone", Role::Operator, &a);
        let disabled = token("operator-off", Role::Operator, &a);
        let mut store = UserStore::load_or_empty(workspace.path());
        store.remove("operator-gone").unwrap();
        store.set_disabled("operator-off", true).unwrap();
        store.save(workspace.path()).unwrap();
        let expired_claims = state.auth.decode_claims(&operator_a).unwrap();
        let expired = jsonwebtoken::encode(
            &jsonwebtoken::Header::default(),
            &auth::JwtClaims {
                sub: expired_claims.sub,
                role: expired_claims.role,
                exp: chrono::Utc::now().timestamp() - 120,
                iat: expired_claims.iat,
                tenant_ids: expired_claims.tenant_ids,
                active_tenant_id: expired_claims.active_tenant_id,
                session_version: expired_claims.session_version,
                uid: expired_claims.uid,
                sid: expired_claims.sid,
                dlg: expired_claims.dlg,
                ak: expired_claims.ak,
            },
            &jsonwebtoken::EncodingKey::from_secret(state.auth.secret.as_ref().unwrap().as_bytes()),
        )
        .unwrap();

        let (status, created_a) = call(
            &app,
            "POST",
            "/api/csv/import/preview",
            Some(&operator_a),
            Some(&csv_body()),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{created_a}");
        assert_eq!(created_a["ok"], json!(true), "{created_a}");
        let session_a = created_a["session_id"].as_str().unwrap().to_string();
        let (status, planned_a) = call(
            &app,
            "POST",
            "/api/csv/import/plan",
            Some(&operator_a),
            Some(&plan_body(&session_a, SITE_A)),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{planned_a}");
        assert_eq!(planned_a["ok"], json!(true), "{planned_a}");

        let (status, created_b) = call(
            &app,
            "POST",
            "/api/csv/import/preview",
            Some(&operator_b),
            Some(&csv_body()),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{created_b}");
        let session_b = created_b["session_id"].as_str().unwrap().to_string();
        let (status, planned_b) = call(
            &app,
            "POST",
            "/api/csv/import/plan",
            Some(&operator_b),
            Some(&plan_body(&session_b, SITE_B)),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{planned_b}");
        assert_eq!(planned_b["ok"], json!(true), "{planned_b}");
        assert_ne!(session_a, session_b);

        let before = snap(workspace.path(), &session_a, &session_b);
        assert_eq!(before.marker_a, SITE_A);
        assert_eq!(before.marker_b, SITE_B);
        assert!(!legacy_history(workspace.path()));
        let sums_before = if let Some(pool) = &pool {
            Some((
                sample_sum(pool, SITE_A).await,
                sample_sum(pool, SITE_B).await,
            ))
        } else {
            None
        };

        let session_path = format!("/api/csv/import/sessions/{session_a}");
        let fusion_path = format!("/api/csv/import/sessions/{session_a}/fusion-preview");
        let preview_path = format!("/api/datasets/{SITE_A}/preview");
        let denied_tokens = [
            ("viewer-a", viewer_a.as_str(), StatusCode::FORBIDDEN),
            ("viewer-b", viewer_b.as_str(), StatusCode::FORBIDDEN),
            ("operator-b", operator_b.as_str(), StatusCode::FORBIDDEN),
            ("both-b", both_b.as_str(), StatusCode::FORBIDDEN),
        ];
        for (label, token, expect) in denied_tokens {
            for (method, path, body) in [
                ("GET", session_path.as_str(), None),
                ("GET", fusion_path.as_str(), None),
                ("DELETE", session_path.as_str(), None),
                (
                    "POST",
                    "/api/csv/import/plan",
                    Some(plan_body(&session_a, SITE_A)),
                ),
                (
                    "POST",
                    "/api/csv/import/preflight",
                    Some(json!({"session_id": session_a})),
                ),
                (
                    "POST",
                    "/api/csv/import/execute",
                    Some(json!({"session_id": session_a, "confirm": true})),
                ),
                (
                    "POST",
                    "/api/csv/import/preview",
                    Some({
                        let mut body = csv_body();
                        body["session_id"] = json!(session_a);
                        body
                    }),
                ),
            ] {
                let (status, response) = call(&app, method, path, Some(token), body.as_ref()).await;
                assert_eq!(status, expect, "{label} {method} {path} {response}");
                assert_eq!(response["ok"], json!(false), "{label} {method} {path}");
                assert!(
                    response.get("session").is_none(),
                    "{label} {method} {path} returned a session"
                );
                assert_same(
                    &before,
                    &snap(workspace.path(), &session_a, &session_b),
                    &format!("{label} {method} {path}"),
                );
            }
            let (status, response) = call(&app, "GET", &preview_path, Some(token), None).await;
            if label == "viewer-a" {
                assert_ne!(status, StatusCode::FORBIDDEN, "{response}");
            } else {
                assert_eq!(
                    status,
                    StatusCode::FORBIDDEN,
                    "{label} dataset preview {response}"
                );
            }
            let (status, response) = call(
                &app,
                "DELETE",
                &format!("/api/datasets?id={SITE_A}"),
                Some(token),
                None,
            )
            .await;
            assert_eq!(
                status,
                StatusCode::FORBIDDEN,
                "{label} dataset delete {response}"
            );
            assert_same(
                &before,
                &snap(workspace.path(), &session_a, &session_b),
                &format!("{label} dataset"),
            );
        }

        for (label, token) in [
            ("viewer-a", viewer_a.as_str()),
            ("viewer-b", viewer_b.as_str()),
        ] {
            for path in [
                "/api/csv/import/sessions",
                "/api/csv/import/sessions/latest/planned",
            ] {
                let (status, response) = call(&app, "GET", path, Some(token), None).await;
                assert_eq!(status, StatusCode::FORBIDDEN, "{label} {path} {response}");
                assert_eq!(response["ok"], json!(false), "{label} {path}");
                assert!(response.get("session").is_none(), "{label} {path}");
                assert_same(
                    &before,
                    &snap(workspace.path(), &session_a, &session_b),
                    &format!("{label} {path}"),
                );
            }
        }

        let (status, listed_b) = call(
            &app,
            "GET",
            "/api/csv/import/sessions",
            Some(&operator_b),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{listed_b}");
        let ids_b = listed_b["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|row| row.get("session_id").and_then(|v| v.as_str()))
            .collect::<Vec<_>>();
        assert!(ids_b.contains(&session_b.as_str()), "{listed_b}");
        assert!(!ids_b.contains(&session_a.as_str()), "{listed_b}");
        let (status, latest_b) = call(
            &app,
            "GET",
            "/api/csv/import/sessions/latest/planned",
            Some(&operator_b),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{latest_b}");
        assert_eq!(latest_b["ok"], json!(true), "{latest_b}");
        assert_eq!(latest_b["session_id"], json!(session_b), "{latest_b}");
        let (status, listed_both) =
            call(&app, "GET", "/api/csv/import/sessions", Some(&both_b), None).await;
        assert_eq!(status, StatusCode::OK, "{listed_both}");
        let ids_both = listed_both["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|row| row.get("session_id").and_then(|v| v.as_str()))
            .collect::<Vec<_>>();
        assert!(ids_both.contains(&session_b.as_str()), "{listed_both}");
        assert!(!ids_both.contains(&session_a.as_str()), "{listed_both}");
        let (status, latest_both) = call(
            &app,
            "GET",
            "/api/csv/import/sessions/latest/planned",
            Some(&both_b),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{latest_both}");
        assert_eq!(latest_both["session_id"], json!(session_b), "{latest_both}");
        assert_same(
            &before,
            &snap(workspace.path(), &session_a, &session_b),
            "filtered list",
        );

        for (label, token) in [
            ("anonymous", None),
            ("deleted", Some(deleted.as_str())),
            ("disabled", Some(disabled.as_str())),
            ("expired", Some(expired.as_str())),
        ] {
            let (status, response) = call(&app, "GET", &session_path, token, None).await;
            assert_eq!(status, StatusCode::UNAUTHORIZED, "{label} {response}");
            let (status, response) = call(
                &app,
                "POST",
                "/api/csv/import/execute",
                token,
                Some(&json!({"session_id": session_a, "confirm": true})),
            )
            .await;
            assert_eq!(
                status,
                StatusCode::UNAUTHORIZED,
                "{label} execute {response}"
            );
            assert_same(
                &before,
                &snap(workspace.path(), &session_a, &session_b),
                label,
            );
        }

        let (status, foreign_plan) = call(
            &app,
            "POST",
            "/api/csv/import/plan",
            Some(&operator_a),
            Some(&plan_body(&session_a, SITE_B)),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{foreign_plan}");
        assert_same(
            &before,
            &snap(workspace.path(), &session_a, &session_b),
            "own operator foreign building",
        );

        let (status, own) = call(&app, "GET", &session_path, Some(&operator_a), None).await;
        assert_eq!(status, StatusCode::OK, "{own}");
        assert_eq!(own["ok"], json!(true), "{own}");
        assert_eq!(own["session"]["session_id"], json!(session_a), "{own}");
        assert_eq!(own["session"]["tenant_id"], json!(TENANT_A), "{own}");
        assert_eq!(own["session"]["building_id"], json!(SITE_A), "{own}");

        let (status, both) = call(&app, "GET", &session_path, Some(&both_a), None).await;
        assert_eq!(status, StatusCode::OK, "{both}");
        assert_eq!(both["session"]["session_id"], json!(session_a), "{both}");

        let (status, admin_a) = call(&app, "GET", &session_path, Some(&admin), None).await;
        assert_eq!(status, StatusCode::OK, "{admin_a}");
        let (status, admin_b) = call(
            &app,
            "GET",
            &format!("/api/csv/import/sessions/{session_b}"),
            Some(&admin),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{admin_b}");
        assert_eq!(
            admin_b["session"]["building_id"],
            json!(SITE_B),
            "{admin_b}"
        );

        let (status, listed_a) = call(
            &app,
            "GET",
            "/api/csv/import/sessions",
            Some(&operator_a),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{listed_a}");
        assert_eq!(listed_a["count"], json!(1), "{listed_a}");
        assert_eq!(listed_a["sessions"][0]["session_id"], json!(session_a));
        let (status, latest_a) = call(
            &app,
            "GET",
            "/api/csv/import/sessions/latest/planned",
            Some(&operator_a),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{latest_a}");
        assert_eq!(latest_a["session_id"], json!(session_a), "{latest_a}");

        let (status, fusion) = call(&app, "GET", &fusion_path, Some(&operator_a), None).await;
        assert_eq!(status, StatusCode::OK, "{fusion}");
        assert_eq!(fusion["session_id"], json!(session_a), "{fusion}");
        let (status, stats_before) =
            call(&app, "GET", "/api/ingest/stats", Some(&operator_a), None).await;
        assert_eq!(status, StatusCode::OK, "{stats_before}");

        let (status, executed) = call(
            &app,
            "POST",
            "/api/csv/import/execute",
            Some(&operator_a),
            Some(&json!({"session_id": session_a, "confirm": true})),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{executed}");
        assert_eq!(executed["arrow"], json!(false), "{executed}");
        assert_eq!(executed["parquet"], json!(false), "{executed}");
        assert!(!legacy_history(workspace.path()), "legacy history written");
        assert_eq!(
            std::fs::read_to_string(workspace.path().join("sentinels.txt")).unwrap(),
            "unchanged"
        );
        assert_eq!(
            std::fs::read_to_string(marker(workspace.path(), SITE_B)).unwrap(),
            SITE_B
        );
        if let Some(pool) = &pool {
            assert_eq!(executed["ok"], json!(true), "{executed}");
            assert_eq!(executed["building_id"], json!(SITE_A), "{executed}");
            assert_eq!(sample_sum(pool, SITE_A).await, 141.0, "own samples");
            assert_eq!(sample_sum(pool, SITE_B).await, sums_before.unwrap().1);
            assert_eq!(
                equipment_names(pool, SITE_A).await,
                vec![EQUIPMENT.to_string()]
            );
            assert_eq!(
                equipment_names(pool, SITE_B).await,
                vec![EQUIPMENT.to_string()]
            );
            let (status, actions_a) =
                call(&app, "GET", "/api/actions", Some(&operator_a), None).await;
            assert_eq!(status, StatusCode::OK, "{actions_a}");
            let ids_a = actions_a["actions"].as_array().cloned().unwrap_or_default();
            assert!(
                ids_a
                    .iter()
                    .any(|row| row["kind"] == json!("csv_session_execute")
                        && row["building_id"] == json!(SITE_A)),
                "{actions_a}"
            );
            let (status, actions_b) =
                call(&app, "GET", "/api/actions", Some(&operator_b), None).await;
            assert_eq!(status, StatusCode::OK, "{actions_b}");
            let ids_b = actions_b["actions"].as_array().cloned().unwrap_or_default();
            assert!(
                ids_b.iter().all(|row| row["building_id"] != json!(SITE_A)),
                "{actions_b}"
            );
            let action_id = ids_a
                .iter()
                .find(|row| row["kind"] == json!("csv_session_execute"))
                .and_then(|row| row["id"].as_str())
                .unwrap()
                .to_string();
            let (status, cleared) = call(
                &app,
                "DELETE",
                &format!("/api/actions/{action_id}"),
                Some(&viewer_a),
                None,
            )
            .await;
            assert_eq!(status, StatusCode::FORBIDDEN, "{cleared}");
            let (status, cleared_b) = call(
                &app,
                "DELETE",
                &format!("/api/actions/{action_id}"),
                Some(&operator_b),
                None,
            )
            .await;
            assert_ne!(status, StatusCode::OK, "{cleared_b}");
        } else {
            assert_eq!(executed["ok"], json!(false), "{executed}");
            assert_eq!(
                std::fs::read_to_string(marker(workspace.path(), SITE_A)).unwrap(),
                SITE_A
            );
        }
        let (status, stats_after) =
            call(&app, "GET", "/api/ingest/stats", Some(&operator_b), None).await;
        assert_eq!(stats_after["ingest_ok"], stats_before["ingest_ok"]);
        assert_eq!(status, StatusCode::OK);

        let (status, removed) = call(&app, "DELETE", &session_path, Some(&operator_a), None).await;
        assert_eq!(status, StatusCode::OK, "{removed}");
        assert_eq!(removed["ok"], json!(true), "{removed}");
        assert!(!workspace
            .path()
            .join("data/csv_import_sessions")
            .join(&session_a)
            .exists());
        let (status, still_b) = call(
            &app,
            "GET",
            &format!("/api/csv/import/sessions/{session_b}"),
            Some(&operator_b),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{still_b}");
        assert_eq!(still_b["session"]["building_id"], json!(SITE_B));
        let (status, viewer_delete_b) = call(
            &app,
            "DELETE",
            &format!("/api/csv/import/sessions/{session_b}"),
            Some(&viewer_b),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{viewer_delete_b}");
        assert!(workspace
            .path()
            .join("data/csv_import_sessions")
            .join(&session_b)
            .join("session.json")
            .is_file());

        if let Some(pool) = &pool {
            for site in [SITE_A, SITE_B] {
                for sql in [
                    "DELETE FROM sample WHERE site_id = $1",
                    "DELETE FROM role_map WHERE building_id = $1",
                    "DELETE FROM point_map WHERE site_id = $1",
                    "DELETE FROM equipment WHERE building_id = $1",
                    "DELETE FROM building WHERE building_id = $1",
                    "DELETE FROM site WHERE site_id = $1",
                ] {
                    sqlx::query(sql).bind(site).execute(pool).await.unwrap();
                }
            }
        }
    }
}
