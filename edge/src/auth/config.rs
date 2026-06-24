//! Auth configuration loaded from env + workspace/auth.env.local.

use super::env_file::{
    apply_env_file, default_auth_env_path, load_password_credential, RoleSpec, ALL_ROLES,
};
use super::password::PasswordCredential;
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
    pub users: HashMap<String, (PasswordCredential, &'static str)>,
}

impl AuthConfig {
    pub fn load() -> Self {
        apply_env_file(&default_auth_env_path());

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

        let ttl_seconds = env::var("OPENFDD_AUTH_TTL_SEC")
            .ok()
            .or_else(|| env::var("OFDD_JWT_TTL_SECONDS").ok())
            .and_then(|v| v.parse().ok())
            .unwrap_or(28_800);

        let cookie_secure = env::var("OFDD_COOKIE_SECURE")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

        let map = super::env_file::load_env_file(&default_auth_env_path()).unwrap_or_default();
        let mut users = HashMap::new();
        for spec in ALL_ROLES {
            add_user_from_spec(&mut users, &map, spec);
        }

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
            return Err(
                "operator, integrator, and agent credentials must be configured".to_string(),
            );
        }
        Ok(())
    }
}

fn add_user_from_spec(
    users: &mut HashMap<String, (PasswordCredential, &'static str)>,
    map: &HashMap<String, String>,
    spec: RoleSpec,
) {
    let username = map
        .get(spec.user_key)
        .cloned()
        .unwrap_or_else(|| spec.default_user.to_string());
    if let Some(cred) = load_password_credential(map, spec.hash_key, spec.pass_key) {
        users.insert(username, (cred, spec.role));
    } else if let Ok(password) = env::var(spec.pass_key) {
        users.insert(
            username,
            (PasswordCredential::from_env_plain(password), spec.role),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::env_file::{generate_auth_env, GenerateOptions};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn loads_users_from_generated_env_file() {
        let dir = std::env::temp_dir().join(format!(
            "openfdd-auth-load-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("auth.env.local");
        generate_auth_env(&GenerateOptions {
            path: path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &dir);
        let cfg = AuthConfig::load();
        assert!(cfg.users.contains_key("operator"));
        assert!(cfg.users.contains_key("integrator"));
        assert!(cfg.users.contains_key("agent"));
        assert!(cfg.users.contains_key("admin"));
        let _ = std::fs::remove_dir_all(dir);
    }
}
