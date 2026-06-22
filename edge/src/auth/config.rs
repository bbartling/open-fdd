//! Auth configuration loaded from env + workspace/auth.env.local.

use super::env_file::{apply_env_file, default_auth_env_path};
use std::collections::HashMap;
use std::env;

#[derive(Clone, Debug)]
pub struct Principal {
    pub sub: String,
    pub role: String,
}

#[derive(Clone, Debug)]
pub struct AuthConfig {
    pub required: bool,
    pub secret: String,
    pub ttl_seconds: i64,
    pub cookie_secure: bool,
    pub users: HashMap<String, (String, &'static str)>,
}

impl AuthConfig {
    pub fn load() -> Self {
        apply_env_file(&default_auth_env_path());

        // Legacy alias
        if env::var("OFDD_AUTH_SECRET").is_err() {
            if let Ok(v) = env::var("OPENFDD_JWT_SECRET") {
                env::set_var("OFDD_AUTH_SECRET", v);
            }
        }

        let required = env::var("OFDD_AUTH_REQUIRED")
            .map(|v| v != "0" && !v.eq_ignore_ascii_case("false"))
            .unwrap_or(true);

        let secret = env::var("OFDD_AUTH_SECRET").unwrap_or_else(|_| {
            if required {
                eprintln!("warning: OFDD_AUTH_SECRET missing; using insecure dev fallback");
            }
            "dev-change-me-openfdd-rust-edge".to_string()
        });

        let ttl_seconds = env::var("OFDD_JWT_TTL_SECONDS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(28_800);

        let cookie_secure = env::var("OFDD_COOKIE_SECURE")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

        let mut users = HashMap::new();
        add_user(&mut users, "OFDD_OPERATOR_USER", "OFDD_OPERATOR_PASSWORD", "operator");
        add_user(&mut users, "OFDD_INTEGRATOR_USER", "OFDD_INTEGRATOR_PASSWORD", "integrator");
        add_user(&mut users, "OFDD_AGENT_USER", "OFDD_AGENT_PASSWORD", "agent");

        Self {
            required,
            secret,
            ttl_seconds,
            cookie_secure,
            users,
        }
    }

    pub fn validate_for_production(&self) -> Result<(), String> {
        if !self.required {
            return Ok(());
        }
        if self.secret.len() < 32 || self.secret.contains("dev-change-me") {
            return Err("OFDD_AUTH_SECRET is missing or too weak".to_string());
        }
        if self.users.len() < 3 {
            return Err("operator, integrator, and agent credentials must be configured".to_string());
        }
        Ok(())
    }
}

fn add_user(
    users: &mut HashMap<String, (String, &'static str)>,
    user_key: &str,
    pass_key: &str,
    role: &'static str,
) {
    let username = env::var(user_key).unwrap_or_else(|_| role.to_string());
    if let Ok(password) = env::var(pass_key) {
        users.insert(username, (password, role));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::env_file::{generate_auth_env, GenerateOptions};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn loads_users_from_generated_env_file() {
        let path = std::env::temp_dir().join(format!(
            "openfdd-auth-load-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        generate_auth_env(&GenerateOptions {
            path: path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", path.parent().unwrap());
        // Re-apply by reading file directly
        let map = crate::auth::env_file::load_env_file(&path).unwrap();
        for (k, v) in map {
            std::env::set_var(k, v);
        }
        let cfg = AuthConfig::load();
        assert!(cfg.users.contains_key("operator"));
        assert!(cfg.users.contains_key("integrator"));
        assert!(cfg.users.contains_key("agent"));
        let _ = std::fs::remove_file(path);
    }
}
