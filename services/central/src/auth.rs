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

const VALID_ROLES: &[&str] = &["viewer", "operator", "admin"];

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
    /// Wave L — tenant memberships when multi-tenant mode is on (empty = hub-wide admin or single-tenant).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tenant_ids: Vec<String>,
    /// File-plane session epoch (S09). Env identities always mint/verify as 0.
    #[serde(default, rename = "sv")]
    pub session_version: u64,
}

fn is_env_identity(sub: &str) -> bool {
    matches!(
        sub.trim().to_ascii_lowercase().as_str(),
        "admin" | "agent" | "viewer" | "dev"
    )
}

fn file_plane_session_version(sub: &str) -> Option<u64> {
    if is_env_identity(sub) {
        return Some(0);
    }
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    crate::user_store::UserStore::load_or_empty(std::path::Path::new(&workspace))
        .get(sub)
        .filter(|r| !r.disabled)
        .map(|r| r.session_version)
}

#[derive(Debug, Clone)]
pub struct AuthUser {
    pub sub: String,
    pub role: Role,
    pub tenant_ids: Vec<String>,
}

impl AuthUser {
    pub fn dev_anonymous() -> Self {
        Self {
            sub: "dev".into(),
            role: Role::Admin,
            tenant_ids: vec![],
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

    /// Mint a JWT with optional tenant membership claims (Wave L L4+).
    ///
    /// File-plane subjects embed the current `session_version` so disable/role/
    /// membership/password changes revoke outstanding tokens (S09). Env identities
    /// (`admin`/`agent`/`viewer`) always use session_version 0.
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
        let session_version = if is_env_identity(sub) {
            0
        } else {
            file_plane_session_version(sub).unwrap_or(0)
        };
        let claims = JwtClaims {
            sub: sub.to_string(),
            role: role.as_str().to_string(),
            exp: now + ttl_secs.max(60),
            iat: now,
            tenant_ids: tenant_ids.to_vec(),
            session_version,
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
        // S09: control-plane file users must still exist, be enabled, and match sv.
        // Env identities and legacy JWT subjects not in users.json are unchanged.
        if !is_env_identity(&claims.sub) {
            let workspace =
                std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
            let store =
                crate::user_store::UserStore::load_or_empty(std::path::Path::new(&workspace));
            if let Some(rec) = store.get(&claims.sub) {
                if rec.disabled {
                    return Err("identity disabled".into());
                }
                if rec.session_version != claims.session_version {
                    return Err("session revoked".into());
                }
                let store_role = Role::parse(rec.role.trim())
                    .ok_or_else(|| "identity role invalid".to_string())?;
                if store_role != role {
                    return Err("session revoked".into());
                }
                for tid in &claims.tenant_ids {
                    if !rec.tenant_ids.iter().any(|t| t == tid) {
                        return Err("session revoked".into());
                    }
                }
            }
        }
        Ok(AuthUser {
            sub: claims.sub,
            role,
            tenant_ids: claims.tenant_ids,
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
        Err(detail) => (
            StatusCode::UNAUTHORIZED,
            axum::Json(serde_json::json!({"ok": false, "error": detail})),
        )
            .into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use jsonwebtoken::{encode, EncodingKey, Header};

    #[test]
    fn roundtrip_jwt() {
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
            session_version: 0,
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
            session_version: 0,
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
            session_version: 0,
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
}
