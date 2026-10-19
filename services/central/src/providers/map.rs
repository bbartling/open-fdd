//! Role resolution for vendor portal points.
//!
//! # SPARQL / identity law (product path)
//!
//! Equipment id and Haystack SQL **role** MUST come from either:
//!
//! 1. **Committed model / SPARQL bindings** — typed rows with a semantic
//!    `point_id` distinct from the provider source id, or
//! 2. **Explicit config** — `provider_point_id` → `{ equipment_id, role }` in
//!    `OPENFDD_PROVIDER_SITES` `point_map`, compiled into that same model.
//!
//! **Forbidden:** substring, prefix, `contains`, `LIKE`, or grepping NF **display
//! names** (`name`, human labels) to invent roles. Display names are smoke / UX only.

use std::collections::BTreeMap;

use serde::Deserialize;

use super::committed_model::{BootstrapPoint, CommittedModel, IngestPlan, ModelScope};
use super::types::NormalizedSample;

#[derive(Debug, Clone, Deserialize)]
pub struct PointMapEntry {
    pub provider_point_id: String,
    #[serde(default)]
    pub semantic_point_id: Option<String>,
    pub equipment_id: String,
    pub role: String,
    #[serde(default)]
    pub equip_type: Option<String>,
    #[serde(default)]
    pub unit: Option<String>,
    #[serde(default)]
    pub kind: Option<String>,
    #[serde(default)]
    pub provisional: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedRole {
    pub equipment_id: String,
    pub role: String,
    pub equip_type: Option<String>,
    pub semantic_point_id: String,
    pub unit: Option<String>,
    pub canonical_unit: Option<String>,
    pub kind: Option<String>,
    pub quantity: Option<String>,
    pub provider_instance_id: String,
    pub model_revision: String,
}

#[derive(Debug, Default, Clone)]
pub struct RoleResolver {
    by_provider_point_id: BTreeMap<String, ResolvedRole>,
    model_revision: Option<String>,
}

impl RoleResolver {
    pub fn from_plan(plan: &IngestPlan) -> Self {
        if plan.schema != super::committed_model::PLAN_SCHEMA {
            return Self::default();
        }
        let mut by_provider_point_id = BTreeMap::new();
        for group in &plan.groups {
            for point in &group.points {
                by_provider_point_id.insert(
                    point.source_point_id.clone(),
                    ResolvedRole {
                        equipment_id: group.equipment_id.clone(),
                        role: point.canonical_role.clone(),
                        equip_type: Some(group.equip_type.clone()),
                        semantic_point_id: point.semantic_point_id.clone(),
                        unit: point.source_unit.clone(),
                        canonical_unit: point.canonical_unit.clone(),
                        kind: point.kind.clone(),
                        quantity: point.quantity.clone(),
                        provider_instance_id: group.provider_instance_id.clone(),
                        model_revision: plan.revision_id.clone(),
                    },
                );
            }
        }
        Self {
            by_provider_point_id,
            model_revision: Some(plan.revision_id.clone()),
        }
    }

    pub fn model_revision(&self) -> Option<&str> {
        self.model_revision.as_deref()
    }

    pub fn from_point_map(scope: &ModelScope, entries: &[PointMapEntry]) -> Result<Self, String> {
        let model = super::committed_model::model_from_point_map(scope, &bootstrap(entries))?;
        let mut store = super::committed_model::CommittedModelStore::default();
        store.try_activate(None, &model)?;
        let plan = store
            .active_plan(&scope.tenant_id, &scope.site_id)
            .ok_or_else(|| "committed model did not activate".to_string())?;
        Ok(Self::from_plan(plan))
    }

    pub fn from_committed_json(
        json: &str,
        scope: &ModelScope,
    ) -> Result<(Self, CommittedModel), String> {
        let model = super::committed_model::model_from_json(json, scope)?;
        let mut store = super::committed_model::CommittedModelStore::default();
        store.try_activate(None, &model)?;
        let plan = store
            .active_plan(&scope.tenant_id, &scope.site_id)
            .ok_or_else(|| "committed model did not activate".to_string())?;
        Ok((Self::from_plan(plan), model))
    }

    pub fn from_committed_path(
        path: &std::path::Path,
        scope: &ModelScope,
    ) -> Result<(Self, CommittedModel), String> {
        let raw = std::fs::read_to_string(path)
            .map_err(|e| format!("read committed model {}: {e}", path.display()))?;
        Self::from_committed_json(&raw, scope)
    }

    /// Resolve by stable `provider_point_id` only — never by display name.
    pub fn resolve(&self, provider_point_id: &str) -> Option<&ResolvedRole> {
        self.by_provider_point_id.get(provider_point_id.trim())
    }

    pub fn mapped_count(&self) -> usize {
        self.by_provider_point_id.len()
    }

    pub fn provider_point_ids(&self) -> Vec<String> {
        self.by_provider_point_id.keys().cloned().collect()
    }
}

fn bootstrap(entries: &[PointMapEntry]) -> Vec<BootstrapPoint> {
    entries
        .iter()
        .map(|entry| BootstrapPoint {
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

#[derive(Debug, Clone)]
pub struct RawProviderPoint {
    pub provider_point_id: String,
    pub display_name: Option<String>,
    pub ts: chrono::DateTime<chrono::Utc>,
    pub val: f64,
    pub unit: Option<String>,
    pub attrs: serde_json::Map<String, serde_json::Value>,
}

pub fn normalize_mapped(
    building_id: &str,
    raw: &RawProviderPoint,
    resolved: &ResolvedRole,
) -> NormalizedSample {
    let mut attrs = raw.attrs.clone();
    if let Some(label) = raw.display_name.as_deref() {
        // Label only. Role resolution already happened by provider_point_id.
        insert_attr(&mut attrs, "display_name", label);
    }
    insert_attr(&mut attrs, "semantic_point_id", &resolved.semantic_point_id);
    insert_attr(
        &mut attrs,
        "provider_instance_id",
        &resolved.provider_instance_id,
    );
    insert_attr(&mut attrs, "model_revision", &resolved.model_revision);
    if let Some(kind) = resolved.kind.as_deref() {
        insert_attr(&mut attrs, "kind", kind);
    }
    if let Some(quantity) = resolved.quantity.as_deref() {
        insert_attr(&mut attrs, "quantity", quantity);
    }
    if let Some(unit) = resolved.canonical_unit.as_deref() {
        insert_attr(&mut attrs, "canonical_unit", unit);
    }
    NormalizedSample {
        building_id: building_id.to_string(),
        equipment_id: resolved.equipment_id.clone(),
        provider_point_id: raw.provider_point_id.clone(),
        role: resolved.role.clone(),
        equip_type: resolved.equip_type.clone(),
        ts: raw.ts,
        val: raw.val,
        unit: raw.unit.clone().or_else(|| resolved.unit.clone()),
        attrs,
    }
}

fn insert_attr(attrs: &mut serde_json::Map<String, serde_json::Value>, key: &str, value: &str) {
    if value.is_empty() {
        return;
    }
    attrs.insert(
        key.to_string(),
        serde_json::Value::String(value.to_string()),
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scope() -> ModelScope {
        ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        }
    }

    fn entry(id: &str, role: &str) -> PointMapEntry {
        PointMapEntry {
            provider_point_id: id.into(),
            semantic_point_id: None,
            equipment_id: "AHU_1".into(),
            role: role.into(),
            equip_type: Some("ahu".into()),
            unit: None,
            kind: None,
            provisional: false,
        }
    }

    #[test]
    fn id_map_hits_explicit_config() {
        let resolver =
            RoleResolver::from_point_map(&scope(), &[entry("uuid-oa-t", "outside-air-temp")])
                .unwrap();
        let hit = resolver.resolve("uuid-oa-t").unwrap();
        assert_eq!(hit.equipment_id, "AHU_1");
        assert_eq!(hit.role, "outside-air-temp");
        assert_ne!(hit.semantic_point_id, hit.role);
        assert!(resolver.resolve("OA-T").is_none());
    }

    #[test]
    fn excluded_binding_is_not_scheduled() {
        let json = r#"{
            "schema": "ofdd_portal_committed_model_v1",
            "tenant_id": "tenant-a",
            "site_id": "site-a",
            "provider_instance_id": "nf-conn-a",
            "truncated": false,
            "equipment": [{
                "equipment_id": "AHU_1",
                "equip_type": "ahu",
                "points": [{
                    "point_id": "urn:openfdd:point:site-a:AHU_1:sat",
                    "provider_point_id": "uuid-sat",
                    "canonical_role": "sat",
                    "selection_status": "excluded",
                    "fdd_ready": false,
                    "display_name": "SAT"
                }]
            }]
        }"#;
        let (resolver, _) = RoleResolver::from_committed_json(json, &scope()).unwrap();
        assert!(resolver.resolve("uuid-sat").is_none());
        assert!(resolver.resolve("SAT").is_none());
        assert_eq!(resolver.mapped_count(), 0);
    }
}
