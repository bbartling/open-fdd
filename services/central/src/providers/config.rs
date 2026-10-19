//! Load `OPENFDD_PROVIDER_SITES` (inline JSON or file path).
//!
//! Shareable config stores `env:NAME` credential references. Missing, empty,
//! or one-sided OAuth pairs fail configuration. Anonymous access is only the
//! explicit lab mode (`auth_mode: "anonymous"` or `OPENFDD_NF_ALLOW_ANONYMOUS`)
//! and only when no credential fields are present.

use std::fmt;
use std::path::Path;

use serde::Deserialize;

use super::committed_model::{
    model_from_sparql_rows, CommittedModel, CommittedModelStore, ModelScope,
};
use super::http_policy::{canonicalize_provider_endpoint, connection_id};
use super::map::{PointMapEntry, RoleResolver};
use super::meteo::{self, MAX_METEO_SERIES};
use super::types::ProviderKind;
use open_fdd_edge_prototype::csv_ingest::portal_ingest_sparql::{
    compile_bindings_from_snapshot, IngestSparqlScope,
};

#[derive(Clone, Deserialize)]
pub struct SiteConfigRaw {
    pub building_id: String,
    #[serde(default)]
    pub tenant_id: Option<String>,
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
    /// Decimal degrees. Required for `open_meteo`.
    #[serde(default)]
    pub latitude: Option<f64>,
    /// Decimal degrees. Required for `open_meteo`.
    #[serde(default)]
    pub longitude: Option<f64>,
}

fn default_poll_secs() -> u64 {
    300
}

pub struct SiteConfig {
    pub building_id: String,
    pub tenant_id: String,
    /// Wave-A connection id (`kind:explicit` or `kind:building:digest`).
    pub provider_instance_id: String,
    pub kind: ProviderKind,
    pub endpoint: String,
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    pub anonymous: bool,
    pub poll_secs: u64,
    pub latitude: Option<f64>,
    pub longitude: Option<f64>,
    pub resolver: RoleResolver,
    pub model: CommittedModel,
}

impl fmt::Debug for SiteConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SiteConfig")
            .field("building_id", &self.building_id)
            .field("tenant_id", &self.tenant_id)
            .field("provider_instance_id", &self.provider_instance_id)
            .field("model_revision", &self.resolver.model_revision())
            .field("kind", &self.kind)
            .field("endpoint", &self.endpoint)
            .field("client_id", &redacted(self.client_id.as_deref()))
            .field("client_secret", &redacted(self.client_secret.as_deref()))
            .field("anonymous", &self.anonymous)
            .field("poll_secs", &self.poll_secs)
            .field("latitude", &self.latitude)
            .field("longitude", &self.longitude)
            .field("mapped_points", &self.resolver.mapped_count())
            .finish()
    }
}

impl Clone for SiteConfig {
    fn clone(&self) -> Self {
        Self {
            building_id: self.building_id.clone(),
            tenant_id: self.tenant_id.clone(),
            provider_instance_id: self.provider_instance_id.clone(),
            kind: self.kind,
            endpoint: self.endpoint.clone(),
            client_id: self.client_id.clone(),
            client_secret: self.client_secret.clone(),
            anonymous: self.anonymous,
            poll_secs: self.poll_secs,
            latitude: self.latitude,
            longitude: self.longitude,
            resolver: self.resolver.clone(),
            model: self.model.clone(),
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
        "open_meteo" | "open-meteo" | "meteo" => Ok(ProviderKind::OpenMeteo),
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
    } else if matches!(kind, ProviderKind::OpenMeteo) {
        if id_present || secret_present {
            return Err("meteo_credentials_rejected".into());
        }
        (None, None, true)
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
    if matches!(kind, ProviderKind::OpenMeteo) && raw.allow_insecure_http {
        return Err("meteo_https_required".into());
    }
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
        ProviderKind::OpenMeteo => "open_meteo",
    };
    let provider_instance_id = connection_id(
        kind_slug,
        &building_id,
        &endpoint,
        raw.provider_instance_id.as_deref(),
    )?;
    let tenant_id = raw
        .tenant_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "tenant_required".to_string())?
        .to_string();
    let (latitude, longitude) = if matches!(kind, ProviderKind::OpenMeteo) {
        if !meteo::public_origin(&endpoint) {
            return Err("meteo_host".into());
        }
        let latitude = raw.latitude.ok_or("meteo_coordinates")?;
        let longitude = raw.longitude.ok_or("meteo_coordinates")?;
        if !meteo::valid_coords(latitude, longitude) {
            return Err("meteo_coordinates".into());
        }
        let ids: Vec<&str> = raw
            .point_map
            .iter()
            .map(|entry| entry.provider_point_id.as_str())
            .collect();
        if ids.is_empty() || ids.len() > MAX_METEO_SERIES {
            return Err("meteo_series".into());
        }
        if ids.iter().any(|id| !meteo::series_allowed(id)) {
            return Err("meteo_series".into());
        }
        (Some(latitude), Some(longitude))
    } else {
        (None, None)
    };
    let model_instance =
        model_instance_id(raw.provider_instance_id.as_deref(), &provider_instance_id)?;
    let scope = ModelScope {
        tenant_id: tenant_id.clone(),
        site_id: building_id.clone(),
        provider_instance_id: model_instance,
    };
    let (resolver, model) = compile_site_model(&raw, &scope)?;
    if matches!(kind, ProviderKind::OpenMeteo) {
        let scheduled = resolver.provider_point_ids();
        if scheduled.is_empty()
            || scheduled.len() > MAX_METEO_SERIES
            || scheduled.iter().any(|id| !meteo::series_allowed(id))
        {
            return Err("meteo_series".into());
        }
    }
    let poll_secs = raw.poll_secs.clamp(15, 3600);
    Ok(SiteConfig {
        building_id,
        tenant_id,
        provider_instance_id,
        kind,
        endpoint,
        client_id,
        client_secret,
        anonymous,
        poll_secs,
        latitude,
        longitude,
        resolver,
        model,
    })
}

fn model_instance_id(explicit: Option<&str>, connection_id: &str) -> Result<String, String> {
    let raw = explicit
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or(connection_id);
    let slug = raw.replace(':', "-");
    if slug.is_empty()
        || !slug
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return Err("provider_instance_id".into());
    }
    Ok(slug)
}

fn compile_site_model(
    raw: &SiteConfigRaw,
    scope: &ModelScope,
) -> Result<(RoleResolver, CommittedModel), String> {
    let has_map = !raw.point_map.is_empty();
    let binding_path = raw.binding_set_path.as_deref().filter(|s| !s.is_empty());
    let binding_inline = raw.binding_set_inline.as_deref().filter(|s| !s.is_empty());
    if has_map && (binding_path.is_some() || binding_inline.is_some()) {
        return Err("one_committed_model".into());
    }
    if binding_path.is_some() && binding_inline.is_some() {
        return Err("one_committed_model".into());
    }
    if let Some(path) = binding_path {
        let text = std::fs::read_to_string(Path::new(path))
            .map_err(|_| "binding_set_unreadable".to_string())?;
        return load_committed_binding(&text, scope);
    }
    if let Some(inline) = binding_inline {
        return load_committed_binding(inline, scope);
    }
    RoleResolver::compile_point_map(scope, &raw.point_map)
}

fn load_committed_binding(
    raw: &str,
    scope: &ModelScope,
) -> Result<(RoleResolver, CommittedModel), String> {
    let trimmed = raw.trim_start();
    if trimmed.starts_with('{') {
        return RoleResolver::from_committed_json(raw, scope).map_err(model_error_code);
    }
    let graph = format!(
        "urn:openfdd:ingest:v1:graph/{}/{}",
        scope.tenant_id, scope.site_id
    );
    let sparql_scope = IngestSparqlScope::new(
        scope.tenant_id.clone(),
        scope.site_id.clone(),
        graph,
        scope.provider_instance_id.clone(),
    );
    let rows = compile_bindings_from_snapshot(raw, &sparql_scope).map_err(model_error_code)?;
    let model = model_from_sparql_rows(scope, &rows).map_err(model_error_code)?;
    let mut store = CommittedModelStore::default();
    store.try_activate(None, &model).map_err(model_error_code)?;
    let plan = store
        .active_plan(&scope.tenant_id, &scope.site_id)
        .ok_or_else(|| "model_not_activated".to_string())?;
    Ok((RoleResolver::from_plan(plan), model))
}

fn model_error_code(err: String) -> String {
    if err.contains("truncated") {
        "truncated_model".into()
    } else if err.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') && err.len() <= 64 {
        err
    } else {
        "model_invalid".into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn anon_site(endpoint: &str) -> String {
        format!(
            r#"{{"building_id":"SITE","tenant_id":"tenant-a","provider":"nf","endpoint":"{endpoint}","auth_mode":"anonymous"}}"#
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
            r#"{"building_id":"SITE","tenant_id":"tenant-a","provider":"nf","endpoint":"https://portal.example","client_id":"id-only"}"#,
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
            r#"{"building_id":"SITE","tenant_id":"tenant-a","provider":"nf","endpoint":"https://portal.example","client_id":"env:OPENFDD_TEST_WAVEA_ID","client_secret":"env:OPENFDD_TEST_WAVEA_SECRET"}"#,
        )
        .unwrap();
        let debug = format!("{:?}", loaded.sites[0]);
        assert!(!debug.contains("CANARY-SECRET-VALUE"));
        assert!(debug.contains("<set>"));
        std::env::remove_var("OPENFDD_TEST_WAVEA_ID");
        std::env::remove_var("OPENFDD_TEST_WAVEA_SECRET");
    }

    #[test]
    fn open_meteo_site_is_anonymous_and_explicitly_mapped() {
        let loaded = load_sites_json_owned(
            r#"{
                "building_id":"SITE",
                "tenant_id":"tenant-a",
                "provider":"open_meteo",
                "endpoint":"https://api.open-meteo.com",
                "latitude":43.07,
                "longitude":-89.4,
                "point_map":[{
                    "provider_point_id":"temperature_2m",
                    "equipment_id":"WEATHER",
                    "role":"web-outside-air-temp",
                    "equip_type":"weather"
                }]
            }"#,
        )
        .unwrap();
        assert!(loaded.failures.is_empty());
        assert_eq!(loaded.sites.len(), 1);
        let site = &loaded.sites[0];
        assert_eq!(site.kind, ProviderKind::OpenMeteo);
        assert!(site.anonymous);
        assert!(site.client_id.is_none());
        assert!(site.client_secret.is_none());
        assert!((site.latitude.unwrap() - 43.07).abs() < 1e-9);
        assert!((site.longitude.unwrap() + 89.4).abs() < 1e-9);
        assert_eq!(site.resolver.mapped_count(), 1);
        assert!(site.provider_instance_id.starts_with("open_meteo:"));
    }

    #[test]
    fn open_meteo_rejects_secrets_foreign_hosts_and_display_names() {
        let secret = load_sites_json_owned(
            r#"{"building_id":"SITE","tenant_id":"tenant-a","provider":"open_meteo","endpoint":"https://api.open-meteo.com","latitude":1.0,"longitude":2.0,"client_id":"id","client_secret":"sek","point_map":[{"provider_point_id":"temperature_2m","equipment_id":"WEATHER","role":"web-outside-air-temp"}]}"#,
        )
        .unwrap();
        assert!(secret.sites.is_empty());
        assert_eq!(secret.failures[0].code, "meteo_credentials_rejected");

        let host = load_sites_json_owned(
            r#"{"building_id":"SITE","tenant_id":"tenant-a","provider":"open_meteo","endpoint":"https://example.com","latitude":1.0,"longitude":2.0,"point_map":[{"provider_point_id":"temperature_2m","equipment_id":"WEATHER","role":"web-outside-air-temp"}]}"#,
        )
        .unwrap();
        assert_eq!(host.failures[0].code, "meteo_host");

        let named = load_sites_json_owned(
            r#"{"building_id":"SITE","tenant_id":"tenant-a","provider":"open_meteo","endpoint":"https://api.open-meteo.com","latitude":1.0,"longitude":2.0,"point_map":[{"provider_point_id":"Outside Air Temp","equipment_id":"WEATHER","role":"web-outside-air-temp"}]}"#,
        )
        .unwrap();
        assert_eq!(named.failures[0].code, "meteo_series");

        let coords = load_sites_json_owned(
            r#"{"building_id":"SITE","tenant_id":"tenant-a","provider":"open_meteo","endpoint":"https://api.open-meteo.com","point_map":[{"provider_point_id":"temperature_2m","equipment_id":"WEATHER","role":"web-outside-air-temp"}]}"#,
        )
        .unwrap();
        assert_eq!(coords.failures[0].code, "meteo_coordinates");
    }

    #[test]
    fn missing_tenant_fails_closed() {
        let loaded = load_sites_json_owned(
            r#"{"building_id":"SITE","provider":"nf","endpoint":"https://portal.example","auth_mode":"anonymous"}"#,
        )
        .unwrap();
        assert!(loaded.sites.is_empty());
        assert_eq!(loaded.failures[0].code, "tenant_required");
    }

    #[test]
    fn point_map_and_binding_set_are_not_two_truths() {
        let raw = r#"{
            "building_id": "site-a",
            "tenant_id": "tenant-a",
            "provider_instance_id": "nf-conn-a",
            "provider": "nf",
            "endpoint": "https://portal.example",
            "auth_mode": "anonymous",
            "point_map": [{
                "provider_point_id": "uuid-sat",
                "equipment_id": "AHU_1",
                "role": "sat",
                "equip_type": "ahu"
            }],
            "binding_set_inline": "{\"schema\":\"ofdd_portal_committed_model_v1\"}"
        }"#;
        let loaded = load_sites_json_owned(raw).unwrap();
        assert!(loaded.sites.is_empty());
        assert_eq!(loaded.failures[0].code, "one_committed_model");
    }

    #[test]
    fn binding_set_rejects_truncated_export() {
        let raw = r#"{
            "building_id": "site-a",
            "tenant_id": "tenant-a",
            "provider_instance_id": "nf-conn-a",
            "provider": "nf",
            "endpoint": "https://portal.example",
            "auth_mode": "anonymous",
            "binding_set_inline": "{\"schema\":\"ofdd_portal_committed_model_v1\",\"tenant_id\":\"tenant-a\",\"site_id\":\"site-a\",\"provider_instance_id\":\"nf-conn-a\",\"truncated\":true,\"equipment\":[]}"
        }"#;
        let loaded = load_sites_json_owned(raw).unwrap();
        assert!(loaded.sites.is_empty());
        assert_eq!(loaded.failures[0].code, "truncated_model");
    }
}
