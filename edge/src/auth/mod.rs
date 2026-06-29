//! Open-FDD edge authentication: env loading, JWT, RBAC, audit.

pub mod audit;
pub mod config;
pub mod env_file;
pub mod jwt;
pub mod login;
pub mod password;
pub mod rbac;

pub use config::AuthConfig;

use std::sync::OnceLock;

static AUTH: OnceLock<AuthConfig> = OnceLock::new();

pub fn auth_config() -> &'static AuthConfig {
    AUTH.get_or_init(AuthConfig::load)
}
