//! Role resolution for vendor portal points.
//!
//! # SPARQL / identity law (product path)
//!
//! Equipment id and Haystack SQL **role** MUST come from either:
//!
//! 1. **Haystack RDF + inventory-approved bindings** — a `TypedBindingSet` (or
//!    equivalent) keyed by stable **`point_id`** → `{ equipment_id, canonical_role }`, or
//! 2. **Explicit config** — `provider_point_id` → `{ equipment_id, role }` in
//!    `OPENFDD_PROVIDER_SITES` `point_map`.
//!
//! **Forbidden:** substring, prefix, `contains`, `LIKE`, or grepping NF **display
//! names** (`name`, human labels) to invent roles. Display names are smoke / UX only.

use std::collections::HashMap;

use serde::Deserialize;

use super::types::NormalizedSample;

#[derive(Debug, Clone, Deserialize)]
pub struct PointMapEntry {
    pub provider_point_id: String,
    pub equipment_id: String,
    pub role: String,
    #[serde(default)]
    pub equip_type: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct BindingSetFile {
    #[serde(default)]
    building_id: Option<String>,
    #[serde(default)]
    equipment: Vec<BindingEquipment>,
}

#[derive(Debug, Clone, Deserialize)]
struct BindingEquipment {
    equipment_id: String,
    #[serde(default)]
    points: Vec<BindingPoint>,
}

#[derive(Debug, Clone, Deserialize)]
struct BindingPoint {
    point_id: String,
    #[serde(default)]
    canonical_role: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedRole {
    pub equipment_id: String,
    pub role: String,
    pub equip_type: Option<String>,
}

#[derive(Debug, Default, Clone)]
pub struct RoleResolver {
    by_provider_point_id: HashMap<String, ResolvedRole>,
}

impl RoleResolver {
    pub fn from_point_map(entries: &[PointMapEntry]) -> Self {
        let mut by_provider_point_id = HashMap::new();
        for entry in entries {
            let key = entry.provider_point_id.trim();
            if key.is_empty() {
                continue;
            }
            by_provider_point_id.insert(
                key.to_string(),
                ResolvedRole {
                    equipment_id: entry.equipment_id.clone(),
                    role: entry.role.clone(),
                    equip_type: entry.equip_type.clone(),
                },
            );
        }
        Self { by_provider_point_id }
    }

    pub fn merge_binding_set_json(&mut self, json: &str) -> Result<(), String> {
        let set: BindingSetFile =
            serde_json::from_str(json).map_err(|e| format!("binding set JSON: {e}"))?;
        for equip in set.equipment {
            for pt in equip.points {
                let Some(role) = pt
                    .canonical_role
                    .as_deref()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                else {
                    continue;
                };
                let pid = pt.point_id.trim();
                if pid.is_empty() {
                    continue;
                }
                self.by_provider_point_id.insert(
                    pid.to_string(),
                    ResolvedRole {
                        equipment_id: equip.equipment_id.clone(),
                        role: role.to_string(),
                        equip_type: None,
                    },
                );
            }
        }
        Ok(())
    }

    pub fn merge_binding_set_path(&mut self, path: &std::path::Path) -> Result<(), String> {
        let raw = std::fs::read_to_string(path)
            .map_err(|e| format!("read binding set {}: {e}", path.display()))?;
        self.merge_binding_set_json(&raw)
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

#[derive(Debug, Clone)]
pub struct RawProviderPoint {
    pub provider_point_id: String,
    #[allow(dead_code)]
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
    NormalizedSample {
        building_id: building_id.to_string(),
        equipment_id: resolved.equipment_id.clone(),
        provider_point_id: raw.provider_point_id.clone(),
        role: resolved.role.clone(),
        equip_type: resolved.equip_type.clone(),
        ts: raw.ts,
        val: raw.val,
        unit: raw.unit.clone(),
        attrs: raw.attrs.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn id_map_hits_explicit_config() {
        let resolver = RoleResolver::from_point_map(&[PointMapEntry {
            provider_point_id: "6639-uuid-oa-t".into(),
            equipment_id: "AHU_1".into(),
            role: "outside-air-temp".into(),
            equip_type: None,
        }]);
        let hit = resolver.resolve("6639-uuid-oa-t").unwrap();
        assert_eq!(hit.equipment_id, "AHU_1");
        assert_eq!(hit.role, "outside-air-temp");
    }

    #[test]
    fn name_only_must_not_resolve() {
        let resolver = RoleResolver::from_point_map(&[PointMapEntry {
            provider_point_id: "6639-uuid-oa-t".into(),
            equipment_id: "AHU_1".into(),
            role: "outside-air-temp".into(),
            equip_type: None,
        }]);
        assert!(resolver.resolve("OA-T").is_none());
    }
}
