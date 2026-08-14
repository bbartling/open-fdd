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
}

#[derive(Debug, Clone)]
pub struct AuthUser {
    pub sub: String,
    pub role: Role,
}

impl AuthUser {
    pub fn dev_anonymous() -> Self {
        Self {
            sub: "dev".into(),
            role: Role::Admin,
        }
    }
}

#[derive(Debug, Clone)]
pub struct AuthConfig {
    pub secret: Option<String>,
    /// Optional plaintext admin password for `POST /api/auth/login` (bench / remote UI).
    pub admin_password: Option<String>,
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
        }
        Self {
            secret,
            admin_password,
        }
    }

    pub fn required(&self) -> bool {
        self.secret.is_some()
    }

    /// Mint a JWT for username/role. Requires `OPENFDD_JWT_SECRET`.
    pub fn issue_token(&self, sub: &str, role: Role, ttl_secs: i64) -> Result<String, String> {
        use jsonwebtoken::{encode, EncodingKey, Header};
        let secret = self
            .secret
            .as_ref()
            .ok_or_else(|| "auth not configured".to_string())?;
        let now = chrono::Utc::now().timestamp();
        let claims = JwtClaims {
            sub: sub.to_string(),
            role: role.as_str().to_string(),
            exp: now + ttl_secs,
            iat: now,
        };
        encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(secret.as_bytes()),
        )
        .map_err(|e| format!("token encode failed: {e}"))
    }

    /// Validate username/password for UI login.
    /// Only `admin` is accepted with `OPENFDD_ADMIN_PASSWORD` (do not mint other roles
    /// from a shared password).
    pub fn authenticate_password(
        &self,
        username: &str,
        password: &str,
    ) -> Result<(String, Role), String> {
        let expected = self
            .admin_password
            .as_ref()
            .ok_or_else(|| "login not configured (set OPENFDD_ADMIN_PASSWORD)".to_string())?;
        if !constant_time_eq(expected.as_bytes(), password.as_bytes()) {
            return Err("invalid credentials".into());
        }
        if username.trim() != "admin" {
            return Err("invalid credentials".into());
        }
        Ok(("admin".into(), Role::Admin))
    }

    pub fn verify_bearer(&self, token: &str) -> Result<AuthUser, String> {
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
        let role = Role::parse(&data.claims.role).ok_or_else(|| {
            format!(
                "invalid role {}; expected one of {VALID_ROLES:?}",
                data.claims.role
            )
        })?;
        Ok(AuthUser {
            sub: data.claims.sub,
            role,
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
        };
        let claims = JwtClaims {
            sub: "operator".into(),
            role: "operator".into(),
            exp: chrono::Utc::now().timestamp() + 3600,
            iat: chrono::Utc::now().timestamp(),
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
        };
        let claims = JwtClaims {
            sub: "x".into(),
            role: "integrator".into(),
            exp: chrono::Utc::now().timestamp() + 3600,
            iat: chrono::Utc::now().timestamp(),
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
}
