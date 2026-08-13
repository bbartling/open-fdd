//! Dev-only helpers — quick login and local stack scripts (OPENFDD_ALLOW_INSECURE_AUTH=1).

use crate::auth::config::AuthConfig;
use serde_json::{json, Value};
use std::env;
use std::path::PathBuf;

pub fn insecure_dev_enabled() -> bool {
    env::var("OPENFDD_ALLOW_INSECURE_AUTH")
        .map(|v| matches!(v.as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
}

pub fn quick_login(body: &Value) -> Value {
    if !insecure_dev_enabled() {
        return json!({
            "ok": false,
            "error": "dev quick-login disabled (set OPENFDD_ALLOW_INSECURE_AUTH=1 on edge)"
        });
    }
    let role = body
        .get("role")
        .and_then(|v| v.as_str())
        .unwrap_or("integrator");
    let config = AuthConfig::load();
    for (username, (_, user_role)) in &config.users {
        if *user_role == role {
            let (token, expires_at) = crate::auth::jwt::create_token(&config, username, role);
            return json!({
                "ok": true,
                "token": token,
                "access_token": token,
                "role": role,
                "username": username,
                "expires_at": expires_at.to_rfc3339(),
                "dev": true
            });
        }
    }
    json!({
        "ok": false,
        "error": format!("no configured user for role '{role}' — run scripts/openfdd_auth_init.sh")
    })
}

pub fn run_script(body: &Value) -> Value {
    if !insecure_dev_enabled() {
        return json!({
            "ok": false,
            "error": "dev scripts disabled (set OPENFDD_ALLOW_INSECURE_AUTH=1 on edge)"
        });
    }
    let script_key = body.get("script").and_then(|v| v.as_str()).unwrap_or("");
    json!({
        "ok": false,
        "error": format!("unknown dev script: {script_key}"),
        "allowed": []
    })
}
