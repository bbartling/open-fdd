//! Tenant and role scope for Actions history.
//!
//! Listing returns rows for the caller's tenants and sites. A hub admin sees
//! the whole log. Deletes require an operator or admin acting inside that
//! scope, and each delete or clear (allowed or denied) appends one
//! `openfdd.audit.v1` event outside the Actions log.

use std::path::Path;

use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};

use crate::actions::{ActionEntry, ActionRef, RemoveOne};
use crate::audit::{AuditAction, AuditChange, AuditEvent, BoundedList, ReasonCode, TargetType};
use crate::auth::{AuthUser, Role};
use crate::tenant::ControlPlane;

type ActionResponse = Result<Json<Value>, (StatusCode, Json<Value>)>;

struct CallerScope {
    role: Role,
    tenant_ids: Vec<String>,
    /// Hub admin, or the single-hub log when multi-tenant mode is off.
    sees_all: bool,
}

pub async fn list_actions(user: &AuthUser, limit: Option<usize>) -> ActionResponse {
    let user = user.clone();
    let limit = limit.unwrap_or(10);
    let value = tokio::task::spawn_blocking(move || list_sync(&user, limit))
        .await
        .map_err(join_err)?;
    value.map(Json)
}

pub async fn delete_action(user: &AuthUser, id: &str) -> ActionResponse {
    let mut audit = AuditEvent::new(AuditAction::ActionDelete);
    audit.user(user).target(TargetType::Action, id);
    let user = user.clone();
    let id = id.to_string();
    run_audited(audit, move |audit| delete_sync(&user, &id, audit)).await
}

pub async fn clear_actions(user: &AuthUser) -> ActionResponse {
    let mut audit = AuditEvent::new(AuditAction::ActionsClear);
    audit.user(user).target_type(TargetType::ActionsLog);
    let user = user.clone();
    run_audited(audit, move |audit| clear_sync(&user, audit)).await
}

/// Run a blocking Actions-log write and emit its audit event once the result
/// (including a failed blocking task) is known.
async fn run_audited<F>(audit: AuditEvent, op: F) -> ActionResponse
where
    F: FnOnce(&mut AuditEvent) -> Result<Value, (StatusCode, Json<Value>)> + Send + 'static,
{
    let fallback = audit.clone();
    let joined = tokio::task::spawn_blocking(move || {
        let mut audit = audit;
        let result = op(&mut audit).map(Json);
        (result, audit)
    })
    .await;
    let (result, mut audit) = match joined {
        Ok(pair) => pair,
        Err(error) => (Err(join_err(error)), fallback),
    };
    audit.finish(&result).emit();
    result
}

/// Stamp `tenant_id` / `building_id` from detail and the control plane.
///
/// Called when a row is started or finished so later reads do not have to guess
/// from free-form detail. A missing sole tenant leaves `tenant_id` empty.
pub(crate) fn bind_entry_scope(entry: &mut ActionEntry) {
    if let Some(building) = detail_owned(&entry.detail, "building_id")
        .or_else(|| detail_owned(&entry.detail, "dataset_id"))
    {
        entry.building_id = Some(building);
    }
    if let Some(tenant) = detail_owned(&entry.detail, "tenant_id") {
        entry.tenant_id = Some(tenant);
        return;
    }
    let Some(building_id) = nonempty(entry.building_id.as_deref()) else {
        return;
    };
    entry.tenant_id = load_plane().sole_tenant_for_building(building_id);
}

fn list_sync(user: &AuthUser, limit: usize) -> Result<Value, (StatusCode, Json<Value>)> {
    let scope = caller_scope(user);
    let plane = load_plane();
    let entries = crate::actions::list_visible(limit, |entry| entry_visible(&scope, &plane, entry))
        .map_err(store_err)?;
    Ok(json!({
        "ok": true,
        "count": entries.len(),
        "actions": entries,
    }))
}

fn delete_sync(
    user: &AuthUser,
    id: &str,
    audit: &mut AuditEvent,
) -> Result<Value, (StatusCode, Json<Value>)> {
    let scope = caller_scope(user);
    if !scope.role.can_issue_commands() {
        audit.deny(ReasonCode::RoleRequired);
        return Err(forbidden("operator or admin role required"));
    }
    let plane = load_plane();
    let outcome =
        crate::actions::remove_one(id, |entry| entry_visible(&scope, &plane, entry), stamp)
            .map_err(|e| {
                audit.reason(ReasonCode::StorageError);
                store_err(e)
            })?;
    match outcome {
        RemoveOne::Missing => Err((
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": "action not found"})),
        )),
        RemoveOne::OutOfScope(action) => {
            bind_action_scope(audit, &scope, &action);
            audit.deny(ReasonCode::TenantScope);
            Err(forbidden("action is outside tenant scope"))
        }
        RemoveOne::Removed {
            action,
            in_scope_remaining,
        } => {
            bind_action_scope(audit, &scope, &action);
            audit.change(AuditChange::ActionsRemoved {
                action_ids: BoundedList::new(std::slice::from_ref(&action.id)),
            });
            Ok(json!({
                "ok": true,
                "deleted": action.id,
                "remaining": in_scope_remaining,
            }))
        }
    }
}

fn clear_sync(user: &AuthUser, audit: &mut AuditEvent) -> Result<Value, (StatusCode, Json<Value>)> {
    let scope = caller_scope(user);
    if !scope.role.can_issue_commands() {
        audit.deny(ReasonCode::RoleRequired);
        return Err(forbidden("operator or admin role required"));
    }
    let plane = load_plane();
    let removed =
        crate::actions::remove_matching(|entry| entry_visible(&scope, &plane, entry), stamp)
            .map_err(|e| {
                audit.reason(ReasonCode::StorageError);
                store_err(e)
            })?;
    let ids: Vec<&str> = removed.iter().map(|a| a.id.as_str()).collect();
    audit.change(AuditChange::ActionsRemoved {
        action_ids: BoundedList::new(&ids),
    });
    Ok(json!({
        "ok": true,
        "cleared": true,
        "deleted_count": removed.len(),
        "remaining": 0,
    }))
}

fn caller_scope(user: &AuthUser) -> CallerScope {
    let hub_admin = user.role == Role::Admin && user.tenant_ids.is_empty();
    // Mode off keeps the single hub log. Mode on filters unless the caller is a hub admin.
    let sees_all = hub_admin || !crate::tenant::multi_tenant_enabled();
    CallerScope {
        role: user.role,
        tenant_ids: user.tenant_ids.clone(),
        sees_all,
    }
}

fn entry_visible(scope: &CallerScope, plane: &ControlPlane, entry: &ActionEntry) -> bool {
    if scope.sees_all {
        return true;
    }
    let tenant = effective_tenant(entry);
    let building = effective_building(entry);
    match (tenant, building) {
        (Some(tenant_id), Some(building_id)) => {
            scope.tenant_ids.iter().any(|id| id == tenant_id)
                && tenant_lists_building(plane, tenant_id, building_id)
        }
        (Some(tenant_id), None) => scope.tenant_ids.iter().any(|id| id == tenant_id),
        (None, Some(building_id)) => scope
            .tenant_ids
            .iter()
            .any(|tenant_id| tenant_lists_building(plane, tenant_id, building_id)),
        (None, None) => false,
    }
}

fn tenant_lists_building(plane: &ControlPlane, tenant_id: &str, building_id: &str) -> bool {
    plane.tenants.iter().any(|tenant| {
        tenant.id == tenant_id
            && tenant
                .building_ids
                .iter()
                .any(|building| building == building_id)
    })
}

fn stamp(entry: &ActionEntry) -> ActionRef {
    ActionRef {
        id: entry.id.clone(),
        tenant_id: effective_tenant(entry).map(str::to_string),
        building_id: effective_building(entry).map(str::to_string),
    }
}

fn effective_building(entry: &ActionEntry) -> Option<&str> {
    nonempty(entry.building_id.as_deref())
        .or_else(|| detail_str(&entry.detail, "building_id"))
        .or_else(|| detail_str(&entry.detail, "dataset_id"))
}

fn effective_tenant(entry: &ActionEntry) -> Option<&str> {
    nonempty(entry.tenant_id.as_deref()).or_else(|| detail_str(&entry.detail, "tenant_id"))
}

fn detail_owned(detail: &Option<Value>, key: &str) -> Option<String> {
    detail_str(detail, key).map(str::to_string)
}

fn detail_str<'a>(detail: &'a Option<Value>, key: &str) -> Option<&'a str> {
    nonempty(
        detail
            .as_ref()
            .and_then(|value| value.get(key))
            .and_then(Value::as_str),
    )
}

fn nonempty(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|text| !text.is_empty())
}

fn load_plane() -> ControlPlane {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    ControlPlane::load_or_legacy(Path::new(&workspace))
}

/// Resolved tenant and site of the row the caller tried to delete.
fn bind_action_scope(audit: &mut AuditEvent, scope: &CallerScope, action: &ActionRef) {
    let tenant_id = action
        .tenant_id
        .as_deref()
        .or_else(|| scope.tenant_ids.first().map(String::as_str));
    audit.tenant(tenant_id);
    if let Some(building_id) = action.building_id.as_deref() {
        audit.site(building_id);
    }
}

fn forbidden(error: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::FORBIDDEN,
        Json(json!({"ok": false, "error": error})),
    )
}

fn store_err(error: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({"ok": false, "error": error})),
    )
}

fn join_err(error: tokio::task::JoinError) -> (StatusCode, Json<Value>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({"ok": false, "error": format!("actions task failed: {error}")})),
    )
}

#[cfg(test)]
mod tests {
    use super::{entry_visible, CallerScope};
    use crate::actions::ActionEntry;
    use crate::auth::{AuthConfig, Role};
    use crate::state::AppState;
    use crate::tenant::{ControlPlane, TenantRecord};
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use serde_json::json;
    use serde_json::Value;
    use std::fs::{self, OpenOptions};
    use std::io::Write;
    use std::path::Path;
    use std::sync::Arc;
    use tower::ServiceExt;

    struct RestoreVar {
        key: &'static str,
        prev: Option<String>,
    }

    impl RestoreVar {
        fn set(key: &'static str, value: &str) -> Self {
            let prev = std::env::var(key).ok();
            std::env::set_var(key, value);
            Self { key, prev }
        }
    }

    impl Drop for RestoreVar {
        fn drop(&mut self) {
            match self.prev.take() {
                Some(value) => std::env::set_var(self.key, value),
                None => std::env::remove_var(self.key),
            }
        }
    }

    struct Fixture {
        id_a: String,
        id_b: String,
        id_legacy_b: String,
        marker_a: String,
        marker_b: String,
        marker_legacy_b: String,
    }

    struct Tokens {
        viewer_a: String,
        operator_a: String,
        admin_a: String,
        hub: String,
    }

    fn write_fixture(workspace: &Path) -> Fixture {
        let plane = ControlPlane {
            tenants: vec![
                TenantRecord {
                    id: "tenant-a".into(),
                    name: "Tenant A".into(),
                    building_ids: vec!["site-a".into()],
                },
                TenantRecord {
                    id: "tenant-b".into(),
                    name: "Tenant B".into(),
                    building_ids: vec!["site-b".into()],
                },
            ],
        };
        plane.save(workspace).expect("control plane");
        let run = uuid::Uuid::new_v4();
        let marker_a = format!("marker-a-{run}");
        let marker_b = format!("marker-b-{run}");
        let marker_legacy_b = format!("marker-legacy-b-{run}");
        let id_a = crate::actions::start_action(
            "package_import",
            &marker_a,
            Some(json!({"building_id": "site-a", "marker": marker_a})),
        )
        .expect("start a");
        let id_b = crate::actions::start_action(
            "package_import",
            &marker_b,
            Some(json!({"building_id": "site-b", "marker": marker_b})),
        )
        .expect("start b");
        let id_legacy_b = format!("act-legacy-{run}");
        let legacy = json!({
            "id": id_legacy_b,
            "kind": "package_import",
            "label": marker_legacy_b,
            "started_at": "2026-01-01T00:00:00.000Z",
            "status": "ok",
            "detail": {"building_id": "site-b", "marker": marker_legacy_b}
        });
        let path = workspace.join("data").join("actions").join("log.jsonl");
        let mut file = OpenOptions::new().append(true).open(path).expect("log");
        writeln!(file, "{legacy}").expect("legacy row");
        Fixture {
            id_a,
            id_b,
            id_legacy_b,
            marker_a,
            marker_b,
            marker_legacy_b,
        }
    }

    fn tokens(state: &AppState) -> Tokens {
        let tenant_a = "tenant-a".to_string();
        let member = std::slice::from_ref(&tenant_a);
        Tokens {
            viewer_a: state
                .auth
                .issue_token_with_tenants("tenant-a-viewer", Role::Viewer, 600, member)
                .expect("viewer token"),
            operator_a: state
                .auth
                .issue_token_with_tenants("tenant-a-operator", Role::Operator, 600, member)
                .expect("operator token"),
            admin_a: state
                .auth
                .issue_token_with_tenants("tenant-a-admin", Role::Admin, 600, member)
                .expect("tenant admin token"),
            hub: state
                .auth
                .issue_token_with_tenants("hub-admin", Role::Admin, 600, &[])
                .expect("hub token"),
        }
    }

    async fn send(
        app: axum::Router,
        method: &str,
        uri: &str,
        token: Option<&str>,
    ) -> (StatusCode, Value) {
        let mut builder = Request::builder().method(method).uri(uri);
        if let Some(token) = token {
            builder = builder.header("authorization", format!("Bearer {token}"));
        }
        let response = app
            .oneshot(builder.body(Body::empty()).expect("request"))
            .await
            .expect("response");
        let status = response.status();
        let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let json = serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| json!({"raw": String::from_utf8_lossy(&bytes).into_owned()}));
        (status, json)
    }

    fn log_text(workspace: &Path) -> String {
        fs::read_to_string(workspace.join("data").join("actions").join("log.jsonl"))
            .unwrap_or_default()
    }

    fn listed_ids(body: &Value) -> Vec<String> {
        body["actions"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|row| row["id"].as_str().map(str::to_string))
            .collect()
    }

    fn audit_events(path: &Path) -> Vec<Value> {
        open_fdd_edge_prototype::auth::audit::flush_sink();
        let raw = fs::read_to_string(path).unwrap_or_default();
        raw.lines()
            .filter_map(|line| serde_json::from_str::<Value>(line).ok())
            .filter(|event| event["event"] == "actions.delete" || event["event"] == "actions.clear")
            .map(|event| {
                assert_eq!(event["detail"]["schema"], "openfdd.audit.v1");
                event["detail"].clone()
            })
            .collect()
    }

    fn removed_ids(event: &Value) -> Vec<String> {
        event["change"]["action_ids"]["items"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|id| id.as_str().map(str::to_string))
            .collect()
    }

    fn assert_only_a(body: &Value, fixture: &Fixture) {
        let ids = listed_ids(body);
        assert_eq!(ids, vec![fixture.id_a.clone()]);
        let rendered = body.to_string();
        assert!(rendered.contains(&fixture.marker_a));
        assert!(!rendered.contains(&fixture.marker_b));
        assert!(!rendered.contains(&fixture.marker_legacy_b));
        assert!(!rendered.contains(&fixture.id_b));
        assert!(!rendered.contains(&fixture.id_legacy_b));
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "hold the workspace env lock across the handler calls that read it"
    )]
    async fn actions_history_is_tenant_and_role_scoped() {
        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("temp workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _mt = RestoreVar::set("OPENFDD_MULTI_TENANT", "1");
        let audit_path = workspace.path().join("security_audit.jsonl");
        let _audit = RestoreVar::set(
            "OPENFDD_AUDIT_LOG_PATH",
            audit_path.to_str().expect("audit path"),
        );
        let fixture = write_fixture(workspace.path());
        let stored = log_text(workspace.path());
        assert!(stored.contains("\"tenant_id\":\"tenant-a\""));
        assert!(stored.contains("\"tenant_id\":\"tenant-b\""));
        assert!(stored.contains(&fixture.marker_legacy_b));

        let mut state = AppState::new();
        state.auth = AuthConfig {
            secret: Some("actions-scope-test-secret-0123456789".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = crate::routes::router(Arc::clone(&state));
        let tokens = tokens(&state);
        assert_lists(&app, &tokens, &fixture).await;
        assert_denied_and_owned_deletes(&app, &tokens, &fixture, workspace.path(), &audit_path)
            .await;
        assert_hub_admin_clears_remaining(&app, &tokens, &fixture, workspace.path(), &audit_path)
            .await;
    }

    async fn assert_lists(app: &axum::Router, tokens: &Tokens, fixture: &Fixture) {
        let (status, _) = send(app.clone(), "GET", "/api/actions?limit=50", None).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        for token in [&tokens.viewer_a, &tokens.operator_a, &tokens.admin_a] {
            let (status, body) =
                send(app.clone(), "GET", "/api/actions?limit=50", Some(token)).await;
            assert_eq!(status, StatusCode::OK);
            assert_eq!(body["ok"], true);
            assert_only_a(&body, fixture);
        }

        let (status, body) = send(
            app.clone(),
            "GET",
            "/api/actions?limit=50",
            Some(&tokens.hub),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let hub_ids = listed_ids(&body);
        assert!(hub_ids.contains(&fixture.id_a));
        assert!(hub_ids.contains(&fixture.id_b));
        assert!(hub_ids.contains(&fixture.id_legacy_b));
        let hub_body = body.to_string();
        assert!(hub_body.contains(&fixture.marker_a));
        assert!(hub_body.contains(&fixture.marker_b));
        assert!(hub_body.contains(&fixture.marker_legacy_b));
    }

    async fn assert_denied_and_owned_deletes(
        app: &axum::Router,
        tokens: &Tokens,
        fixture: &Fixture,
        workspace: &Path,
        audit_path: &Path,
    ) {
        let before = log_text(workspace);
        let (status, body) = send(
            app.clone(),
            "DELETE",
            &format!("/api/actions/{}", fixture.id_a),
            Some(&tokens.viewer_a),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert_eq!(body["ok"], false);
        assert_eq!(log_text(workspace), before);
        let (status, _) = send(
            app.clone(),
            "DELETE",
            "/api/actions",
            Some(&tokens.viewer_a),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert_eq!(log_text(workspace), before);

        let (status, body) = send(
            app.clone(),
            "DELETE",
            &format!("/api/actions/{}", fixture.id_b),
            Some(&tokens.operator_a),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert_eq!(body["ok"], false);
        assert!(!body.to_string().contains(&fixture.marker_b));
        assert_eq!(log_text(workspace), before);
        let (status, _) = send(
            app.clone(),
            "DELETE",
            &format!("/api/actions/{}", fixture.id_legacy_b),
            Some(&tokens.operator_a),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert_eq!(log_text(workspace), before);

        let (status, body) = send(
            app.clone(),
            "DELETE",
            &format!("/api/actions/{}", fixture.id_a),
            Some(&tokens.operator_a),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["ok"], true);
        assert_eq!(body["deleted"], fixture.id_a);
        assert_eq!(body["remaining"], 0);
        let after_one = log_text(workspace);
        assert!(!after_one.contains(&fixture.marker_a));
        assert!(!after_one.contains(&fixture.id_a));
        assert!(after_one.contains(&fixture.marker_b));
        assert!(after_one.contains(&fixture.marker_legacy_b));

        let deleted = audit_events(audit_path)
            .into_iter()
            .find(|event| {
                event["action"] == "actions.delete"
                    && event["outcome"] == "ok"
                    && event["target_id"] == fixture.id_a
            })
            .expect("delete audit");
        assert_eq!(deleted["actor"], "tenant-a-operator");
        assert_eq!(deleted["role"], "operator");
        assert_eq!(deleted["decision"], "allow");
        assert_eq!(deleted["tenant_id"], "tenant-a");
        assert_eq!(deleted["site_id"], "site-a");
        assert_eq!(removed_ids(&deleted), vec![fixture.id_a.clone()]);
        let events = audit_events(audit_path);
        assert!(events.iter().any(|event| {
            event["action"] == "actions.delete"
                && event["decision"] == "deny"
                && event["reason"] == "role_required"
                && event["actor"] == "tenant-a-viewer"
                && event["role"] == "viewer"
                && event["target_id"] == fixture.id_a
        }));
        assert!(events.iter().any(|event| {
            event["action"] == "actions.clear"
                && event["decision"] == "deny"
                && event["actor"] == "tenant-a-viewer"
        }));
        assert!(events.iter().any(|event| {
            event["decision"] == "deny"
                && event["reason"] == "tenant_scope"
                && event["actor"] == "tenant-a-operator"
                && event["target_id"] == fixture.id_b
        }));

        let (status, body) = send(
            app.clone(),
            "DELETE",
            "/api/actions",
            Some(&tokens.operator_a),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["deleted_count"], 0);
        let after_clear = log_text(workspace);
        assert!(after_clear.contains(&fixture.marker_b));
        assert!(after_clear.contains(&fixture.marker_legacy_b));
        assert!(audit_events(audit_path).iter().any(|event| {
            event["action"] == "actions.clear"
                && event["outcome"] == "ok"
                && event["actor"] == "tenant-a-operator"
                && event["change"]["action_ids"]["total"] == 0
        }));
    }

    async fn assert_hub_admin_clears_remaining(
        app: &axum::Router,
        tokens: &Tokens,
        fixture: &Fixture,
        workspace: &Path,
        audit_path: &Path,
    ) {
        let (status, body) = send(
            app.clone(),
            "DELETE",
            &format!("/api/actions/{}", fixture.id_b),
            Some(&tokens.hub),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["deleted"], fixture.id_b);
        let after_hub = log_text(workspace);
        assert!(!after_hub.contains(&fixture.marker_b));
        assert!(after_hub.contains(&fixture.marker_legacy_b));

        let (status, _) = send(app.clone(), "DELETE", "/api/actions", Some(&tokens.hub)).await;
        assert_eq!(status, StatusCode::OK);
        let cleared = log_text(workspace);
        assert!(!cleared.contains(&fixture.marker_a));
        assert!(!cleared.contains(&fixture.marker_b));
        assert!(!cleared.contains(&fixture.marker_legacy_b));
        assert!(!cleared.contains("actions.delete"));
        assert!(!cleared.contains("actions.clear"));
        assert!(audit_events(audit_path).iter().any(|event| {
            event["actor"] == "tenant-a-operator"
                && event["tenant_id"] == "tenant-a"
                && event["target_id"] == fixture.id_a
                && event["outcome"] == "ok"
        }));
        assert!(audit_events(audit_path).iter().any(|event| {
            event["action"] == "actions.clear"
                && event["actor"] == "hub-admin"
                && event["outcome"] == "ok"
                && removed_ids(event).contains(&fixture.id_legacy_b)
        }));
    }

    #[test]
    fn row_without_tenant_or_site_stays_hidden_from_members() {
        let scope = CallerScope {
            role: Role::Viewer,
            tenant_ids: vec!["tenant-a".into()],
            sees_all: false,
        };
        let plane = ControlPlane {
            tenants: vec![TenantRecord {
                id: "tenant-a".into(),
                name: "Tenant A".into(),
                building_ids: vec!["site-a".into()],
            }],
        };
        let blank = ActionEntry {
            id: "act-blank".into(),
            kind: "package_import".into(),
            label: "blank".into(),
            started_at: "2026-01-01T00:00:00.000Z".into(),
            finished_at: None,
            duration_ms: None,
            status: "ok".into(),
            detail: None,
            tenant_id: None,
            building_id: None,
        };
        assert!(!entry_visible(&scope, &plane, &blank));
    }
}
