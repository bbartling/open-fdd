//! HS256 JWT creation and validation.

use super::config::AuthConfig;
use super::config::Principal;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use chrono::{DateTime, Utc};
use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

#[derive(Clone, Debug)]
pub struct Claims {
    pub sub: String,
    pub role: String,
    pub iat: i64,
    pub exp: i64,
}

pub fn create_token(config: &AuthConfig, sub: &str, role: &str) -> (String, DateTime<Utc>) {
    let now = Utc::now();
    let exp = now + chrono::Duration::seconds(config.ttl_seconds);
    let header = json!({"alg":"HS256","typ":"JWT"});
    let claims = json!({
        "sub": sub,
        "role": role,
        "iat": now.timestamp(),
        "exp": exp.timestamp(),
        "iss": "open-fdd",
        "aud": "open-fdd-edge"
    });
    let h = URL_SAFE_NO_PAD.encode(header.to_string().as_bytes());
    let c = URL_SAFE_NO_PAD.encode(claims.to_string().as_bytes());
    let msg = format!("{h}.{c}");
    let mut mac = HmacSha256::new_from_slice(config.secret.as_bytes()).expect("hmac key");
    mac.update(msg.as_bytes());
    let sig = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    (format!("{msg}.{sig}"), exp)
}

pub fn verify_token(config: &AuthConfig, token: &str) -> Result<Principal, String> {
    let parts: Vec<&str> = token.split('.').collect();
    if parts.len() != 3 {
        return Err("malformed JWT".into());
    }
    let msg = format!("{}.{}", parts[0], parts[1]);
    let mut mac = HmacSha256::new_from_slice(config.secret.as_bytes()).expect("hmac key");
    mac.update(msg.as_bytes());
    let expected = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    if expected != parts[2] {
        return Err("invalid JWT signature".into());
    }
    let bytes = URL_SAFE_NO_PAD
        .decode(parts[1])
        .map_err(|_| "invalid JWT payload")?;
    let claims: Value = serde_json::from_slice(&bytes).map_err(|_| "invalid JWT claims")?;

    if let Some(iss) = claims.get("iss").and_then(|v| v.as_str()) {
        if iss != "open-fdd" {
            return Err("invalid JWT issuer".into());
        }
    }
    if let Some(aud) = claims.get("aud").and_then(|v| v.as_str()) {
        if aud != "open-fdd-edge" {
            return Err("invalid JWT audience".into());
        }
    }

    let exp = claims.get("exp").and_then(|v| v.as_i64()).unwrap_or(0);
    if exp < Utc::now().timestamp() {
        return Err("expired JWT".into());
    }

    Ok(Principal {
        sub: claims
            .get("sub")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        role: claims
            .get("role")
            .and_then(|v| v.as_str())
            .unwrap_or("operator")
            .to_string(),
    })
}

pub fn claims_from_token_unverified(token: &str) -> Option<Claims> {
    let parts: Vec<&str> = token.split('.').collect();
    if parts.len() != 3 {
        return None;
    }
    let bytes = URL_SAFE_NO_PAD.decode(parts[1]).ok()?;
    let claims: Value = serde_json::from_slice(&bytes).ok()?;
    Some(Claims {
        sub: claims.get("sub")?.as_str()?.to_string(),
        role: claims.get("role")?.as_str()?.to_string(),
        iat: claims.get("iat")?.as_i64()?,
        exp: claims.get("exp")?.as_i64()?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::env_file::{generate_auth_env, GenerateOptions};
    use std::collections::HashMap;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_config() -> AuthConfig {
        AuthConfig {
            required: true,
            secret: "test-secret-with-enough-entropy-for-hmac-signing".to_string(),
            ttl_seconds: 3600,
            cookie_secure: false,
            users: HashMap::new(),
        }
    }

    #[test]
    fn jwt_roundtrip() {
        let cfg = test_config();
        let (token, _exp) = create_token(&cfg, "integrator", "integrator");
        let principal = verify_token(&cfg, &token).unwrap();
        assert_eq!(principal.sub, "integrator");
        assert_eq!(principal.role, "integrator");
    }

    #[test]
    fn expired_jwt_rejected() {
        let cfg = AuthConfig {
            ttl_seconds: -10,
            ..test_config()
        };
        let (token, _) = create_token(&cfg, "agent", "agent");
        assert!(verify_token(&cfg, &token).is_err());
    }
}
