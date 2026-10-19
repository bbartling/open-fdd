//! Load `OPENFDD_PROVIDER_SITES` (inline JSON or file path).
//!
//! Shareable config stores `env:NAME` credential references. Missing, empty,
//! or one-sided OAuth pairs fail configuration. Anonymous access is only the
//! explicit lab mode (`auth_mode: "anonymous"` or `OPENFDD_NF_ALLOW_ANONYMOUS`)
//! and only when no credential fields are present.

use std::fmt;
use std::path::Path;

use serde::Deserialize;

use super::http_policy::{canonicalize_provider_endpoint, connection_id};
use super::map::{PointMapEntry, RoleResolver};
use super::types::ProviderKind;

#[derive(Clone, Deserialize)]
pub struct SiteConfigRaw {
    pub building_id: String,
    pub provider: String,
    pub endpoint: String,
    #[serde(default)]
    pub provider_instance_id: Option<String>,
    #[serde(default)]
    pub client_id: Option<String>,
    #[serde(default)]
    pub client_secret: Option<String>,
    /// `oauth` (default) or `anonymous` (lab only, no credential fields).
    #[serde(default)]
    pub auth_mode: Option<String>,
    /// Loopback HTTP only, and only together with anonymous lab auth.
    #[serde(default)]
    pub allow_insecure_http: bool,
    /// `public` (default) or `private` (RFC1918 / loopback literals allowed).
    #[serde(default)]
    pub network_scope: Option<String>,
    #[serde(default = "default_poll_secs")]
    pub poll_secs: u64,
    #[serde(default)]
    pub point_map: Vec<PointMapEntry>,
    #[serde(default)]
    pub binding_set_path: Option<String>,
    #[serde(default)]
    pub binding_set_inline: Option<String>,
}

fn default_poll_secs() -> u64 {
    300
}

pub struct SiteConfig {
    pub building_id: String,
    pub provider_instance_id: String,
    pub kind: ProviderKind,
    pub endpoint: String,
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    pub anonymous: bool,
    pub poll_secs: u64,
    pub resolver: RoleResolver,
}

impl fmt::Debug for SiteConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SiteConfig")
            .field("building_id", &self.building_id)
            .field("provider_instance_id", &self.provider_instance_id)
            .field("kind", &self.kind)
            .field("endpoint", &self.endpoint)
            .field("client_id", &redacted(self.client_id.as_deref()))
            .field("client_secret", &redacted(self.client_secret.as_deref()))
            .field("anonymous", &self.anonymous)
            .field("poll_secs", &self.poll_secs)
            .field("mapped_points", &self.resolver.mapped_count())
            .finish()
    }
}

impl Clone for SiteConfig {
    fn clone(&self) -> Self {
        Self {
            building_id: self.building_id.clone(),
            provider_instance_id: self.provider_instance_id.clone(),
            kind: self.kind,
            endpoint: self.endpoint.clone(),
            client_id: self.client_id.clone(),
            client_secret: self.client_secret.clone(),
            anonymous: self.anonymous,
            poll_secs: self.poll_secs,
            resolver: self.resolver.clone(),
        }
    }
}

fn redacted(value: Option<&str>) -> &'static str {
    if value.map(|s| !s.is_empty()).unwrap_or(false) {
        "<set>"
    } else {
        "<unset>"
    }
}

fn parse_provider_kind(raw: &str) -> Result<ProviderKind, String> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "nf" | "normal" | "normal_framework" => Ok(ProviderKind::Nf),
        "ace_iot" | "ace" | "ace-iot" => Ok(ProviderKind::AceIot),
        _ => Err("unknown_provider".into()),
    }
}

/// Resolve `env:VAR`. Literals are accepted for local lab files but are never
/// written back. Unset or empty env refs fail closed.
pub fn resolve_secret_ref(value: &str) -> Result<String, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err("auth_not_configured".into());
    }
    if let Some(var) = trimmed
        .strip_prefix("env:")
        .or_else(|| trimmed.strip_prefix("ENV:"))
    {
        let name = var.trim();
        if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            return Err("auth_not_configured".into());
        }
        match std::env::var(name) {
            Ok(secret) if !secret.trim().is_empty() => Ok(secret),
            _ => Err("auth_not_configured".into()),
        }
    } else {
        Ok(trimmed.to_string())
    }
}

fn load_sites_json(raw: &str) -> Result<Vec<SiteConfigRaw>, String> {
    let trimmed = raw.trim();
    if trimmed.starts_with('[') {
        serde_json::from_str(trimmed).map_err(|_| "provider_config_json".to_string())
    } else {
        let one: SiteConfigRaw =
            serde_json::from_str(trimmed).map_err(|_| "provider_config_json".to_string())?;
        Ok(vec![one])
    }
}

#[derive(Debug)]
pub struct ProviderConfigLoad {
    pub sites: Vec<SiteConfig>,
    pub failures: Vec<SiteConfigFailure>,
    pub fatal: Option<String>,
}

#[derive(Debug, Clone)]
pub struct SiteConfigFailure {
    pub building_id: String,
    pub code: String,
}

pub fn load_sites_from_env() -> Result<ProviderConfigLoad, String> {
    let Some(spec) = std::env::var("OPENFDD_PROVIDER_SITES")
        .ok()
        .filter(|s| !s.trim().is_empty())
    else {
        return Ok(ProviderConfigLoad {
            sites: Vec::new(),
            failures: Vec::new(),
            fatal: None,
        });
    };
    let trimmed = spec.trim();
    let json = if trimmed.starts_with('{') || trimmed.starts_with('[') {
        trimmed.to_string()
    } else {
        std::fs::read_to_string(Path::new(trimmed))
            .map_err(|_| "provider_config_unreadable".to_string())?
    };
    load_sites_json_owned(&json)
}

pub fn load_sites_json_owned(json: &str) -> Result<ProviderConfigLoad, String> {
    let raws = load_sites_json(json)?;
    let mut sites = Vec::new();
    let mut failures = Vec::new();
    for raw in raws {
        let building_id = raw.building_id.trim().to_string();
        match site_from_raw(raw) {
            Ok(site) => sites.push(site),
            Err(code) => failures.push(SiteConfigFailure {
                building_id: if building_id.is_empty() {
                    "unknown".into()
                } else {
                    building_id
                },
                code,
            }),
        }
    }
    let mut seen = std::collections::HashSet::new();
    for site in &sites {
        if !seen.insert(site.provider_instance_id.clone()) {
            return Err("duplicate_provider_instance".into());
        }
    }
    Ok(ProviderConfigLoad {
        sites,
        failures,
        fatal: None,
    })
}

fn anonymous_lab_enabled() -> bool {
    std::env::var("OPENFDD_NF_ALLOW_ANONYMOUS")
        .ok()
        .is_some_and(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
}

fn site_from_raw(raw: SiteConfigRaw) -> Result<SiteConfig, String> {
    let building_id = raw.building_id.trim().to_string();
    if building_id.is_empty() {
        return Err("site_building_required".into());
    }
    let kind = parse_provider_kind(&raw.provider)?;
    let auth_mode = raw
        .auth_mode
        .as_deref()
        .map(str::trim)
        .unwrap_or("oauth")
        .to_ascii_lowercase();
    let wants_anonymous =
        auth_mode == "anonymous" || (anonymous_lab_enabled() && auth_mode != "oauth_required");
    let id_field = raw.client_id.as_deref();
    let secret_field = raw.client_secret.as_deref();
    let id_present = id_field.map(|s| !s.trim().is_empty()).unwrap_or(false);
    let secret_present = secret_field.map(|s| !s.trim().is_empty()).unwrap_or(false);
    let (client_id, client_secret, anonymous) = if matches!(kind, ProviderKind::AceIot) {
        (None, None, false)
    } else if wants_anonymous && !id_present && !secret_present {
        (None, None, true)
    } else if !id_present || !secret_present || auth_mode == "anonymous" {
        // Both missing, one-sided, or anonymous mode with credential fields.
        return Err("auth_not_configured".into());
    } else {
        let id = resolve_secret_ref(id_field.unwrap_or(""))?;
        let secret = resolve_secret_ref(secret_field.unwrap_or(""))?;
        (Some(id), Some(secret), false)
    };
    if raw.allow_insecure_http && !anonymous {
        return Err("insecure_http_with_credentials".into());
    }
    let allow_private = raw
        .network_scope
        .as_deref()
        .map(|s| s.eq_ignore_ascii_case("private"))
        .unwrap_or(false);
    let endpoint = canonicalize_provider_endpoint(
        &raw.endpoint,
        raw.allow_insecure_http && anonymous,
        allow_private,
    )?;
    let kind_slug = match kind {
        ProviderKind::Nf => "nf",
        ProviderKind::AceIot => "ace_iot",
    };
    let provider_instance_id = connection_id(
        kind_slug,
        &building_id,
        &endpoint,
        raw.provider_instance_id.as_deref(),
    )?;
    let mut resolver = RoleResolver::from_point_map(&raw.point_map)?;
    if let Some(path) = raw.binding_set_path.as_deref().filter(|s| !s.is_empty()) {
        resolver.merge_binding_set_path(Path::new(path), &building_id)?;
    }
    if let Some(inline) = raw.binding_set_inline.as_deref().filter(|s| !s.is_empty()) {
        resolver.merge_binding_set_json(inline, &building_id)?;
    }
    let poll_secs = raw.poll_secs.clamp(15, 3600);
    Ok(SiteConfig {
        building_id,
        provider_instance_id,
        kind,
        endpoint,
        client_id,
        client_secret,
        anonymous,
        poll_secs,
        resolver,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn anon_site(endpoint: &str) -> String {
        format!(
            r#"{{"building_id":"SITE","provider":"nf","endpoint":"{endpoint}","auth_mode":"anonymous"}}"#
        )
    }

    #[test]
    fn env_ref_resolves_and_missing_fails() {
        let _guard = crate::test_env_lock::lock_env();
        std::env::set_var("OPENFDD_TEST_PROVIDER_SECRET", "sekret");
        assert_eq!(
            resolve_secret_ref("env:OPENFDD_TEST_PROVIDER_SECRET").as_deref(),
            Ok("sekret")
        );
        std::env::remove_var("OPENFDD_TEST_PROVIDER_SECRET_MISSING");
        assert_eq!(
            resolve_secret_ref("env:OPENFDD_TEST_PROVIDER_SECRET_MISSING"),
            Err("auth_not_configured".into())
        );
        assert_eq!(
            resolve_secret_ref("env:"),
            Err("auth_not_configured".into())
        );
        assert_eq!(resolve_secret_ref("  "), Err("auth_not_configured".into()));
        std::env::set_var("OPENFDD_TEST_PROVIDER_SECRET_EMPTY", "");
        assert_eq!(
            resolve_secret_ref("env:OPENFDD_TEST_PROVIDER_SECRET_EMPTY"),
            Err("auth_not_configured".into())
        );
        std::env::remove_var("OPENFDD_TEST_PROVIDER_SECRET");
        std::env::remove_var("OPENFDD_TEST_PROVIDER_SECRET_EMPTY");
    }

    #[test]
    fn one_sided_oauth_and_missing_pair_fail_closed() {
        let missing = load_sites_json_owned(&anon_site("https://portal.example").replace(
            "\"auth_mode\":\"anonymous\"",
            "\"client_id\":\"env:OPENFDD_TEST_NO_SUCH_ID\"",
        ))
        .unwrap();
        assert!(missing.sites.is_empty());
        assert_eq!(missing.failures[0].code, "auth_not_configured");

        let one_sided = load_sites_json_owned(
            r#"{"building_id":"SITE","provider":"nf","endpoint":"https://portal.example","client_id":"id-only"}"#,
        )
        .unwrap();
        assert!(one_sided.sites.is_empty());
        assert_eq!(one_sided.failures[0].code, "auth_not_configured");
    }

    #[test]
    fn explicit_anonymous_lab_has_no_credential_ref() {
        let loaded = load_sites_json_owned(&anon_site("https://portal.example")).unwrap();
        assert_eq!(loaded.sites.len(), 1);
        assert!(loaded.sites[0].anonymous);
        assert!(loaded.sites[0].client_secret.is_none());
        let debug = format!("{:?}", loaded.sites[0]);
        assert!(!debug.contains("sekret"));
        assert!(debug.contains("<unset>"));
    }

    #[test]
    fn debug_redacts_resolved_secret() {
        let _guard = crate::test_env_lock::lock_env();
        std::env::set_var("OPENFDD_TEST_WAVEA_ID", "client-id");
        std::env::set_var("OPENFDD_TEST_WAVEA_SECRET", "CANARY-SECRET-VALUE");
        let loaded = load_sites_json_owned(
            r#"{"building_id":"SITE","provider":"nf","endpoint":"https://portal.example","client_id":"env:OPENFDD_TEST_WAVEA_ID","client_secret":"env:OPENFDD_TEST_WAVEA_SECRET"}"#,
        )
        .unwrap();
        let debug = format!("{:?}", loaded.sites[0]);
        assert!(!debug.contains("CANARY-SECRET-VALUE"));
        assert!(debug.contains("<set>"));
        std::env::remove_var("OPENFDD_TEST_WAVEA_ID");
        std::env::remove_var("OPENFDD_TEST_WAVEA_SECRET");
    }
}
