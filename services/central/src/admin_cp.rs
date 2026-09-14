//! Wave O8 — hub-admin CRUD over control-plane `users.json` / `tenants.json`.
//!
//! Hub `admin` (env password, empty `tenant_ids`) only. File-plane users never
//! get Admin role. Passwords: prefer `password_env`; lab may set `password`.

use std::fs;
use std::io::Write;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::auth::Role;
use crate::tenant::{ControlPlane, TenantRecord};
use crate::user_store::{UserRecord, UserStore};

fn atomic_write(path: &Path, body: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir control_plane: {e}"))?;
    }
    let tmp = path.with_extension("json.tmp");
    {
        let mut f = fs::File::create(&tmp).map_err(|e| format!("create tmp: {e}"))?;
        f.write_all(body.as_bytes())
            .map_err(|e| format!("write tmp: {e}"))?;
        f.sync_all().map_err(|e| format!("sync tmp: {e}"))?;
    }
    fs::rename(&tmp, path).map_err(|e| format!("rename control_plane file: {e}"))?;
    Ok(())
}

impl UserStore {
    pub fn save(&self, workspace: &Path) -> Result<(), String> {
        let path = Self::path_under_workspace(workspace);
        let body = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        atomic_write(&path, &format!("{body}\n"))
    }

    pub fn public_list(&self) -> Vec<UserPublic> {
        self.users
            .iter()
            .map(|u| UserPublic {
                username: u.username.clone(),
                role: u.role.clone(),
                tenant_ids: u.tenant_ids.clone(),
                password_env: u.password_env.clone(),
                has_inline_password: u
                    .password
                    .as_ref()
                    .map(|p| !p.trim().is_empty())
                    .unwrap_or(false),
                disabled: u.disabled,
            })
            .collect()
    }

    pub fn upsert(&mut self, rec: UserRecord) -> Result<(), String> {
        let name = rec.username.trim().to_string();
        if name.is_empty() {
            return Err("username required".into());
        }
        if name.eq_ignore_ascii_case("admin")
            || name.eq_ignore_ascii_case("agent")
            || name.eq_ignore_ascii_case("viewer")
        {
            return Err("username reserved for env identities".into());
        }
        let role = Role::parse(rec.role.trim()).ok_or_else(|| "role must be operator or viewer".to_string())?;
        if matches!(role, Role::Admin) {
            return Err("file users cannot be admin (hub admin is env-only)".into());
        }
        if rec.tenant_ids.is_empty() {
            return Err("tenant_ids required".into());
        }
        let has_env = rec
            .password_env
            .as_ref()
            .map(|s| !s.trim().is_empty())
            .unwrap_or(false);
        let has_pw = rec
            .password
            .as_ref()
            .map(|s| !s.trim().is_empty())
            .unwrap_or(false);
        let existing = self
            .users
            .iter()
            .find(|u| u.username.eq_ignore_ascii_case(&name));
        if existing.is_none() && !has_env && !has_pw {
            return Err("new user requires password or password_env".into());
        }
        let mut next = rec;
        next.username = name.clone();
        next.role = match role {
            Role::Operator => "operator".into(),
            Role::Viewer => "viewer".into(),
            Role::Admin => unreachable!(),
        };
        if let Some(idx) = self
            .users
            .iter()
            .position(|u| u.username.eq_ignore_ascii_case(&name))
        {
            // Keep prior password material when update omits both.
            if !has_env && !has_pw {
                next.password_env = self.users[idx].password_env.clone();
                next.password = self.users[idx].password.clone();
            } else if has_pw && !has_env {
                next.password_env = None;
            } else if has_env {
                next.password = None;
            }
            self.users[idx] = next;
        } else {
            if has_env {
                next.password = None;
            }
            self.users.push(next);
        }
        Ok(())
    }

    pub fn set_disabled(&mut self, username: &str, disabled: bool) -> Result<(), String> {
        let rec = self
            .users
            .iter_mut()
            .find(|u| u.username.eq_ignore_ascii_case(username.trim()))
            .ok_or_else(|| "user not found".to_string())?;
        rec.disabled = disabled;
        Ok(())
    }

    pub fn remove(&mut self, username: &str) -> Result<(), String> {
        let before = self.users.len();
        self.users
            .retain(|u| !u.username.eq_ignore_ascii_case(username.trim()));
        if self.users.len() == before {
            return Err("user not found".into());
        }
        Ok(())
    }
}

impl ControlPlane {
    pub fn save(&self, workspace: &Path) -> Result<(), String> {
        let path = Self::path_under_workspace(workspace);
        let body = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        atomic_write(&path, &format!("{body}\n"))
    }

    pub fn upsert_tenant(&mut self, rec: TenantRecord) -> Result<(), String> {
        let id = rec.id.trim().to_string();
        if id.is_empty() {
            return Err("tenant id required".into());
        }
        if id == "legacy" {
            return Err("tenant id 'legacy' is reserved".into());
        }
        let mut next = rec;
        next.id = id.clone();
        if next.name.trim().is_empty() {
            next.name = id.clone();
        }
        if let Some(idx) = self.tenants.iter().position(|t| t.id == id) {
            self.tenants[idx] = next;
        } else {
            self.tenants.push(next);
        }
        Ok(())
    }

    pub fn remove_tenant(&mut self, tenant_id: &str) -> Result<(), String> {
        let before = self.tenants.len();
        self.tenants.retain(|t| t.id != tenant_id.trim());
        if self.tenants.len() == before {
            return Err("tenant not found".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserPublic {
    pub username: String,
    pub role: String,
    pub tenant_ids: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub password_env: Option<String>,
    pub has_inline_password: bool,
    pub disabled: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct UserUpsertRequest {
    pub username: String,
    pub role: String,
    pub tenant_ids: Vec<String>,
    #[serde(default)]
    pub password_env: Option<String>,
    #[serde(default)]
    pub password: Option<String>,
    #[serde(default)]
    pub disabled: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TenantUpsertRequest {
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub building_ids: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn upsert_disable_remove_user_roundtrip() {
        let dir = tempdir().unwrap();
        let mut store = UserStore::default();
        store
            .upsert(UserRecord {
                username: "acme-ops".into(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("secret".into()),
                disabled: false,
            })
            .unwrap();
        store.save(dir.path()).unwrap();
        let loaded = UserStore::load_or_empty(dir.path());
        assert_eq!(loaded.users.len(), 1);
        assert!(loaded.authenticate("acme-ops", "secret").is_some());

        let mut store = loaded;
        store.set_disabled("acme-ops", true).unwrap();
        store.save(dir.path()).unwrap();
        let loaded = UserStore::load_or_empty(dir.path());
        assert!(loaded.authenticate("acme-ops", "secret").is_none());

        let mut store = loaded;
        store.remove("acme-ops").unwrap();
        store.save(dir.path()).unwrap();
        assert!(UserStore::load_or_empty(dir.path()).users.is_empty());
    }

    #[test]
    fn rejects_admin_role_and_reserved_names() {
        let mut store = UserStore::default();
        assert!(store
            .upsert(UserRecord {
                username: "admin".into(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
            })
            .is_err());
        assert!(store
            .upsert(UserRecord {
                username: "bob".into(),
                role: "admin".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
            })
            .is_err());
    }

    #[test]
    fn tenant_upsert_remove() {
        let dir = tempdir().unwrap();
        let mut plane = ControlPlane::default();
        plane
            .upsert_tenant(TenantRecord {
                id: "acme".into(),
                name: "ACME".into(),
                building_ids: vec!["ACME".into()],
            })
            .unwrap();
        plane.save(dir.path()).unwrap();
        let loaded = ControlPlane::load_or_legacy(dir.path());
        assert_eq!(loaded.tenants.len(), 1);
        let mut plane = loaded;
        plane.remove_tenant("acme").unwrap();
        plane.save(dir.path()).unwrap();
        assert!(ControlPlane::load_or_legacy(dir.path()).tenants.is_empty());
    }
}
