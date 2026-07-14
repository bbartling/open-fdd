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
}

impl AuthConfig {
    pub fn load() -> Self {
        let secret = std::env::var("OPENFDD_JWT_SECRET")
            .ok()
            .filter(|s| !s.trim().is_empty());
        if secret.is_none() {
            warn!(
                "OPENFDD_JWT_SECRET unset — central API is open for local/dev (no Bearer required)"
            );
        }
        Self { secret }
    }

    pub fn required(&self) -> bool {
        self.secret.is_some()
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
}
