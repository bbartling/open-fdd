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
use uuid::Uuid;

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
        if crate::auth::is_env_identity(&name) {
            return Err("username reserved for env identities".into());
        }
        let role = Role::parse(rec.role.trim())
            .ok_or_else(|| "role must be operator or viewer".to_string())?;
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
            let prev = &self.users[idx];
            let prev_sv = prev.session_version;
            let role_changed = prev.role != next.role;
            let tenants_changed = prev.tenant_ids != next.tenant_ids;
            let disabled_changed = prev.disabled != next.disabled;
            // Keep prior password material when update omits both.
            if !has_env && !has_pw {
                next.password_env = prev.password_env.clone();
                next.password = prev.password.clone();
            } else if has_pw && !has_env {
                next.password_env = None;
            } else if has_env {
                next.password = None;
            }
            let password_changed =
                next.password_env != prev.password_env || next.password != prev.password;
            next.session_version = prev_sv;
            if role_changed || tenants_changed || disabled_changed || password_changed {
                next.session_version = prev_sv.saturating_add(1);
            }
            next.user_id = if prev.user_id.trim().is_empty() {
                Uuid::new_v4().to_string()
            } else {
                prev.user_id.clone()
            };
            self.users[idx] = next;
        } else {
            if has_env {
                next.password = None;
            }
            next.user_id = Uuid::new_v4().to_string();
            next.session_version = self
                .retired_session_floor(&name)
                .map(|sv| sv.saturating_add(1))
                .unwrap_or(0);
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
        if rec.disabled != disabled {
            rec.session_version = rec.session_version.saturating_add(1);
        }
        rec.disabled = disabled;
        Ok(())
    }

    pub fn remove(&mut self, username: &str) -> Result<(), String> {
        let idx = self
            .users
            .iter()
            .position(|u| u.username.eq_ignore_ascii_case(username.trim()))
            .ok_or_else(|| "user not found".to_string())?;
        let rec = self.users.remove(idx);
        self.note_retired(rec.username, rec.user_id, rec.session_version);
        Ok(())
    }

    pub fn get(&self, username: &str) -> Option<&UserRecord> {
        self.users
            .iter()
            .find(|u| u.username.eq_ignore_ascii_case(username.trim()))
    }
}

/// Buildings this user may cascade-delete without touching another account.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct UserCascadePlan {
    pub username: String,
    pub tenant_ids: Vec<String>,
    pub buildings_to_purge: Vec<String>,
    pub buildings_shared_skipped: Vec<String>,
}

/// Plan cascade delete for a control-plane user.
///
/// A building is purged only when **no other remaining user** has any tenant that
/// lists it. Shared buildings are skipped (fail-closed for foreign tenant data).
pub fn plan_user_cascade_delete(
    store: &UserStore,
    plane: &ControlPlane,
    username: &str,
) -> Result<UserCascadePlan, String> {
    let rec = store
        .get(username)
        .ok_or_else(|| "user not found".to_string())?;
    let tenant_ids = rec.tenant_ids.clone();
    let mut owned: Vec<String> = Vec::new();
    for tid in &tenant_ids {
        owned.extend(plane.buildings_for_tenant(tid));
    }
    owned.sort();
    owned.dedup();

    let uname = rec.username.clone();
    let mut other_buildings = std::collections::HashSet::new();
    for other in &store.users {
        if other.username.eq_ignore_ascii_case(&uname) {
            continue;
        }
        for tid in &other.tenant_ids {
            for bid in plane.buildings_for_tenant(tid) {
                other_buildings.insert(bid);
            }
        }
    }

    let mut buildings_to_purge = Vec::new();
    let mut buildings_shared_skipped = Vec::new();
    for bid in owned {
        if other_buildings.contains(&bid) {
            buildings_shared_skipped.push(bid);
        } else {
            buildings_to_purge.push(bid);
        }
    }
    Ok(UserCascadePlan {
        username: uname,
        tenant_ids,
        buildings_to_purge,
        buildings_shared_skipped,
    })
}

impl ControlPlane {
    pub fn save(&self, workspace: &Path) -> Result<(), String> {
        let path = Self::path_under_workspace(workspace);
        let body = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        atomic_write(&path, &format!("{body}\n"))
    }

    /// Create or replace one tenant.
    ///
    /// A site id may be added only when no other tenant already lists it.
    /// A tenant may keep a site id it already has, including one that another
    /// tenant also lists from an earlier file. A rejected upsert does not
    /// change this plane.
    pub fn upsert_tenant(&mut self, rec: TenantRecord) -> Result<(), TenantUpsertError> {
        let id = rec.id.trim().to_string();
        if id.is_empty() {
            return Err(TenantUpsertError::Invalid("tenant id required".into()));
        }
        if id == "legacy" {
            return Err(TenantUpsertError::Invalid(
                "tenant id 'legacy' is reserved".into(),
            ));
        }
        let mut next = rec;
        next.id = id.clone();
        if next.name.trim().is_empty() {
            next.name = id.clone();
        }
        let prior_raw = self
            .tenants
            .iter()
            .find(|tenant| tenant.id == id)
            .map(|tenant| tenant.building_ids.clone())
            .unwrap_or_default();
        let prior = normalized_site_ids(&prior_raw);
        let proposed = normalized_site_ids(&next.building_ids);
        let conflicts = new_site_conflicts(self, &id, &proposed, &prior);
        if !conflicts.is_empty() {
            return Err(TenantUpsertError::SiteConflict { conflicts });
        }
        next.building_ids = assign_site_ids(&prior_raw, &proposed);
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

/// A site id that another tenant already lists.
///
/// Reported when a create or update would add that membership. Existing rows
/// are left as stored.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct SiteMembershipConflict {
    pub site_id: String,
    pub tenant_id: String,
}

/// Why a tenant upsert did not change the control plane.
#[derive(Debug)]
pub enum TenantUpsertError {
    Invalid(String),
    SiteConflict {
        conflicts: Vec<SiteMembershipConflict>,
    },
}

/// HTTP status and JSON body for [`TenantUpsertError`].
#[derive(Debug)]
pub(crate) struct TenantUpsertRejection {
    pub status: u16,
    pub body: serde_json::Value,
}

const MAX_REPORTED_CONFLICTS: usize = 16;
const MAX_REPORTED_ID_CHARS: usize = 128;

impl TenantUpsertError {
    pub(crate) fn rejection(&self) -> TenantUpsertRejection {
        match self {
            Self::Invalid(error) => TenantUpsertRejection {
                status: 400,
                body: serde_json::json!({"ok": false, "error": error}),
            },
            Self::SiteConflict { conflicts } => {
                let total = conflicts.len();
                let reported: Vec<SiteMembershipConflict> = conflicts
                    .iter()
                    .take(MAX_REPORTED_CONFLICTS)
                    .map(SiteMembershipConflict::bounded)
                    .collect();
                TenantUpsertRejection {
                    status: 409,
                    body: serde_json::json!({
                        "ok": false,
                        "error": conflict_message(total),
                        "conflicts": reported,
                        "conflict_count": total,
                    }),
                }
            }
        }
    }
}

impl std::fmt::Display for TenantUpsertError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(error) => f.write_str(error),
            Self::SiteConflict { conflicts } => f.write_str(&conflict_message(conflicts.len())),
        }
    }
}

impl SiteMembershipConflict {
    fn bounded(&self) -> Self {
        Self {
            site_id: bounded_id(&self.site_id),
            tenant_id: bounded_id(&self.tenant_id),
        }
    }
}

fn conflict_message(total: usize) -> String {
    if total == 1 {
        "site id already assigned to another tenant".to_string()
    } else {
        format!("site id already assigned to another tenant ({total} conflicts)")
    }
}

fn bounded_id(raw: &str) -> String {
    raw.chars().take(MAX_REPORTED_ID_CHARS).collect()
}

/// Trim, drop blanks, and keep the first spelling of each site id.
fn normalized_site_ids(ids: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for raw in ids {
        let id = raw.trim();
        if id.is_empty() || out.iter().any(|seen| seen == id) {
            continue;
        }
        out.push(id.to_string());
    }
    out
}

/// New site ids in `proposed` that another tenant already lists.
fn new_site_conflicts(
    plane: &ControlPlane,
    tenant_id: &str,
    proposed: &[String],
    prior: &[String],
) -> Vec<SiteMembershipConflict> {
    let mut conflicts = Vec::new();
    for site_id in proposed {
        if prior.iter().any(|id| id == site_id) {
            continue;
        }
        for other in &plane.tenants {
            if other.id == tenant_id {
                continue;
            }
            if other
                .building_ids
                .iter()
                .any(|raw| raw.trim() == site_id.as_str())
            {
                conflicts.push(SiteMembershipConflict {
                    site_id: site_id.clone(),
                    tenant_id: other.id.clone(),
                });
            }
        }
    }
    conflicts.sort();
    conflicts.dedup();
    conflicts
}

/// Keep a site id spelling that is already stored. New ids use the trimmed form.
fn assign_site_ids(prior_raw: &[String], proposed: &[String]) -> Vec<String> {
    proposed
        .iter()
        .map(|site_id| {
            prior_raw
                .iter()
                .find(|raw| raw.trim() == site_id)
                .cloned()
                .unwrap_or_else(|| site_id.clone())
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::AuthUser;
    use crate::tenant::TenantContext;
    use crate::test_env_lock::lock_env;
    use tempfile::tempdir;

    #[test]
    fn upsert_disable_remove_user_roundtrip() {
        let dir = tempdir().unwrap();
        let mut store = UserStore::default();
        store
            .upsert(UserRecord {
                username: "acme-ops".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("secret".into()),
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        store.save(dir.path()).unwrap();
        let loaded = UserStore::load_or_empty(dir.path());
        assert_eq!(loaded.users.len(), 1);
        assert!(loaded.authenticate("acme-ops", "secret").is_some());
        assert_eq!(loaded.users[0].session_version, 0);
        assert!(!loaded.users[0].user_id.is_empty());

        let mut store = loaded;
        store.set_disabled("acme-ops", true).unwrap();
        assert_eq!(store.users[0].session_version, 1);
        store.save(dir.path()).unwrap();
        let loaded = UserStore::load_or_empty(dir.path());
        assert!(loaded.authenticate("acme-ops", "secret").is_none());

        let mut store = loaded;
        let removed_id = store.users[0].user_id.clone();
        store.remove("acme-ops").unwrap();
        store.save(dir.path()).unwrap();
        let loaded = UserStore::load_or_empty(dir.path());
        assert!(loaded.users.is_empty());
        assert!(loaded.is_retired("acme-ops"));
        assert_eq!(loaded.retired_session_floor("acme-ops"), Some(1));
        store = loaded;
        store
            .upsert(UserRecord {
                username: "acme-ops".into(),
                user_id: removed_id.clone(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("secret".into()),
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        assert_ne!(store.users[0].user_id, removed_id);
        assert_eq!(store.users[0].session_version, 2);
    }

    #[test]
    fn rejects_admin_role_and_reserved_names() {
        let mut store = UserStore::default();
        assert!(store
            .upsert(UserRecord {
                username: "admin".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
                session_version: 0,
            })
            .is_err());
        assert!(store
            .upsert(UserRecord {
                username: "bob".into(),
                user_id: String::new(),
                role: "admin".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
                session_version: 0,
            })
            .is_err());
        assert!(store
            .upsert(UserRecord {
                username: "dev".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["acme".into()],
                password_env: None,
                password: Some("x".into()),
                disabled: false,
                session_version: 0,
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

    #[test]
    fn cascade_plan_skips_buildings_shared_with_other_users() {
        let mut plane = ControlPlane::default();
        plane
            .upsert_tenant(TenantRecord {
                id: "solo".into(),
                name: "Solo".into(),
                building_ids: vec!["SOLO_SITE".into()],
            })
            .unwrap();
        plane
            .upsert_tenant(TenantRecord {
                id: "shared".into(),
                name: "Shared".into(),
                building_ids: vec!["SHARED_SITE".into()],
            })
            .unwrap();
        let mut store = UserStore::default();
        store
            .upsert(UserRecord {
                username: "alice".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["solo".into(), "shared".into()],
                password_env: None,
                password: Some("a".into()),
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        store
            .upsert(UserRecord {
                username: "bob".into(),
                user_id: String::new(),
                role: "operator".into(),
                tenant_ids: vec!["shared".into()],
                password_env: None,
                password: Some("b".into()),
                disabled: false,
                session_version: 0,
            })
            .unwrap();
        let plan = plan_user_cascade_delete(&store, &plane, "alice").unwrap();
        assert_eq!(plan.buildings_to_purge, vec!["SOLO_SITE".to_string()]);
        assert_eq!(
            plan.buildings_shared_skipped,
            vec!["SHARED_SITE".to_string()]
        );
    }

    fn operator(sub: &str, tenant_id: &str) -> AuthUser {
        AuthUser {
            sub: sub.to_string(),
            role: Role::Operator,
            tenant_ids: vec![tenant_id.to_string()],
            active_tenant_id: None,
        }
    }

    #[test]
    fn load_leaves_existing_shared_site_memberships_unchanged() {
        let dir = tempdir().unwrap();
        let path = ControlPlane::path_under_workspace(dir.path());
        fs::create_dir_all(path.parent().expect("control plane parent")).unwrap();
        let raw = "{\n  \"tenants\": [\n    {\"id\": \"tenant-a\", \"name\": \"A\", \"building_ids\": [\"site-shared\"]},\n    {\"id\": \"tenant-b\", \"name\": \"B\", \"building_ids\": [\"site-shared\"]}\n  ]\n}\n";
        fs::write(&path, raw).unwrap();
        let plane = ControlPlane::load_or_legacy(dir.path());
        assert_eq!(
            plane.buildings_for_tenant("tenant-a"),
            vec!["site-shared".to_string()]
        );
        assert_eq!(
            plane.buildings_for_tenant("tenant-b"),
            vec!["site-shared".to_string()]
        );
        assert_eq!(fs::read_to_string(&path).unwrap(), raw);
    }

    #[test]
    fn existing_shared_site_keeps_own_access_and_foreign_denial() {
        let _env = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "1");
        let plane = shared_plane();
        let ctx_a =
            TenantContext::resolve(&operator("operator-a", "tenant-a"), &plane).expect("tenant a");
        assert!(ctx_a.allow_building("site-shared"));
        assert!(ctx_a.allow_building("site-a"));
        assert!(!ctx_a.allow_building("site-b"));
        let ctx_b =
            TenantContext::resolve(&operator("operator-b", "tenant-b"), &plane).expect("tenant b");
        assert!(ctx_b.allow_building(" site-shared "));
        assert!(ctx_b.allow_building("site-b"));
        assert!(!ctx_b.allow_building("site-a"));
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }

    #[test]
    fn site_creation_rejects_a_site_another_tenant_already_lists() {
        let mut plane = shared_plane();
        let stored = serde_json::to_string(&plane).unwrap();

        let err = plane
            .upsert_tenant(TenantRecord {
                id: "tenant-c".into(),
                name: "C".into(),
                building_ids: vec![" site-shared ".into(), "site-c".into()],
            })
            .expect_err("shared site is not a new assignment");
        let TenantUpsertError::SiteConflict { conflicts } = &err else {
            panic!("expected a site conflict, got {err}");
        };
        assert_eq!(
            conflicts,
            &vec![
                SiteMembershipConflict {
                    site_id: "site-shared".into(),
                    tenant_id: "tenant-a".into(),
                },
                SiteMembershipConflict {
                    site_id: "site-shared".into(),
                    tenant_id: "tenant-b".into(),
                },
            ]
        );
        let rejection = err.rejection();
        assert_eq!(rejection.status, 409);
        assert_eq!(rejection.body["ok"], false);
        assert_eq!(rejection.body["conflict_count"], 2);
        assert_eq!(
            rejection.body["error"],
            "site id already assigned to another tenant (2 conflicts)"
        );
        assert_eq!(serde_json::to_string(&plane).unwrap(), stored);

        plane
            .upsert_tenant(TenantRecord {
                id: "tenant-a".into(),
                name: "A renamed".into(),
                building_ids: vec!["site-shared".into(), "site-a".into()],
            })
            .expect("existing membership can be saved again");
        assert_eq!(
            plane.buildings_for_tenant("tenant-a"),
            vec!["site-shared".to_string(), "site-a".to_string()]
        );
        assert_eq!(
            plane.buildings_for_tenant("tenant-b"),
            vec![" site-shared ".to_string(), "site-b".to_string()]
        );
        assert_eq!(
            plane
                .tenants
                .iter()
                .find(|tenant| tenant.id == "tenant-a")
                .map(|tenant| tenant.name.as_str()),
            Some("A renamed")
        );
    }

    #[test]
    fn site_creation_accepts_a_new_id_and_a_released_id() {
        let mut plane = shared_plane();
        plane
            .upsert_tenant(TenantRecord {
                id: "tenant-c".into(),
                name: "C".into(),
                building_ids: vec![" site-c ".into(), "site-c".into(), "  ".into()],
            })
            .expect("new site");
        assert_eq!(
            plane.buildings_for_tenant("tenant-c"),
            vec!["site-c".to_string()]
        );

        let blocked = plane
            .upsert_tenant(TenantRecord {
                id: "tenant-c".into(),
                name: "C renamed".into(),
                building_ids: vec!["site-c".into(), "site-b".into()],
            })
            .expect_err("site-b stays with tenant-b");
        assert_eq!(blocked.rejection().status, 409);
        assert_eq!(blocked.rejection().body["conflict_count"], 1);
        assert_eq!(
            plane
                .tenants
                .iter()
                .find(|tenant| tenant.id == "tenant-c")
                .map(|tenant| tenant.name.as_str()),
            Some("C")
        );
        assert_eq!(
            plane.buildings_for_tenant("tenant-c"),
            vec!["site-c".to_string()]
        );

        plane
            .upsert_tenant(TenantRecord {
                id: "tenant-b".into(),
                name: "B".into(),
                building_ids: vec![" site-shared ".into()],
            })
            .expect("release site-b");
        plane
            .upsert_tenant(TenantRecord {
                id: "tenant-c".into(),
                name: "C".into(),
                building_ids: vec!["site-c".into(), "site-b".into()],
            })
            .expect("site-b after release");
        assert_eq!(
            plane.buildings_for_tenant("tenant-c"),
            vec!["site-c".to_string(), "site-b".to_string()]
        );
        assert!(!plane
            .buildings_for_tenant("tenant-b")
            .iter()
            .any(|site| site.trim() == "site-b"));
    }

    fn shared_plane() -> ControlPlane {
        ControlPlane {
            tenants: vec![
                TenantRecord {
                    id: "tenant-a".into(),
                    name: "A".into(),
                    building_ids: vec!["site-shared".into(), "site-a".into()],
                },
                TenantRecord {
                    id: "tenant-b".into(),
                    name: "B".into(),
                    building_ids: vec![" site-shared ".into(), "site-b".into()],
                },
            ],
        }
    }
}
