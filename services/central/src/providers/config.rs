//! Load `OPENFDD_PROVIDER_SITES` (inline JSON or file path).

use std::path::Path;

use serde::Deserialize;

use super::committed_model::{
    model_from_point_map, model_from_sparql_rows, CommittedModel, CommittedModelStore, ModelScope,
};
use super::map::{PointMapEntry, RoleResolver};
use super::types::ProviderKind;
use open_fdd_edge_prototype::csv_ingest::portal_ingest_sparql::{
    compile_bindings_from_snapshot, IngestSparqlScope,
};

#[derive(Debug, Clone, Deserialize)]
pub struct SiteConfigRaw {
    pub building_id: String,
    #[serde(default)]
    pub tenant_id: Option<String>,
    #[serde(default)]
    pub provider_instance_id: Option<String>,
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
    pub tenant_id: String,
    pub provider_instance_id: String,
    pub kind: ProviderKind,
    pub endpoint: String,
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    pub poll_secs: u64,
    pub resolver: RoleResolver,
    pub model: CommittedModel,
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
    let tenant_id = raw
        .tenant_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| format!("site {}: tenant_id required", raw.building_id.trim()))?
        .to_string();
    let provider_instance_id = raw
        .provider_instance_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            format!(
                "site {}: provider_instance_id required",
                raw.building_id.trim()
            )
        })?
        .to_string();
    let scope = ModelScope {
        tenant_id: tenant_id.clone(),
        site_id: raw.building_id.trim().to_string(),
        provider_instance_id: provider_instance_id.clone(),
    };
    let has_map = !raw.point_map.is_empty();
    let binding_path = raw.binding_set_path.as_deref().filter(|s| !s.is_empty());
    let binding_inline = raw.binding_set_inline.as_deref().filter(|s| !s.is_empty());
    if has_map && (binding_path.is_some() || binding_inline.is_some()) {
        return Err(format!(
            "site {}: one committed model; point_map and binding_set cannot both be set",
            scope.site_id
        ));
    }
    if binding_path.is_some() && binding_inline.is_some() {
        return Err(format!(
            "site {}: binding_set_path and binding_set_inline cannot both be set",
            scope.site_id
        ));
    }
    let (resolver, model) = if let Some(path) = binding_path {
        let raw = std::fs::read_to_string(Path::new(path))
            .map_err(|e| format!("read committed model {path}: {e}"))?;
        if raw.trim_start().starts_with('{') {
            RoleResolver::from_committed_path(Path::new(path), &scope)?
        } else {
            load_committed_binding(&raw, &scope)?
        }
    } else if let Some(inline) = binding_inline {
        load_committed_binding(inline, &scope)?
    } else if has_map {
        let resolver = RoleResolver::from_point_map(&scope, &raw.point_map)?;
        let model = model_from_point_map(&scope, &point_bootstrap(&raw.point_map))?;
        (resolver, model)
    } else {
        let model = model_from_point_map(&scope, &[])?;
        (RoleResolver::default(), model)
    };
    Ok(SiteConfig {
        building_id: scope.site_id,
        tenant_id,
        provider_instance_id,
        kind,
        endpoint: raw.endpoint.trim().trim_end_matches('/').to_string(),
        client_id,
        client_secret,
        poll_secs: raw.poll_secs.max(15),
        resolver,
        model,
    })
}

fn load_committed_binding(
    raw: &str,
    scope: &ModelScope,
) -> Result<(RoleResolver, CommittedModel), String> {
    let trimmed = raw.trim_start();
    if trimmed.starts_with('{') {
        return RoleResolver::from_committed_json(raw, scope);
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
    let rows = compile_bindings_from_snapshot(raw, &sparql_scope)?;
    let model = model_from_sparql_rows(scope, &rows)?;
    let mut store = CommittedModelStore::default();
    store.try_activate(None, &model)?;
    let plan = store
        .active_plan(&scope.tenant_id, &scope.site_id)
        .ok_or_else(|| "committed model did not activate".to_string())?;
    Ok((RoleResolver::from_plan(plan), model))
}

fn point_bootstrap(entries: &[PointMapEntry]) -> Vec<super::committed_model::BootstrapPoint> {
    entries
        .iter()
        .map(|entry| super::committed_model::BootstrapPoint {
            provider_point_id: entry.provider_point_id.clone(),
            semantic_point_id: entry.semantic_point_id.clone(),
            equipment_id: entry.equipment_id.clone(),
            role: entry.role.clone(),
            equip_type: entry.equip_type.clone(),
            unit: entry.unit.clone(),
            kind: entry.kind.clone(),
            provisional: entry.provisional,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn point_map_and_binding_set_are_not_two_truths() {
        let raw = r#"{
            "building_id": "site-a",
            "tenant_id": "tenant-a",
            "provider_instance_id": "nf-conn-a",
            "provider": "nf",
            "endpoint": "https://portal.example",
            "point_map": [{
                "provider_point_id": "uuid-sat",
                "equipment_id": "AHU_1",
                "role": "sat",
                "equip_type": "ahu"
            }],
            "binding_set_inline": "{\"schema\":\"ofdd_portal_committed_model_v1\"}"
        }"#;
        let err = load_sites_json(raw)
            .unwrap()
            .into_iter()
            .map(site_from_raw)
            .collect::<Result<Vec<_>, _>>()
            .unwrap_err();
        assert!(err.contains("one committed model"), "{err}");
    }

    #[test]
    fn binding_set_rejects_truncated_export() {
        let raw = r#"{
            "building_id": "site-a",
            "tenant_id": "tenant-a",
            "provider_instance_id": "nf-conn-a",
            "provider": "nf",
            "endpoint": "https://portal.example",
            "binding_set_inline": "{\"schema\":\"ofdd_portal_committed_model_v1\",\"tenant_id\":\"tenant-a\",\"site_id\":\"site-a\",\"provider_instance_id\":\"nf-conn-a\",\"truncated\":true,\"equipment\":[]}"
        }"#;
        let err = load_sites_json(raw)
            .unwrap()
            .into_iter()
            .map(site_from_raw)
            .collect::<Result<Vec<_>, _>>()
            .unwrap_err();
        assert!(err.contains("truncated"), "{err}");
    }

    #[test]
    fn env_ref_resolves() {
        std::env::set_var("OPENFDD_TEST_PROVIDER_SECRET", "sekret");
        assert_eq!(
            resolve_env_ref("env:OPENFDD_TEST_PROVIDER_SECRET").as_deref(),
            Some("sekret")
        );
    }
}
