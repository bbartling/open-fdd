//! Load `OPENFDD_PROVIDER_SITES` (inline JSON or file path).

use std::path::Path;

use serde::Deserialize;

use super::map::{PointMapEntry, RoleResolver};
use super::types::ProviderKind;

#[derive(Debug, Clone, Deserialize)]
pub struct SiteConfigRaw {
    pub building_id: String,
    pub provider: String,
    pub endpoint: String,
    #[serde(default)]
    pub client_id: Option<String>,
    #[serde(default)]
    pub client_secret: Option<String>,
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

#[derive(Debug, Clone)]
pub struct SiteConfig {
    pub building_id: String,
    pub kind: ProviderKind,
    pub endpoint: String,
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    pub poll_secs: u64,
    pub resolver: RoleResolver,
}

fn parse_provider_kind(raw: &str) -> Result<ProviderKind, String> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "nf" | "normal" | "normal_framework" => Ok(ProviderKind::Nf),
        "ace_iot" | "ace" | "ace-iot" => Ok(ProviderKind::AceIot),
        other => Err(format!("unknown provider {other:?}; expected nf|ace_iot")),
    }
}

/// Resolve `env:VAR` or `ENV:VAR` references; otherwise return trimmed literal.
pub fn resolve_env_ref(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Some(var) = trimmed
        .strip_prefix("env:")
        .or_else(|| trimmed.strip_prefix("ENV:"))
    {
        return std::env::var(var.trim()).ok().filter(|s| !s.is_empty());
    }
    Some(trimmed.to_string())
}

fn load_sites_json(raw: &str) -> Result<Vec<SiteConfigRaw>, String> {
    let trimmed = raw.trim();
    if trimmed.starts_with('[') {
        serde_json::from_str(trimmed).map_err(|e| e.to_string())
    } else {
        let one: SiteConfigRaw = serde_json::from_str(trimmed).map_err(|e| e.to_string())?;
        Ok(vec![one])
    }
}

pub fn load_sites_from_env() -> Result<Vec<SiteConfig>, String> {
    let Some(spec) = std::env::var("OPENFDD_PROVIDER_SITES")
        .ok()
        .filter(|s| !s.trim().is_empty())
    else {
        return Ok(Vec::new());
    };
    let trimmed = spec.trim();
    let json = if trimmed.starts_with('{') || trimmed.starts_with('[') {
        trimmed.to_string()
    } else {
        std::fs::read_to_string(Path::new(trimmed))
            .map_err(|e| format!("OPENFDD_PROVIDER_SITES path {trimmed}: {e}"))?
    };
    let raws = load_sites_json(&json)?;
    raws.into_iter().map(site_from_raw).collect()
}

fn site_from_raw(raw: SiteConfigRaw) -> Result<SiteConfig, String> {
    if raw.building_id.trim().is_empty() {
        return Err("site building_id required".into());
    }
    if raw.endpoint.trim().is_empty() {
        return Err(format!(
            "site {}: endpoint required",
            raw.building_id.trim()
        ));
    }
    let kind = parse_provider_kind(&raw.provider)?;
    let client_id = raw.client_id.as_deref().and_then(resolve_env_ref);
    let client_secret = raw.client_secret.as_deref().and_then(resolve_env_ref);
    let mut resolver = RoleResolver::from_point_map(&raw.point_map);
    if let Some(path) = raw.binding_set_path.as_deref().filter(|s| !s.is_empty()) {
        resolver.merge_binding_set_path(Path::new(path))?;
    }
    if let Some(inline) = raw.binding_set_inline.as_deref().filter(|s| !s.is_empty()) {
        resolver.merge_binding_set_json(inline)?;
    }
    Ok(SiteConfig {
        building_id: raw.building_id.trim().to_string(),
        kind,
        endpoint: raw.endpoint.trim().trim_end_matches('/').to_string(),
        client_id,
        client_secret,
        poll_secs: raw.poll_secs.max(15),
        resolver,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_ref_resolves() {
        std::env::set_var("OPENFDD_TEST_PROVIDER_SECRET", "sekret");
        assert_eq!(
            resolve_env_ref("env:OPENFDD_TEST_PROVIDER_SECRET").as_deref(),
            Some("sekret")
        );
    }
}
