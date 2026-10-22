//! JWT authentication and RBAC for the central control plane.

use std::sync::Arc;

use axum::extract::{Request, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use tracing::warn;
use utoipa::ToSchema;

use crate::state::AppState;
use crate::user_store::{UserRecord, UserStore, UserStoreLoad};

const VALID_ROLES: &[&str] = &["viewer", "operator", "admin"];
const IDENTITY_STORE_UNAVAILABLE: &str = "identity store unavailable";

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    constant_time_eq_bytes(a, b)
}

/// Shared with [`crate::user_store`] for file-plane password compare.
pub(crate) fn constant_time_eq_bytes(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Viewer,
    Operator,
    Admin,
}

impl Role {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "viewer" => Some(Self::Viewer),
            "operator" => Some(Self::Operator),
            "admin" => Some(Self::Admin),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Viewer => "viewer",
            Self::Operator => "operator",
            Self::Admin => "admin",
        }
    }

    pub fn can_issue_commands(self) -> bool {
        matches!(self, Self::Operator | Self::Admin)
    }
}

impl std::fmt::Display for Role {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct JwtClaims {
    pub sub: String,
    pub role: String,
    pub exp: i64,
    #[serde(default)]
    pub iat: i64,
    /// Durable tenant membership when multi-tenant mode is on.
    /// Empty means a hub-wide admin or an unbound identity.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tenant_ids: Vec<String>,
    /// Active tenant for this session. Membership stays in `tenant_ids`.
    /// Tokens minted before this field use the first membership as the active tenant.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_tenant_id: Option<String>,
    /// File-plane session epoch (S09). Env identities always mint/verify as 0.
    #[serde(default, rename = "sv")]
    pub session_version: u64,
    /// File-plane record id. Absent on env identities and on tokens that were never file-issued.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uid: Option<String>,
}

pub(crate) fn is_env_identity(sub: &str) -> bool {
    matches!(
        sub.trim().to_ascii_lowercase().as_str(),
        "admin" | "agent" | "viewer" | "dev"
    )
}

fn workspace_dir() -> std::path::PathBuf {
    std::path::PathBuf::from(
        std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into()),
    )
}

fn bound_uid(uid: &Option<String>) -> Option<&str> {
    uid.as_deref().map(str::trim).filter(|s| !s.is_empty())
}

struct FilePlaneBinding {
    session_version: u64,
    uid: Option<String>,
    /// Live file-plane membership. Absent for env identities and unbound subjects.
    durable_tenant_ids: Option<Vec<String>>,
}

/// Session epoch, record id, and durable membership to embed.
/// Env identities stay unbound. A subject that is not in the store and was never
/// retired stays unbound so direct-mint callers keep working. A retired name is refused.
fn file_plane_binding(sub: &str) -> Result<FilePlaneBinding, String> {
    if is_env_identity(sub) {
        return Ok(FilePlaneBinding {
            session_version: 0,
            uid: None,
            durable_tenant_ids: None,
        });
    }
    let workspace = workspace_dir();
    match UserStore::load_status(&workspace) {
        UserStoreLoad::Absent => Ok(FilePlaneBinding {
            session_version: 0,
            uid: None,
            durable_tenant_ids: None,
        }),
        UserStoreLoad::Unreadable => {
            warn!("control-plane user store is unreadable; refusing to mint a file token");
            Err(IDENTITY_STORE_UNAVAILABLE.into())
        }
        UserStoreLoad::Ready(mut store) => {
            let Some(idx) = store
                .users
                .iter()
                .position(|u| u.username.eq_ignore_ascii_case(sub))
            else {
                if store.is_retired(sub) {
                    return Err("identity unknown".into());
                }
                return Ok(FilePlaneBinding {
                    session_version: 0,
                    uid: None,
                    durable_tenant_ids: None,
                });
            };
            if store.users[idx].disabled {
                return Err("identity disabled".into());
            }
            if store.users[idx].user_id.trim().is_empty() {
                store.users[idx].user_id = uuid::Uuid::new_v4().to_string();
                store.save(&workspace)?;
            }
            Ok(FilePlaneBinding {
                session_version: store.users[idx].session_version,
                uid: Some(store.users[idx].user_id.clone()),
                durable_tenant_ids: Some(store.users[idx].tenant_ids.clone()),
            })
        }
    }
}

/// Membership claim plus the active tenant for a newly minted session.
///
/// A single requested id that belongs to the stored membership selects that
/// tenant and keeps the stored list. A longer requested list (login) keeps the
/// stored list and activates its first id. Requests that are not a subset of
/// the stored membership are left unchanged so verification can reject them.
fn minted_session(
    requested: &[String],
    durable: Option<&[String]>,
) -> (Vec<String>, Option<String>) {
    let requested_clean: Vec<String> = requested
        .iter()
        .map(|id| id.trim())
        .filter(|id| !id.is_empty())
        .map(str::to_string)
        .collect();
    let Some(durable) = durable else {
        let active = requested_clean.first().cloned();
        return (requested_clean, active);
    };
    let subset = !requested_clean.is_empty()
        && requested_clean
            .iter()
            .all(|id| durable.iter().any(|have| have == id));
    if !subset {
        let active = requested_clean.first().cloned();
        return (requested_clean, active);
    }
    let active = if requested_clean.len() == 1 {
        requested_clean.first().cloned()
    } else {
        durable.first().cloned()
    };
    (durable.to_vec(), active)
}

#[derive(Debug, Clone)]
pub struct AuthUser {
    pub sub: String,
    pub role: Role,
    /// Durable membership. A file-plane user carries the stored list.
    pub tenant_ids: Vec<String>,
    /// Active tenant for this session, when the token names one.
    pub active_tenant_id: Option<String>,
}

impl AuthUser {
    pub fn dev_anonymous() -> Self {
        Self {
            sub: "dev".into(),
            role: Role::Admin,
            tenant_ids: vec![],
            active_tenant_id: None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct AuthConfig {
    pub secret: Option<String>,
    /// Optional plaintext admin password for `POST /api/auth/login` (bench / remote UI).
    pub admin_password: Option<String>,
    /// Optional agent password for FDD AI assistance (`username=agent` → operator JWT).
    /// Prefer this on Railway over sharing the admin password with MCP hosts.
    pub agent_password: Option<String>,
    /// Optional viewer password (`username=viewer` → viewer JWT, read-only RBAC).
    /// When MT ON, set `OPENFDD_VIEWER_TENANT_IDS` (comma-separated) for scoped membership;
    /// empty list remains deny-all under MT (not hub-wide). Prefer file users for multi-viewer sites.
    /// Unset password → viewer password login disabled.
    pub viewer_password: Option<String>,
    /// Optional tenant membership for the env `viewer` password identity.
    pub viewer_tenant_ids: Vec<String>,
}

pub fn is_loopback_bind(host: &str) -> bool {
    matches!(
        host.trim(),
        "127.0.0.1" | "::1" | "localhost" | "localhost.localdomain"
    )
}

/// Fail closed when Central is reachable off-loopback without a strong secret + admin identity.
pub fn assert_bind_auth_policy(
    host: &str,
    secret: Option<&str>,
    admin_password: Option<&str>,
) -> Result<(), String> {
    if is_loopback_bind(host) {
        return Ok(());
    }
    if std::env::var("OPENFDD_ALLOW_OPEN_BIND")
        .ok()
        .filter(|s| matches!(s.trim(), "1" | "true" | "yes"))
        .is_some()
    {
        warn!(
            "OPENFDD_ALLOW_OPEN_BIND=1 — open mode allowed on non-loopback (CI/smoke only; not internet-ready)"
        );
        return Ok(());
    }
    let secret = secret.map(str::trim).filter(|s| !s.is_empty());
    let Some(secret) = secret else {
        return Err(
            "fail-closed: non-loopback bind requires OPENFDD_JWT_SECRET (open mode is loopback-only)"
                .into(),
        );
    };
    if secret.len() < 32 {
        return Err(
            "fail-closed: OPENFDD_JWT_SECRET must be at least 32 characters on non-loopback binds"
                .into(),
        );
    }
    if admin_password
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .is_none()
    {
        return Err(
            "fail-closed: non-loopback bind requires OPENFDD_ADMIN_PASSWORD (admin identity)"
                .into(),
        );
    }
    Ok(())
}

impl AuthConfig {
    pub fn load() -> Self {
        let secret = std::env::var("OPENFDD_JWT_SECRET")
            .ok()
            .filter(|s| !s.trim().is_empty());
        let admin_password = std::env::var("OPENFDD_ADMIN_PASSWORD")
            .ok()
            .filter(|s| !s.trim().is_empty());
        let agent_password = std::env::var("OPENFDD_AGENT_PASSWORD")
            .ok()
            .filter(|s| !s.trim().is_empty());
        let viewer_password = std::env::var("OPENFDD_VIEWER_PASSWORD")
            .ok()
            .filter(|s| !s.trim().is_empty());
        let viewer_tenant_ids: Vec<String> = std::env::var("OPENFDD_VIEWER_TENANT_IDS")
            .ok()
            .map(|s| {
                s.split(',')
                    .map(str::trim)
                    .filter(|t| !t.is_empty())
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        if secret.is_none() {
            warn!("auth_enabled=false (OPENFDD_JWT_SECRET unset) — open mode is loopback-only");
        } else {
            tracing::info!(
                auth_enabled = true,
                "JWT auth configured (secret not logged)"
            );
            if admin_password.is_none() {
                warn!(
                    "OPENFDD_ADMIN_PASSWORD unset — UI login will fail until password is configured"
                );
            }
            if agent_password.is_none() {
                warn!(
                    "OPENFDD_AGENT_PASSWORD unset — Railway/MCP agents should use a dedicated agent password (username=agent), not admin"
                );
            }
            if viewer_password.is_none() {
                warn!(
                    "OPENFDD_VIEWER_PASSWORD unset — viewer password login disabled (RBAC role still mintable via JWT)"
                );
            }
        }
        Self {
            secret,
            admin_password,
            agent_password,
            viewer_password,
            viewer_tenant_ids,
        }
    }

    pub fn required(&self) -> bool {
        self.secret.is_some()
    }

    /// Mint a JWT with durable membership and a separate active tenant.
    ///
    /// File-plane subjects embed `uid` plus the current `session_version`, so a
    /// disabled, removed, or recreated account no longer matches. Env identities
    /// (`admin` / `agent` / `viewer` / `dev`) stay unbound and always use
    /// session_version 0. Passing one stored membership id selects that tenant
    /// and keeps the rest of the stored membership on the token.
    pub fn issue_token_with_tenants(
        &self,
        sub: &str,
        role: Role,
        ttl_secs: i64,
        tenant_ids: &[String],
    ) -> Result<String, String> {
        use jsonwebtoken::{encode, EncodingKey, Header};
        let secret = self
            .secret
            .as_ref()
            .ok_or_else(|| "auth not configured".to_string())?;
        let now = chrono::Utc::now().timestamp();
        let binding = file_plane_binding(sub)?;
        let (membership, active_tenant_id) =
            minted_session(tenant_ids, binding.durable_tenant_ids.as_deref());
        let claims = JwtClaims {
            sub: sub.to_string(),
            role: role.as_str().to_string(),
            exp: now + ttl_secs.max(60),
            iat: now,
            tenant_ids: membership,
            active_tenant_id,
            session_version: binding.session_version,
            uid: binding.uid,
        };
        encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(secret.as_bytes()),
        )
        .map_err(|e| format!("token mint failed: {e}"))
    }

    /// Decode bearer claims after signature/exp validation (S09 parent TTL ceiling).
    pub fn decode_claims(&self, token: &str) -> Result<JwtClaims, String> {
        let secret = self
            .secret
            .as_ref()
            .ok_or_else(|| "auth not configured".to_string())?;
        let mut validation = Validation::new(Algorithm::HS256);
        validation.validate_aud = false;
        validation.validate_exp = true;
        let data = decode::<JwtClaims>(
            token,
            &DecodingKey::from_secret(secret.as_bytes()),
            &validation,
        )
        .map_err(|e| format!("invalid token: {e}"))?;
        Ok(data.claims)
    }

    /// Validate username/password for UI / agent login.
    /// Returns `(subject, role, tenant_ids)`.
    /// - `admin` + `OPENFDD_ADMIN_PASSWORD` → Admin, empty tenant_ids (hub_admin when MT ON)
    /// - `agent` + `OPENFDD_AGENT_PASSWORD` → Operator, empty tenant_ids (deployment-wide; prefer file users when MT ON)
    /// - `viewer` + `OPENFDD_VIEWER_PASSWORD` → Viewer, tenant_ids from `OPENFDD_VIEWER_TENANT_IDS` (may be empty)
    /// - Wave N file users (`control_plane/users.json`) → role + non-empty tenant_ids
    pub fn authenticate_password(
        &self,
        username: &str,
        password: &str,
    ) -> Result<(String, Role, Vec<String>), String> {
        let user = username.trim();
        if user.eq_ignore_ascii_case("admin") {
            let expected = self
                .admin_password
                .as_ref()
                .ok_or_else(|| "login not configured (set OPENFDD_ADMIN_PASSWORD)".to_string())?;
            if !constant_time_eq(expected.as_bytes(), password.as_bytes()) {
                return Err("invalid credentials".into());
            }
            return Ok(("admin".into(), Role::Admin, vec![]));
        }
        if user.eq_ignore_ascii_case("agent") {
            let expected = self.agent_password.as_ref().ok_or_else(|| {
                "agent login not configured (set OPENFDD_AGENT_PASSWORD)".to_string()
            })?;
            if !constant_time_eq(expected.as_bytes(), password.as_bytes()) {
                return Err("invalid credentials".into());
            }
            return Ok(("agent".into(), Role::Operator, vec![]));
        }
        if user.eq_ignore_ascii_case("viewer") {
            let expected = self.viewer_password.as_ref().ok_or_else(|| {
                "viewer login not configured (set OPENFDD_VIEWER_PASSWORD)".to_string()
            })?;
            if !constant_time_eq(expected.as_bytes(), password.as_bytes()) {
                return Err("invalid credentials".into());
            }
            return Ok((
                "viewer".into(),
                Role::Viewer,
                self.viewer_tenant_ids.clone(),
            ));
        }
        let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
        if let Some((sub, role, tids)) =
            crate::user_store::UserStore::load_or_empty(std::path::Path::new(&workspace))
                .authenticate(user, password)
        {
            return Ok((sub, role, tids));
        }
        Err("invalid credentials".into())
    }

    pub fn verify_bearer(&self, token: &str) -> Result<AuthUser, String> {
        let claims = self.decode_claims(token)?;
        let role = Role::parse(&claims.role).ok_or_else(|| {
            format!(
                "invalid role {}; expected one of {VALID_ROLES:?}",
                claims.role
            )
        })?;
        // File-issued tokens carry `uid` and must match a live enabled record.
        // Env identities are explicit and do not consult the file. An unreadable
        // store fails closed for every other subject.
        let scope = authorize_file_plane(&claims, role)?;
        Ok(AuthUser {
            sub: claims.sub,
            role,
            tenant_ids: scope.tenant_ids,
            active_tenant_id: scope.active_tenant_id,
        })
    }

    pub fn user_from_headers(&self, headers: &HeaderMap) -> Result<AuthUser, String> {
        if self.secret.is_none() {
            return Ok(AuthUser::dev_anonymous());
        }
        let auth = headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .ok_or_else(|| "Authorization: Bearer <token> required".to_string())?;
        let token = auth
            .strip_prefix("Bearer ")
            .or_else(|| auth.strip_prefix("bearer "))
            .ok_or_else(|| "Authorization must be Bearer token".to_string())?;
        self.verify_bearer(token.trim())
    }
}

struct SessionScope {
    tenant_ids: Vec<String>,
    active_tenant_id: Option<String>,
}

fn authorize_file_plane(claims: &JwtClaims, role: Role) -> Result<SessionScope, String> {
    if is_env_identity(&claims.sub) {
        return Ok(scope_from_claims(claims));
    }
    let workspace = workspace_dir();
    match UserStore::load_status(&workspace) {
        UserStoreLoad::Unreadable => {
            warn!("control-plane user store is unreadable; rejecting token");
            Err(IDENTITY_STORE_UNAVAILABLE.into())
        }
        UserStoreLoad::Absent => {
            if bound_uid(&claims.uid).is_some() {
                warn!("control-plane user store is missing; rejecting bound token");
                Err(IDENTITY_STORE_UNAVAILABLE.into())
            } else {
                Ok(scope_from_claims(claims))
            }
        }
        UserStoreLoad::Ready(store) => authorize_loaded(&store, claims, role),
    }
}

fn authorize_loaded(
    store: &UserStore,
    claims: &JwtClaims,
    role: Role,
) -> Result<SessionScope, String> {
    let uid = bound_uid(&claims.uid);
    match store.get(&claims.sub) {
        Some(rec) => {
            if let Some(uid) = uid {
                if rec.user_id != uid {
                    return Err("identity unknown".into());
                }
            }
            live_record_ok(rec, claims, role)?;
            Ok(scope_for_live_record(rec, claims))
        }
        None if uid.is_some() || store.is_retired(&claims.sub) => Err("identity unknown".into()),
        None => Ok(scope_from_claims(claims)),
    }
}

fn live_record_ok(rec: &UserRecord, claims: &JwtClaims, role: Role) -> Result<(), String> {
    if rec.disabled {
        return Err("identity disabled".into());
    }
    if rec.session_version != claims.session_version {
        return Err("session revoked".into());
    }
    let store_role =
        Role::parse(rec.role.trim()).ok_or_else(|| "identity role invalid".to_string())?;
    if store_role != role {
        return Err("session revoked".into());
    }
    if claims
        .tenant_ids
        .iter()
        .any(|tid| !rec.tenant_ids.iter().any(|have| have == tid))
    {
        return Err("session revoked".into());
    }
    if let Some(active) = claims
        .active_tenant_id
        .as_deref()
        .map(str::trim)
        .filter(|id| !id.is_empty())
    {
        if !rec.tenant_ids.iter().any(|have| have == active) {
            return Err("session revoked".into());
        }
    }
    Ok(())
}

fn nonempty_active(raw: Option<&str>) -> Option<&str> {
    raw.map(str::trim).filter(|id| !id.is_empty())
}

/// Scope taken from the token itself. Used for env identities and unbound subjects.
fn scope_from_claims(claims: &JwtClaims) -> SessionScope {
    let active = nonempty_active(claims.active_tenant_id.as_deref())
        .map(str::to_string)
        .or_else(|| claims.tenant_ids.first().cloned());
    SessionScope {
        tenant_ids: claims.tenant_ids.clone(),
        active_tenant_id: active,
    }
}

/// File-plane scope. A token that names at least one stored tenant keeps that
/// active tenant and returns the stored membership. A token with no stored
/// tenant id keeps its own claims.
fn scope_for_live_record(rec: &UserRecord, claims: &JwtClaims) -> SessionScope {
    let claimed: Vec<&String> = claims
        .tenant_ids
        .iter()
        .filter(|id| rec.tenant_ids.iter().any(|have| have == *id))
        .collect();
    if claimed.is_empty() {
        return scope_from_claims(claims);
    }
    let active = nonempty_active(claims.active_tenant_id.as_deref())
        .filter(|id| rec.tenant_ids.iter().any(|have| have == id))
        .map(str::to_string)
        .or_else(|| claimed.first().map(|id| (*id).clone()));
    SessionScope {
        tenant_ids: rec.tenant_ids.clone(),
        active_tenant_id: active,
    }
}

/// Identity rejection is 401. A missing or unreadable user store is 503.
/// Neither status accepts the token.
pub(crate) fn auth_failure_status(detail: &str) -> StatusCode {
    if detail == IDENTITY_STORE_UNAVAILABLE {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::UNAUTHORIZED
    }
}

pub async fn jwt_middleware(
    State(state): State<Arc<AppState>>,
    mut req: Request,
    next: Next,
) -> Response {
    match state.auth.user_from_headers(req.headers()) {
        Ok(user) => {
            req.extensions_mut().insert(user);
            next.run(req).await
        }
        Err(detail) => {
            let status = auth_failure_status(&detail);
            (
                status,
                axum::Json(serde_json::json!({"ok": false, "error": detail})),
            )
                .into_response()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::user_store::{UserRecord, UserStore, UserStoreLoad};
    use jsonwebtoken::{encode, EncodingKey, Header};

    #[test]
    fn roundtrip_jwt() {
        let _g = crate::test_env_lock::lock_env();
        let cfg = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        };
        let claims = JwtClaims {
            sub: "operator".into(),
            role: "operator".into(),
            exp: chrono::Utc::now().timestamp() + 3600,
            iat: chrono::Utc::now().timestamp(),
            tenant_ids: vec![],
            active_tenant_id: None,
            session_version: 0,
            uid: None,
        };
        let token = encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(cfg.secret.as_ref().unwrap().as_bytes()),
        )
        .unwrap();
        let user = cfg.verify_bearer(&token).unwrap();
        assert_eq!(user.sub, "operator");
        assert_eq!(user.role, Role::Operator);
    }

    #[test]
    fn rejects_unknown_role() {
        let cfg = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        };
        let claims = JwtClaims {
            sub: "x".into(),
            role: "integrator".into(),
            exp: chrono::Utc::now().timestamp() + 3600,
            iat: chrono::Utc::now().timestamp(),
            tenant_ids: vec![],
            active_tenant_id: None,
            session_version: 0,
            uid: None,
        };
        let token = encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(cfg.secret.as_ref().unwrap().as_bytes()),
        )
        .unwrap();
        assert!(cfg.verify_bearer(&token).is_err());
    }

    #[test]
    fn rbac_viewer_read_only_operator_admin_mutate() {
        let cases = [
            (Role::Viewer, false),
            (Role::Operator, true),
            (Role::Admin, true),
        ];
        for (role, can_mutate) in cases {
            assert_eq!(role.can_issue_commands(), can_mutate, "{role}");
        }
    }

    #[test]
    fn non_loopback_fails_closed_without_secret() {
        assert!(assert_bind_auth_policy("0.0.0.0", None, Some("pw")).is_err());
        assert!(assert_bind_auth_policy("0.0.0.0", Some("short"), Some("pw")).is_err());
        assert!(
            assert_bind_auth_policy("0.0.0.0", Some("abcdefghijklmnopqrstuvwxyz012345"), None)
                .is_err()
        );
        assert!(assert_bind_auth_policy(
            "0.0.0.0",
            Some("abcdefghijklmnopqrstuvwxyz012345"),
            Some("admin-pw")
        )
        .is_ok());
        assert!(assert_bind_auth_policy("127.0.0.1", None, None).is_ok());
    }

    #[test]
    fn allow_open_bind_escape_hatch() {
        // Covered by env in integration; unit: loopback still ok.
        assert!(is_loopback_bind("localhost"));
    }

    #[test]
    fn agent_password_mints_operator_not_admin() {
        let cfg = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: Some("admin-pw".into()),
            agent_password: Some("agent-pw".into()),
            viewer_password: Some("viewer-pw".into()),
            viewer_tenant_ids: vec![],
        };
        let (sub, role, tids) = cfg.authenticate_password("agent", "agent-pw").unwrap();
        assert_eq!(sub, "agent");
        assert_eq!(role, Role::Operator);
        assert!(tids.is_empty());
        assert!(cfg.authenticate_password("agent", "admin-pw").is_err());
        assert!(cfg.authenticate_password("admin", "agent-pw").is_err());
        let (admin_sub, admin_role, admin_tids) =
            cfg.authenticate_password("admin", "admin-pw").unwrap();
        assert_eq!(admin_sub, "admin");
        assert_eq!(admin_role, Role::Admin);
        assert!(admin_tids.is_empty());
        let (viewer_sub, viewer_role, viewer_tids) =
            cfg.authenticate_password("viewer", "viewer-pw").unwrap();
        assert_eq!(viewer_sub, "viewer");
        assert_eq!(viewer_role, Role::Viewer);
        assert!(viewer_tids.is_empty());
        assert!(cfg.authenticate_password("viewer", "admin-pw").is_err());

        let scoped = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: Some("viewer-pw".into()),
            viewer_tenant_ids: vec!["acme".into()],
        };
        let (_, _, scoped_tids) = scoped.authenticate_password("viewer", "viewer-pw").unwrap();
        assert_eq!(scoped_tids, vec!["acme".to_string()]);
    }

    #[test]
    fn agent_login_requires_configured_password() {
        let cfg = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: Some("admin-pw".into()),
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        };
        assert!(cfg.authenticate_password("agent", "anything").is_err());
        assert!(cfg.authenticate_password("viewer", "anything").is_err());
    }

    /// Phase 3 — ephemeral harness key through the real product verifier.
    /// Audience validation stays off (current auth contract); document gaps rather
    /// than inventing unsupported issuer/JWK behavior.
    fn harness_auth() -> AuthConfig {
        AuthConfig {
            secret: Some("harness-isolated-ephemeral-key-32b!!".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        }
    }

    fn mint_with(
        secret: &str,
        sub: &str,
        role: &str,
        exp: i64,
        iat: i64,
        tenant_ids: Vec<String>,
    ) -> String {
        let claims = JwtClaims {
            sub: sub.into(),
            role: role.into(),
            exp,
            iat,
            tenant_ids,
            active_tenant_id: None,
            session_version: 0,
            uid: None,
        };
        encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(secret.as_bytes()),
        )
        .expect("mint")
    }

    #[test]
    fn phase3_accepts_ephemeral_valid_token() {
        let _g = crate::test_env_lock::lock_env();
        let cfg = harness_auth();
        let now = chrono::Utc::now().timestamp();
        let token = mint_with(
            cfg.secret.as_ref().unwrap(),
            "harness-user",
            "operator",
            now + 600,
            now,
            vec!["tenant-a".into()],
        );
        let user = cfg.verify_bearer(&token).expect("valid token");
        assert_eq!(user.sub, "harness-user");
        assert_eq!(user.role, Role::Operator);
        assert_eq!(user.tenant_ids, vec!["tenant-a".to_string()]);
    }

    #[test]
    fn phase3_rejects_identical_claims_with_past_exp() {
        let _g = crate::test_env_lock::lock_env();
        let cfg = harness_auth();
        let now = chrono::Utc::now().timestamp();
        let secret = cfg.secret.as_ref().unwrap();
        let good = mint_with(secret, "harness-user", "operator", now + 600, now, vec![]);
        let expired = mint_with(
            secret,
            "harness-user",
            "operator",
            now - 120,
            now - 3600,
            vec![],
        );
        assert!(cfg.verify_bearer(&good).is_ok());
        assert!(cfg.verify_bearer(&expired).is_err());
    }

    #[test]
    fn phase3_rejects_wrong_key_alg_none_and_tampered_payload() {
        let cfg = harness_auth();
        let now = chrono::Utc::now().timestamp();
        let secret = cfg.secret.as_ref().unwrap();
        let good = mint_with(secret, "harness-user", "viewer", now + 600, now, vec![]);

        let other = AuthConfig {
            secret: Some("different-ephemeral-harness-key-32b!".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        };
        assert!(other.verify_bearer(&good).is_err(), "wrong key must reject");

        // alg=none with empty signature — HS256-only validator must reject.
        // Fixed fixture token (header.alg=none, role=admin, far-future exp).
        let alg_none = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJoYXJuZXNzLXVzZXIiLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3MDAwMDAwMDAsImV4cCI6OTk5OTk5OTk5OX0.";
        assert!(
            cfg.verify_bearer(alg_none).is_err(),
            "alg=none must not authenticate"
        );

        // Mutate payload segment without re-signing → signature fails.
        let parts: Vec<&str> = good.split('.').collect();
        assert_eq!(parts.len(), 3);
        let mut payload_chars: Vec<u8> = parts[1].as_bytes().to_vec();
        let mid = payload_chars.len() / 2;
        payload_chars[mid] = if payload_chars[mid] == b'A' {
            b'B'
        } else {
            b'A'
        };
        let tampered = format!(
            "{}.{}.{}",
            parts[0],
            std::str::from_utf8(&payload_chars).expect("b64url ascii"),
            parts[2]
        );
        assert_ne!(good, tampered, "tamper must change token bytes");
        assert!(
            cfg.verify_bearer(&tampered).is_err(),
            "tampered payload must not authenticate"
        );
    }

    #[test]
    fn s09_file_plane_disable_revokes_outstanding_token() {
        use crate::test_env_lock::lock_env;
        use crate::user_store::{UserRecord, UserStore};
        use tempfile::tempdir;

        let _g = lock_env();
        let dir = tempdir().unwrap();
        let cp = dir.path().join("openfdd/control_plane");
        std::fs::create_dir_all(&cp).unwrap();
        let mut store = UserStore::default();
        store
            .upsert(UserRecord {
                username: "acme-ops".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("secret".into()),
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        store.save(dir.path()).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let cfg = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        };
        let token = cfg
            .issue_token_with_tenants("acme-ops", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        assert!(cfg.verify_bearer(&token).is_ok());

        let mut store = UserStore::load_or_empty(dir.path());
        store.set_disabled("acme-ops", true).unwrap();
        store.save(dir.path()).unwrap();
        let err = cfg.verify_bearer(&token).expect_err("disabled must revoke");
        assert!(
            err.contains("disabled") || err.contains("revoked"),
            "unexpected err: {err}"
        );

        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    #[test]
    fn s09_role_change_bumps_session_and_revokes_token() {
        use crate::test_env_lock::lock_env;
        use crate::user_store::{UserRecord, UserStore};
        use tempfile::tempdir;

        let _g = lock_env();
        let dir = tempdir().unwrap();
        let mut store = UserStore::default();
        store
            .upsert(UserRecord {
                username: "acme-ops".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("secret".into()),
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        store.save(dir.path()).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let cfg = AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        };
        let token = cfg
            .issue_token_with_tenants("acme-ops", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        assert!(cfg.verify_bearer(&token).is_ok());

        let mut store = UserStore::load_or_empty(dir.path());
        store
            .upsert(UserRecord {
                username: "acme-ops".into(),
                user_id: String::new(),
                role: "viewer".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: None,
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        assert_eq!(store.users[0].session_version, 1);
        store.save(dir.path()).unwrap();
        assert!(cfg.verify_bearer(&token).is_err());

        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    fn file_cfg() -> AuthConfig {
        AuthConfig {
            secret: Some("test-secret-with-enough-entropy-for-hmac-signing".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: vec![],
        }
    }

    fn operator_record(username: &str) -> UserRecord {
        UserRecord {
            username: username.into(),
            user_id: String::new(),
            role: "operator".into(),
            tenant_ids: vec!["acme".into()],
            password_env: None,
            password: Some("secret".into()),
            disabled: false,
            session_version: 0,
        }
    }

    fn save_operator(dir: &std::path::Path, username: &str) {
        let mut store = match UserStore::load_status(dir) {
            UserStoreLoad::Ready(store) => store,
            UserStoreLoad::Absent => UserStore::default(),
            UserStoreLoad::Unreadable => panic!("test setup saw an unreadable user store"),
        };
        store.upsert(operator_record(username)).unwrap();
        store.save(dir).unwrap();
    }

    #[test]
    fn file_token_dies_on_delete_disable_recreate_and_bad_store() {
        use crate::test_env_lock::{lock_env, WorkspaceEnv};
        use jsonwebtoken::{encode, EncodingKey, Header};

        let _g = lock_env();
        let dir = tempfile::tempdir().unwrap();
        let _ws = WorkspaceEnv::set(dir.path());
        save_operator(dir.path(), "acme-del");
        save_operator(dir.path(), "acme-off");
        save_operator(dir.path(), "acme-new");
        save_operator(dir.path(), "acme-store");

        let cfg = file_cfg();
        let deleted = cfg
            .issue_token_with_tenants("acme-del", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        let disabled = cfg
            .issue_token_with_tenants("acme-off", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        let recreated = cfg
            .issue_token_with_tenants("acme-new", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        let stored = cfg
            .issue_token_with_tenants("acme-store", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        for token in [&deleted, &disabled, &recreated, &stored] {
            assert!(cfg.verify_bearer(token).is_ok());
        }
        let old_uid = cfg.decode_claims(&recreated).unwrap().uid;
        assert!(old_uid.as_ref().is_some_and(|id| !id.is_empty()));

        let now = chrono::Utc::now().timestamp();
        let unmarked = encode(
            &Header::default(),
            &JwtClaims {
                sub: "acme-del".into(),
                role: "operator".into(),
                exp: now + 3600,
                iat: now,
                tenant_ids: vec!["acme".into()],
                active_tenant_id: None,
                session_version: 0,
                uid: None,
            },
            &EncodingKey::from_secret(cfg.secret.as_ref().unwrap().as_bytes()),
        )
        .unwrap();
        assert!(cfg.verify_bearer(&unmarked).is_ok());

        let direct = cfg
            .issue_token_with_tenants("harness-user", Role::Viewer, 3600, &[])
            .unwrap();
        assert!(cfg.decode_claims(&direct).unwrap().uid.is_none());
        assert!(cfg.verify_bearer(&direct).is_ok());

        let mut store = UserStore::load_or_empty(dir.path());
        store.remove("acme-del").unwrap();
        store.save(dir.path()).unwrap();
        assert_eq!(cfg.verify_bearer(&deleted).unwrap_err(), "identity unknown");
        assert_eq!(
            cfg.verify_bearer(&unmarked).unwrap_err(),
            "identity unknown"
        );
        assert!(cfg
            .issue_token_with_tenants("acme-del", Role::Operator, 3600, &["acme".into()])
            .is_err());

        let mut store = UserStore::load_or_empty(dir.path());
        store.set_disabled("acme-off", true).unwrap();
        store.save(dir.path()).unwrap();
        assert_eq!(
            cfg.verify_bearer(&disabled).unwrap_err(),
            "identity disabled"
        );

        let mut store = UserStore::load_or_empty(dir.path());
        let previous = store.get("acme-new").unwrap().user_id.clone();
        store.remove("acme-new").unwrap();
        store.upsert(operator_record("acme-new")).unwrap();
        store.save(dir.path()).unwrap();
        let revived = store.get("acme-new").unwrap();
        assert_ne!(revived.user_id, previous);
        assert_eq!(revived.session_version, 1);
        assert_eq!(
            cfg.verify_bearer(&recreated).unwrap_err(),
            "identity unknown"
        );
        let fresh = cfg
            .issue_token_with_tenants("acme-new", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        assert_ne!(cfg.decode_claims(&fresh).unwrap().uid, old_uid);
        assert!(cfg.verify_bearer(&fresh).is_ok());
        assert_eq!(cfg.verify_bearer(&direct).unwrap().sub, "harness-user");

        let path = UserStore::path_under_workspace(dir.path());
        std::fs::write(&path, b"{").unwrap();
        assert_eq!(
            cfg.verify_bearer(&stored).unwrap_err(),
            IDENTITY_STORE_UNAVAILABLE
        );
        assert_eq!(
            auth_failure_status(IDENTITY_STORE_UNAVAILABLE),
            StatusCode::SERVICE_UNAVAILABLE
        );
        let admin = cfg
            .issue_token_with_tenants("admin", Role::Admin, 3600, &[])
            .unwrap();
        assert_eq!(cfg.verify_bearer(&admin).unwrap().sub, "admin");
        assert_eq!(
            cfg.verify_bearer(&direct).unwrap_err(),
            IDENTITY_STORE_UNAVAILABLE
        );
        assert!(cfg
            .issue_token_with_tenants("acme-store", Role::Operator, 3600, &["acme".into()])
            .is_err());

        std::fs::remove_file(&path).unwrap();
        assert_eq!(
            cfg.verify_bearer(&stored).unwrap_err(),
            IDENTITY_STORE_UNAVAILABLE
        );
        assert_eq!(
            auth_failure_status("identity unknown"),
            StatusCode::UNAUTHORIZED
        );
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE while the auth middleware reads the user store"
    )]
    async fn middleware_and_auth_me_reject_removed_users() {
        use crate::test_env_lock::{lock_env, WorkspaceEnv};
        use axum::body::Body;
        use axum::extract::{Request, State};
        use axum::http::{header, HeaderMap, StatusCode};
        use axum::middleware;
        use axum::routing::get;
        use axum::Router;
        use std::sync::Arc;
        use tower::ServiceExt;

        let _g = lock_env();
        let dir = tempfile::tempdir().unwrap();
        let _ws = WorkspaceEnv::set(dir.path());
        save_operator(dir.path(), "acme-http");

        let mut state = crate::state::AppState::new();
        state.auth = file_cfg();
        let state = Arc::new(state);
        let token = state
            .auth
            .issue_token_with_tenants("acme-http", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        let app = Router::new().route("/probe", get(|| async { "ok" })).layer(
            middleware::from_fn_with_state(Arc::clone(&state), jwt_middleware),
        );

        let probe = |token: String| {
            let app = app.clone();
            async move {
                let response = app
                    .oneshot(
                        Request::get("/probe")
                            .header(header::AUTHORIZATION, format!("Bearer {token}"))
                            .body(Body::empty())
                            .unwrap(),
                    )
                    .await
                    .unwrap();
                let status = response.status();
                let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
                    .await
                    .unwrap();
                let json: serde_json::Value =
                    serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
                (status, json)
            }
        };
        let me = |token: String| {
            let state = Arc::clone(&state);
            async move {
                let mut headers = HeaderMap::new();
                headers.insert(
                    header::AUTHORIZATION,
                    format!("Bearer {token}").parse().unwrap(),
                );
                match crate::routes::auth_me(State(state), headers).await {
                    Ok(body) => (
                        StatusCode::OK,
                        serde_json::to_value(body.0).unwrap_or_default(),
                    ),
                    Err((status, body)) => (status, body.0),
                }
            }
        };

        let (status, _) = probe(token.clone()).await;
        assert_eq!(status, StatusCode::OK);
        let (status, body) = me(token.clone()).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            body.get("username").and_then(|v| v.as_str()),
            Some("acme-http")
        );

        let mut store = UserStore::load_or_empty(dir.path());
        store.set_disabled("acme-http", true).unwrap();
        store.save(dir.path()).unwrap();
        let (status, body) = probe(token.clone()).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
        assert_eq!(body.get("ok").and_then(|v| v.as_bool()), Some(false));
        let (status, _) = me(token.clone()).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let mut store = UserStore::load_or_empty(dir.path());
        store.set_disabled("acme-http", false).unwrap();
        store.remove("acme-http").unwrap();
        store.upsert(operator_record("acme-http")).unwrap();
        store.save(dir.path()).unwrap();
        let (status, body) = probe(token.clone()).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
        assert_eq!(
            body.get("error").and_then(|v| v.as_str()),
            Some("identity unknown")
        );
        let (status, _) = me(token.clone()).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
        let fresh = state
            .auth
            .issue_token_with_tenants("acme-http", Role::Operator, 3600, &["acme".into()])
            .unwrap();
        let (status, _) = me(fresh).await;
        assert_eq!(status, StatusCode::OK);

        std::fs::write(UserStore::path_under_workspace(dir.path()), b"{").unwrap();
        let (status, body) = probe(token.clone()).await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(body.get("ok").and_then(|v| v.as_bool()), Some(false));
        assert_eq!(
            body.get("error").and_then(|v| v.as_str()),
            Some(IDENTITY_STORE_UNAVAILABLE)
        );
        let (status, _) = me(token.clone()).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        std::fs::remove_file(UserStore::path_under_workspace(dir.path())).unwrap();
        let (status, _) = probe(token).await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    }
}
