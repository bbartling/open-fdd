//! Open-FDD edge authentication: env loading, JWT, RBAC, audit.

pub mod audit;
pub mod config;
pub mod env_file;
pub mod jwt;
pub mod login;
pub mod rbac;

pub use config::{AuthConfig, Principal};
pub use jwt::Claims;
pub use login::LoginResult;

use std::sync::OnceLock;

static AUTH: OnceLock<AuthConfig> = OnceLock::new();

pub fn auth_config() -> &'static AuthConfig {
    AUTH.get_or_init(AuthConfig::load)
}

pub fn reload_auth_config_for_tests() -> AuthConfig {
    AuthConfig::load()
}
