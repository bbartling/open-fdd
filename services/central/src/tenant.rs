//! Wave L Phase 1 - multi-tenant mode flag + TenantContext + file control plane.
//!
//! Default: **OFF** (`OPENFDD_MULTI_TENANT` unset/0/false). Single-tenant hub
//! semantics unchanged. When ON (lab only until Tier-2), building access must
//! resolve through membership - fail closed.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::auth::{AuthUser, Role};

/// Env flag - multi-tenant shared-hosting mode. Default off.
pub fn multi_tenant_enabled() -> bool {
    match std::env::var("OPENFDD_MULTI_TENANT") {
        Ok(v) => matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
        Err(_) => false,
    }
}

/// Server-side tenant / building scope for a request.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
pub struct TenantContext {
    /// Active tenant id when multi-tenant mode is on and membership resolved.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tenant_id: Option<String>,
    /// Buildings the subject may access (empty = hub-wide when `hub_admin`).
    #[serde(default)]
    pub building_ids: Vec<String>,
    /// Hub operator may cross tenants when mode is on.
    pub hub_admin: bool,
    /// Echo of [`multi_tenant_enabled`] at resolve time.
    pub multi_tenant: bool,
}

impl TenantContext {
    /// Single-tenant / flag-OFF passthrough - preserves today's hub semantics.
    pub fn single_tenant_passthrough(user: &AuthUser) -> Self {
        Self {
            tenant_id: Some("legacy".into()),
            building_ids: vec![],
            hub_admin: matches!(user.role, Role::Admin),
            multi_tenant: false,
        }
    }

    /// Resolve context from JWT membership claims + optional control plane.
    pub fn resolve(user: &AuthUser, plane: &ControlPlane) -> Result<Self, String> {
        if !multi_tenant_enabled() {
            return Ok(Self::single_tenant_passthrough(user));
        }
        let hub_admin = matches!(user.role, Role::Admin) && user.tenant_ids.is_empty();
        if hub_admin {
            return Ok(Self {
                tenant_id: None,
                building_ids: plane.all_building_ids(),
                hub_admin: true,
                multi_tenant: true,
            });
        }
        if user.tenant_ids.is_empty() {
            return Err("multi-tenant mode requires tenant membership claims".into());
        }
        let tenant_id = user.tenant_ids[0].clone();
        let building_ids = plane.buildings_for_tenant(&tenant_id);
        Ok(Self {
            tenant_id: Some(tenant_id),
            building_ids,
            hub_admin: false,
            multi_tenant: true,
        })
    }

    /// Fail-closed building gate when mode is on.
    pub fn allow_building(&self, building_id: &str) -> bool {
        if !self.multi_tenant {
            return true;
        }
        if self.hub_admin {
            return true;
        }
        self.building_ids.iter().any(|b| b == building_id)
    }

    /// Resolve Parquet historian root for this context.
    ///
    /// Mode OFF ? `base` unchanged (today's single-hub layout).
    /// Mode ON ? `{base}/tenants/{tenant_id}` (hub_admin without a selected
    /// tenant must pass an explicit tid; otherwise fail closed).
    pub fn historian_root(&self, base: &std::path::Path) -> Result<std::path::PathBuf, String> {
        if !self.multi_tenant {
            return Ok(base.to_path_buf());
        }
        let tid = self.tenant_id.as_deref().ok_or_else(|| {
            "multi-tenant historian root requires an active tenant_id".to_string()
        })?;
        fdd_store::tenant_storage_root(base, Some(tid)).map_err(|e| e.to_string())
    }

    /// Relative prefix under the hub storage root (empty when mode OFF).
    pub fn historian_prefix(&self) -> Result<String, String> {
        if !self.multi_tenant {
            return Ok(String::new());
        }
        let tid = self.tenant_id.as_deref().ok_or_else(|| {
            "multi-tenant historian prefix requires an active tenant_id".to_string()
        })?;
        fdd_store::tenant_storage_prefix(Some(tid)).map_err(|e| e.to_string())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct TenantRecord {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub building_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, Default)]
pub struct ControlPlane {
    #[serde(default)]
    pub tenants: Vec<TenantRecord>,
}

impl ControlPlane {
    pub fn legacy_default() -> Self {
        Self {
            tenants: vec![TenantRecord {
                id: "legacy".into(),
                name: "Legacy single-hub tenant".into(),
                building_ids: vec![],
            }],
        }
    }

    pub fn path_under_workspace(workspace: &Path) -> PathBuf {
        workspace
            .join("openfdd")
            .join("control_plane")
            .join("tenants.json")
    }

    pub fn load_or_legacy(workspace: &Path) -> Self {
        let path = Self::path_under_workspace(workspace);
        match fs::read_to_string(&path) {
            Ok(raw) => serde_json::from_str(&raw).unwrap_or_else(|_| Self::legacy_default()),
            Err(_) => Self::legacy_default(),
        }
    }

    pub fn buildings_for_tenant(&self, tenant_id: &str) -> Vec<String> {
        self.tenants
            .iter()
            .find(|t| t.id == tenant_id)
            .map(|t| t.building_ids.clone())
            .unwrap_or_default()
    }

    pub fn all_building_ids(&self) -> Vec<String> {
        let mut out = Vec::new();
        for t in &self.tenants {
            out.extend(t.building_ids.iter().cloned());
        }
        out.sort();
        out.dedup();
        out
    }
}

#[derive(Debug, Serialize, ToSchema)]
pub struct TenantsListResponse {
    pub ok: bool,
    pub multi_tenant: bool,
    /// Active tenant from [`TenantContext::resolve`] (legacy when mode OFF).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_tenant_id: Option<String>,
    /// Buildings allowed for the resolved context (empty = hub-wide / no plane buildings).
    #[serde(default)]
    pub buildings_visible: Vec<String>,
    /// Relative historian prefix under the hub Parquet root (empty when mode OFF).
    #[serde(default)]
    pub historian_prefix: String,
    pub tenants: Vec<TenantRecord>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::{AuthUser, Role};
    use crate::test_env_lock::lock_env;

    #[test]
    fn multi_tenant_flag_defaults_off() {
        let _g = lock_env();
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        assert!(!multi_tenant_enabled());
    }

    #[test]
    fn multi_tenant_flag_on() {
        let _g = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "1");
        assert!(multi_tenant_enabled());
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }

    #[test]
    fn resolve_off_is_legacy_passthrough() {
        let _g = lock_env();
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        let user = AuthUser {
            sub: "admin".into(),
            role: Role::Admin,
            tenant_ids: vec![],
        };
        let plane = ControlPlane::legacy_default();
        let ctx = TenantContext::resolve(&user, &plane).expect("resolve");
        assert!(!ctx.multi_tenant);
        assert_eq!(ctx.tenant_id.as_deref(), Some("legacy"));
        assert!(ctx.allow_building("BUILDING_100"));
    }

    #[test]
    fn resolve_on_without_membership_fails_closed() {
        let _g = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "true");
        let user = AuthUser {
            sub: "operator".into(),
            role: Role::Operator,
            tenant_ids: vec![],
        };
        let plane = ControlPlane::legacy_default();
        let err = TenantContext::resolve(&user, &plane).expect_err("deny");
        assert!(err.contains("membership"));
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }

    #[test]
    fn resolve_on_scopes_buildings() {
        let _g = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "on");
        let user = AuthUser {
            sub: "eng".into(),
            role: Role::Operator,
            tenant_ids: vec!["acme".into()],
        };
        let plane = ControlPlane {
            tenants: vec![TenantRecord {
                id: "acme".into(),
                name: "Acme".into(),
                building_ids: vec!["bldg2".into()],
            }],
        };
        let ctx = TenantContext::resolve(&user, &plane).expect("resolve");
        assert!(ctx.multi_tenant);
        assert!(ctx.allow_building("bldg2"));
        assert!(!ctx.allow_building("BUILDING_100"));
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }

    #[test]
    fn historian_root_off_is_hub_base() {
        let _g = lock_env();
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        let user = AuthUser {
            sub: "admin".into(),
            role: Role::Admin,
            tenant_ids: vec![],
        };
        let plane = ControlPlane::legacy_default();
        let ctx = TenantContext::resolve(&user, &plane).expect("resolve");
        let base = std::path::Path::new("/workspace/openfdd");
        assert_eq!(ctx.historian_root(base).unwrap(), base);
        assert_eq!(ctx.historian_prefix().unwrap(), "");
    }

    #[test]
    fn historian_root_on_partitions_by_tenant() {
        let _g = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "1");
        let user = AuthUser {
            sub: "eng".into(),
            role: Role::Operator,
            tenant_ids: vec!["acme".into()],
        };
        let plane = ControlPlane {
            tenants: vec![TenantRecord {
                id: "acme".into(),
                name: "Acme".into(),
                building_ids: vec!["bldg2".into()],
            }],
        };
        let ctx = TenantContext::resolve(&user, &plane).expect("resolve");
        let base = std::path::Path::new("/workspace/openfdd");
        assert_eq!(
            ctx.historian_root(base).unwrap(),
            base.join("tenants").join("acme")
        );
        assert_eq!(ctx.historian_prefix().unwrap(), "tenants/acme");
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }

    /// Wave L L6 — synthetic Tenant A↔B: identical building labels must not cross roots.
    #[test]
    fn ab_isolation_buildings_and_roots() {
        let _g = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "1");
        let plane = ControlPlane {
            tenants: vec![
                TenantRecord {
                    id: "tenant_a".into(),
                    name: "Firm A".into(),
                    building_ids: vec!["site_x".into()],
                },
                TenantRecord {
                    id: "tenant_b".into(),
                    name: "Firm B".into(),
                    building_ids: vec!["site_x".into()],
                },
            ],
        };
        let user_a = AuthUser {
            sub: "a".into(),
            role: Role::Operator,
            tenant_ids: vec!["tenant_a".into()],
        };
        let user_b = AuthUser {
            sub: "b".into(),
            role: Role::Operator,
            tenant_ids: vec!["tenant_b".into()],
        };
        let ctx_a = TenantContext::resolve(&user_a, &plane).expect("a");
        let ctx_b = TenantContext::resolve(&user_b, &plane).expect("b");
        assert!(ctx_a.allow_building("site_x"));
        assert!(ctx_b.allow_building("site_x"));
        // Membership is per-tenant; foreign tenant_id is not in either context.
        assert_eq!(ctx_a.tenant_id.as_deref(), Some("tenant_a"));
        assert_eq!(ctx_b.tenant_id.as_deref(), Some("tenant_b"));
        let base = std::path::Path::new("/workspace/openfdd");
        let root_a = ctx_a.historian_root(base).unwrap();
        let root_b = ctx_b.historian_root(base).unwrap();
        assert_ne!(root_a, root_b);
        assert!(root_a.ends_with("tenants/tenant_a"));
        assert!(root_b.ends_with("tenants/tenant_b"));
        assert!(!root_a.starts_with(&root_b));
        assert!(!root_b.starts_with(&root_a));
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }
}
