//! Username/password authentication and login rate limiting.

use super::audit;
use super::config::AuthConfig;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

#[derive(Clone, Debug)]
pub struct LoginResult {
    pub token: String,
    pub token_type: String,
    pub expires_at: DateTime<Utc>,
    pub role: String,
    pub subject: String,
}

struct RateState {
    failures: HashMap<String, (u32, Instant)>,
}

static RATE: OnceLock<Mutex<RateState>> = OnceLock::new();

fn rate_state() -> &'static Mutex<RateState> {
    RATE.get_or_init(|| {
        Mutex::new(RateState {
            failures: HashMap::new(),
        })
    })
}

fn check_rate_limit(username: &str) -> Result<(), String> {
    let mut state = rate_state().lock().map_err(|_| "login busy".to_string())?;
    if let Some((count, since)) = state.failures.get(username) {
        if *count >= 5 && since.elapsed() < Duration::from_secs(60) {
            audit::log_event("login_rate_limited", json!({"username": username}));
            return Err("too many login attempts; try again later".into());
        }
        if since.elapsed() >= Duration::from_secs(60) {
            state.failures.remove(username);
        }
    }
    Ok(())
}

fn note_failure(username: &str) {
    if let Ok(mut state) = rate_state().lock() {
        let entry = state
            .failures
            .entry(username.to_string())
            .or_insert((0, Instant::now()));
        entry.0 += 1;
        entry.1 = Instant::now();
    }
}

fn clear_failures(username: &str) {
    if let Ok(mut state) = rate_state().lock() {
        state.failures.remove(username);
    }
}

pub fn authenticate(config: &AuthConfig, body: &Value) -> Result<LoginResult, String> {
    if body.get("role").is_some() {
        audit::log_event(
            "login_rejected_self_mint",
            json!({"reason": "client supplied role"}),
        );
        return Err("role cannot be supplied by client".into());
    }
    if body.get("sub").is_some() {
        audit::log_event(
            "login_rejected_self_mint",
            json!({"reason": "client supplied sub"}),
        );
        return Err("sub cannot be supplied by client".into());
    }

    let username = body
        .get("username")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "username and password required".to_string())?;

    let password = body
        .get("password")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "username and password required".to_string())?;

    check_rate_limit(username)?;

    let Some((expected, role)) = config.users.get(username) else {
        note_failure(username);
        audit::log_event(
            "login_failure",
            json!({"username": username, "reason": "unknown_user"}),
        );
        return Err("invalid credentials".into());
    };

    if !expected.verify(password).unwrap_or(false) {
        note_failure(username);
        audit::log_event(
            "login_failure",
            json!({"username": username, "reason": "bad_password"}),
        );
        return Err("invalid credentials".into());
    }

    clear_failures(username);
    let (token, expires_at) = super::jwt::create_token(config, username, role);
    audit::log_event("login_success", json!({"username": username, "role": role}));

    Ok(LoginResult {
        token,
        token_type: "Bearer".to_string(),
        expires_at,
        role: role.to_string(),
        subject: username.to_string(),
    })
}

pub fn login_response(result: LoginResult) -> Value {
    json!({
        "ok": true,
        "token": result.token,
        "access_token": result.token,
        "token_type": result.token_type,
        "expires_at": result.expires_at.to_rfc3339(),
        "role": result.role,
        "subject": result.subject
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::config::AuthConfig;
    use crate::auth::password::PasswordCredential;
    use std::collections::HashMap;

    fn cfg_with_users() -> AuthConfig {
        let mut users = HashMap::new();
        users.insert(
            "integrator".to_string(),
            (
                PasswordCredential::Plain("integrator-test-password-1234567890".to_string()),
                "integrator",
            ),
        );
        users.insert(
            "operator".to_string(),
            (
                PasswordCredential::Plain("operator-test-password-1234567890".to_string()),
                "operator",
            ),
        );
        users.insert(
            "agent".to_string(),
            (
                PasswordCredential::Plain("agent-test-password-123456789012345".to_string()),
                "agent",
            ),
        );
        AuthConfig {
            required: true,
            secret: "test-secret-with-enough-entropy-for-hmac-signing".to_string(),
            ttl_seconds: 3600,
            cookie_secure: false,
            users,
        }
    }

    #[test]
    fn login_success_integrator() {
        let cfg = cfg_with_users();
        let body =
            json!({"username":"integrator","password":"integrator-test-password-1234567890"});
        let result = authenticate(&cfg, &body).unwrap();
        assert_eq!(result.role, "integrator");
    }

    #[test]
    fn login_failure_wrong_password() {
        let cfg = cfg_with_users();
        let body = json!({"username":"integrator","password":"wrong"});
        assert!(authenticate(&cfg, &body).is_err());
    }

    #[test]
    fn rejects_self_mint_without_password() {
        let cfg = cfg_with_users();
        let body = json!({"sub":"agent","role":"agent"});
        assert!(authenticate(&cfg, &body).is_err());
    }
}
