//! Wave N — file control-plane users for per-tenant password logins.
//!
//! Path: `{OPENFDD_WORKSPACE}/openfdd/control_plane/users.json`
//! Passwords prefer `password_env` (Railway secrets); optional `password` for lab only.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::auth::{constant_time_eq_bytes, Role};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserRecord {
    pub username: String,
    /// `operator` or `viewer` (hub `admin` stays env-only).
    pub role: String,
    #[serde(default)]
    pub tenant_ids: Vec<String>,
    /// Env var holding the plaintext password (preferred on Railway).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub password_env: Option<String>,
    /// Lab-only plaintext; never commit real secrets.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub password: Option<String>,
    /// When true, authenticate fails (hub admin soft-delete / suspend).
    #[serde(default)]
    pub disabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UserStore {
    #[serde(default)]
    pub users: Vec<UserRecord>,
}

impl UserStore {
    pub fn path_under_workspace(workspace: &Path) -> PathBuf {
        workspace
            .join("openfdd")
            .join("control_plane")
            .join("users.json")
    }

    pub fn load_or_empty(workspace: &Path) -> Self {
        let path = Self::path_under_workspace(workspace);
        match fs::read_to_string(&path) {
            Ok(raw) => serde_json::from_str(&raw).unwrap_or_default(),
            Err(_) => Self::default(),
        }
    }

    /// Authenticate a control-plane user. Returns (subject, role, tenant_ids).
    pub fn authenticate(
        &self,
        username: &str,
        password: &str,
    ) -> Option<(String, Role, Vec<String>)> {
        let want = username.trim();
        if want.is_empty() {
            return None;
        }
        let rec = self
            .users
            .iter()
            .find(|u| u.username.trim().eq_ignore_ascii_case(want))?;
        if rec.disabled {
            return None;
        }
        let role = Role::parse(rec.role.trim())?;
        // Hub admin must not be minted from the file store (empty tenant_ids + Admin is hub_admin).
        if matches!(role, Role::Admin) {
            return None;
        }
        if rec.tenant_ids.is_empty() {
            return None;
        }
        let expected = if let Some(env_key) = rec
            .password_env
            .as_ref()
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
        {
            std::env::var(env_key).ok().filter(|s| !s.is_empty())?
        } else {
            rec.password
                .as_ref()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())?
        };
        if !constant_time_eq_bytes(expected.as_bytes(), password.as_bytes()) {
            return None;
        }
        Some((
            rec.username.trim().to_string(),
            role,
            rec.tenant_ids.clone(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_env_lock::lock_env;
    use tempfile::tempdir;

    #[test]
    fn authenticates_via_password_env() {
        let _g = lock_env();
        let dir = tempdir().unwrap();
        let cp = dir.path().join("openfdd/control_plane");
        fs::create_dir_all(&cp).unwrap();
        fs::write(
            cp.join("users.json"),
            r#"{
              "users": [{
                "username": "acme-ops",
                "role": "operator",
                "tenant_ids": ["acme"],
                "password_env": "OPENFDD_USER_ACME_OPS_PASSWORD"
              }]
            }"#,
        )
        .unwrap();
        std::env::set_var("OPENFDD_USER_ACME_OPS_PASSWORD", "acme-secret-pass");
        let store = UserStore::load_or_empty(dir.path());
        let (sub, role, tids) = store
            .authenticate("acme-ops", "acme-secret-pass")
            .expect("auth");
        assert_eq!(sub, "acme-ops");
        assert_eq!(role, Role::Operator);
        assert_eq!(tids, vec!["acme".to_string()]);
        assert!(store.authenticate("acme-ops", "wrong").is_none());
        std::env::remove_var("OPENFDD_USER_ACME_OPS_PASSWORD");
    }

    #[test]
    fn rejects_admin_role_in_file() {
        let store = UserStore {
            users: vec![UserRecord {
                username: "evil".into(),
                role: "admin".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
            }],
        };
        assert!(store.authenticate("evil", "x").is_none());
    }
}
