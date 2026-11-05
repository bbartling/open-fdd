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
    /// Server-minted id. A recreate allocates a new one; callers cannot choose it.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub user_id: String,
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
    /// Bumped on disable / role / membership / password change so outstanding JWTs die (S09).
    #[serde(default)]
    pub session_version: u64,
}

/// A control-plane username that was removed. The session epoch is kept so a
/// later account with the same name cannot start again at zero.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RetiredUser {
    pub username: String,
    #[serde(default)]
    pub user_id: String,
    #[serde(default)]
    pub session_version: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UserStore {
    #[serde(default)]
    pub users: Vec<UserRecord>,
    #[serde(default)]
    pub retired: Vec<RetiredUser>,
}

/// Result of reading `users.json`. Auth must not treat a bad read as an empty plane.
#[derive(Debug)]
pub enum UserStoreLoad {
    Ready(UserStore),
    /// The file is not there. A deployment with only env identities looks like this.
    Absent,
    /// Present but unreadable, or JSON that is not this store.
    Unreadable,
}

impl UserStore {
    pub fn path_under_workspace(workspace: &Path) -> PathBuf {
        workspace
            .join("openfdd")
            .join("control_plane")
            .join("users.json")
    }

    pub fn load_status(workspace: &Path) -> UserStoreLoad {
        let path = Self::path_under_workspace(workspace);
        match fs::read_to_string(&path) {
            Ok(raw) => match serde_json::from_str::<Self>(&raw) {
                Ok(store) => UserStoreLoad::Ready(store),
                Err(_) => UserStoreLoad::Unreadable,
            },
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => UserStoreLoad::Absent,
            Err(_) => UserStoreLoad::Unreadable,
        }
    }

    /// Missing or unreadable files become an empty plane.
    ///
    /// Token checks must use [`Self::load_status`] instead. An empty plane is not
    /// a successful revocation check.
    pub fn load_or_empty(workspace: &Path) -> Self {
        match Self::load_status(workspace) {
            UserStoreLoad::Ready(store) => store,
            UserStoreLoad::Absent | UserStoreLoad::Unreadable => Self::default(),
        }
    }

    pub fn is_retired(&self, username: &str) -> bool {
        let want = username.trim();
        self.retired
            .iter()
            .any(|row| row.username.eq_ignore_ascii_case(want))
    }

    /// Highest session epoch recorded for a removed username, if any.
    pub fn retired_session_floor(&self, username: &str) -> Option<u64> {
        self.retired
            .iter()
            .filter(|row| row.username.eq_ignore_ascii_case(username.trim()))
            .map(|row| row.session_version)
            .max()
    }

    pub fn note_retired(&mut self, username: String, user_id: String, session_version: u64) {
        let name = username.trim().to_string();
        if name.is_empty() {
            return;
        }
        if let Some(existing) = self
            .retired
            .iter_mut()
            .find(|row| row.username.eq_ignore_ascii_case(&name))
        {
            if session_version >= existing.session_version {
                existing.username = name;
                existing.user_id = user_id;
                existing.session_version = session_version;
            }
            return;
        }
        self.retired.push(RetiredUser {
            username: name,
            user_id,
            session_version,
        });
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
                user_id: String::new(),
                role: "admin".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
                session_version: 0,
            }],
            ..UserStore::default()
        };
        assert!(store.authenticate("evil", "x").is_none());
    }
}
