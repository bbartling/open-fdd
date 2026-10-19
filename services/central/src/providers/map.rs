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

#[cfg(test)]
#[derive(Debug, Clone, Deserialize)]
struct BindingSetFile {
    #[serde(default)]
    building_id: Option<String>,
    #[serde(default)]
    equipment: Vec<BindingEquipment>,
}

#[cfg(test)]
#[derive(Debug, Clone, Deserialize)]
struct BindingEquipment {
    equipment_id: String,
    #[serde(default)]
    points: Vec<BindingPoint>,
}

#[cfg(test)]
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
    pub unit: Option<String>,
    pub semantic_point_id: String,
    pub canonical_unit: Option<String>,
    pub kind: Option<String>,
    pub quantity: Option<String>,
    pub provider_instance_id: String,
    pub model_revision: String,
}

impl ResolvedRole {
    /// Direct binding used by hourly normalization before model attrs are known.
    pub fn binding(
        equipment_id: impl Into<String>,
        role: impl Into<String>,
        equip_type: Option<String>,
        unit: Option<String>,
    ) -> Self {
        Self {
            equipment_id: equipment_id.into(),
            role: role.into(),
            equip_type,
            unit,
            semantic_point_id: String::new(),
            canonical_unit: None,
            kind: None,
            quantity: None,
            provider_instance_id: String::new(),
            model_revision: String::new(),
        }
    }
}

#[derive(Debug, Default, Clone)]
pub struct RoleResolver {
    by_provider_point_id: HashMap<String, ResolvedRole>,
    model_revision: Option<String>,
}

impl RoleResolver {
    pub fn model_revision(&self) -> Option<&str> {
        self.model_revision.as_deref()
    }

    /// Compile an explicit point map through the committed model, then schedule
    /// only fdd-ready points from the active plan.
    pub fn compile_point_map(
        scope: &super::committed_model::ModelScope,
        entries: &[PointMapEntry],
    ) -> Result<(Self, super::committed_model::CommittedModel), String> {
        let model = super::committed_model::model_from_point_map(scope, &bootstrap(entries))?;
        Self::activate_model(model)
    }

    pub fn from_plan(plan: &super::committed_model::IngestPlan) -> Self {
        if plan.schema != super::committed_model::PLAN_SCHEMA {
            return Self::default();
        }
        let mut by_provider_point_id = HashMap::new();
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

    pub fn from_committed_json(
        json: &str,
        scope: &super::committed_model::ModelScope,
    ) -> Result<(Self, super::committed_model::CommittedModel), String> {
        let model = super::committed_model::model_from_json(json, scope)?;
        Self::activate_model(model)
    }

    fn activate_model(
        model: super::committed_model::CommittedModel,
    ) -> Result<(Self, super::committed_model::CommittedModel), String> {
        let mut store = super::committed_model::CommittedModelStore::default();
        store.try_activate(None, &model)?;
        let plan = store
            .active_plan(&model.tenant_id, &model.site_id)
            .ok_or_else(|| "model_not_activated".to_string())?;
        Ok((Self::from_plan(plan), model))
    }

    #[cfg(test)]
    pub fn from_point_map(entries: &[PointMapEntry]) -> Result<Self, String> {
        let mut resolver = Self::default();
        for entry in entries {
            let key = entry.provider_point_id.trim();
            if key.is_empty() {
                continue;
            }
            resolver.insert_role(
                key,
                ResolvedRole::binding(
                    entry.equipment_id.trim(),
                    entry.role.trim(),
                    entry
                        .equip_type
                        .as_deref()
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                        .map(str::to_string),
                    entry
                        .unit
                        .as_deref()
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                        .map(str::to_string),
                ),
            )?;
        }
        Ok(resolver)
    }

    #[cfg(test)]
    fn insert_role(&mut self, provider_point_id: &str, role: ResolvedRole) -> Result<(), String> {
        if role.equipment_id.is_empty() || role.role.is_empty() {
            return Err("invalid_binding".into());
        }
        if let Some(existing) = self.by_provider_point_id.get(provider_point_id) {
            if existing.equipment_id != role.equipment_id || existing.role != role.role {
                return Err("duplicate_provider_point".into());
            }
            return Ok(());
        }
        let collision = self.by_provider_point_id.values().any(|existing| {
            existing.equipment_id == role.equipment_id && existing.role == role.role
        });
        if collision {
            return Err("duplicate_equipment_role".into());
        }
        self.by_provider_point_id
            .insert(provider_point_id.to_string(), role);
        Ok(())
    }

    #[cfg(test)]
    pub fn merge_binding_set_json(
        &mut self,
        json: &str,
        expected_building: &str,
    ) -> Result<(), String> {
        let set: BindingSetFile =
            serde_json::from_str(json).map_err(|_| "binding_set_json".to_string())?;
        let Some(building) = set
            .building_id
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        else {
            return Err("binding_scope_required".into());
        };
        if building != expected_building.trim() {
            return Err("binding_building_mismatch".into());
        }
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
                let incoming = ResolvedRole::binding(equip.equipment_id.trim(), role, None, None);
                if let Some(existing) = self.by_provider_point_id.get(pid) {
                    if existing.equipment_id != incoming.equipment_id
                        || existing.role != incoming.role
                    {
                        return Err("duplicate_provider_point".into());
                    }
                    continue;
                }
                self.insert_role(pid, incoming)?;
            }
        }
        Ok(())
    }

    /// Resolve by stable `provider_point_id` only — never by display name.
    pub fn resolve(&self, provider_point_id: &str) -> Option<&ResolvedRole> {
        self.by_provider_point_id.get(provider_point_id.trim())
    }

    pub fn mapped_count(&self) -> usize {
        self.by_provider_point_id.len()
    }

    #[expect(
        dead_code,
        reason = "hourly jobs group with devices(); adapters can still list source ids"
    )]
    pub fn provider_point_ids(&self) -> Vec<String> {
        self.by_provider_point_id.keys().cloned().collect()
    }

    /// Group mapped points by equipment id. Hourly jobs run per device.
    pub fn devices(&self) -> Vec<DevicePoints> {
        let mut ids: Vec<String> = self.by_provider_point_id.keys().cloned().collect();
        ids.sort();
        let mut grouped: std::collections::BTreeMap<String, Vec<MappedPoint>> =
            std::collections::BTreeMap::new();
        for point_id in ids {
            let Some(resolved) = self.resolve(&point_id) else {
                continue;
            };
            let equipment_id = resolved.equipment_id.clone();
            let point = MappedPoint {
                provider_point_id: point_id,
                role: resolved.role.clone(),
                equip_type: resolved.equip_type.clone(),
            };
            grouped.entry(equipment_id).or_default().push(point);
        }
        grouped
            .into_iter()
            .map(|(device_id, points)| DevicePoints { device_id, points })
            .collect()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MappedPoint {
    pub provider_point_id: String,
    pub role: String,
    pub equip_type: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DevicePoints {
    pub device_id: String,
    pub points: Vec<MappedPoint>,
}

/// One source series from a history read. An empty `samples` list means the
/// source returned that series with no values. A missing series is different.
#[derive(Debug, Clone, PartialEq)]
pub struct HistorySeries {
    pub provider_point_id: String,
    pub samples: Vec<RawProviderPoint>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct RawProviderPoint {
    pub provider_point_id: String,
    /// Carried for UX. Role resolution must not read this field.
    pub display_name: Option<String>,
    pub ts: chrono::DateTime<chrono::Utc>,
    pub val: f64,
    pub unit: Option<String>,
    pub source_quality: Option<String>,
    pub attrs: serde_json::Map<String, serde_json::Value>,
}

pub fn normalize_mapped(
    building_id: &str,
    provider_instance_id: &str,
    raw: &RawProviderPoint,
    resolved: &ResolvedRole,
) -> NormalizedSample {
    let mut attrs = raw.attrs.clone();
    if let Some(label) = raw.display_name.as_deref() {
        insert_attr(&mut attrs, "display_name", label);
    }
    insert_attr(&mut attrs, "semantic_point_id", &resolved.semantic_point_id);
    let model_instance = if resolved.provider_instance_id.is_empty() {
        provider_instance_id
    } else {
        resolved.provider_instance_id.as_str()
    };
    insert_attr(&mut attrs, "provider_instance_id", model_instance);
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
        provider_instance_id: provider_instance_id.to_string(),
        equipment_id: resolved.equipment_id.clone(),
        provider_point_id: raw.provider_point_id.clone(),
        role: resolved.role.clone(),
        equip_type: resolved.equip_type.clone(),
        ts: raw.ts,
        val: raw.val,
        unit: raw.unit.clone().or_else(|| resolved.unit.clone()),
        source_quality: raw.source_quality.clone(),
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

fn bootstrap(entries: &[PointMapEntry]) -> Vec<super::committed_model::BootstrapPoint> {
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

    fn scope() -> super::super::committed_model::ModelScope {
        super::super::committed_model::ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        }
    }

    #[test]
    fn id_map_hits_explicit_config() {
        let resolver =
            RoleResolver::from_point_map(&[entry("6639-uuid-oa-t", "outside-air-temp")]).unwrap();
        let hit = resolver.resolve("6639-uuid-oa-t").unwrap();
        assert_eq!(hit.equipment_id, "AHU_1");
        assert_eq!(hit.role, "outside-air-temp");
    }

    #[test]
    fn name_only_must_not_resolve() {
        let resolver =
            RoleResolver::from_point_map(&[entry("6639-uuid-oa-t", "outside-air-temp")]).unwrap();
        assert!(resolver.resolve("OA-T").is_none());
    }

    #[test]
    fn duplicate_role_and_wrong_building_fail() {
        let err =
            RoleResolver::from_point_map(&[entry("a", "sat"), entry("b", "sat")]).unwrap_err();
        assert_eq!(err, "duplicate_equipment_role");

        let mut resolver = RoleResolver::default();
        let mismatch = resolver.merge_binding_set_json(
            r#"{"building_id":"OTHER","equipment":[{"equipment_id":"AHU_1","points":[{"point_id":"u","canonical_role":"sat"}]}]}"#,
            "SITE",
        );
        assert_eq!(mismatch.unwrap_err(), "binding_building_mismatch");
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
