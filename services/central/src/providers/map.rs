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
    #[serde(default)]
    pub unit: Option<String>,
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
    pub unit: Option<String>,
}

#[derive(Debug, Default, Clone)]
pub struct RoleResolver {
    by_provider_point_id: HashMap<String, ResolvedRole>,
}

impl RoleResolver {
    pub fn from_point_map(entries: &[PointMapEntry]) -> Result<Self, String> {
        let mut resolver = Self::default();
        for entry in entries {
            let key = entry.provider_point_id.trim();
            if key.is_empty() {
                continue;
            }
            resolver.insert_role(
                key,
                ResolvedRole {
                    equipment_id: entry.equipment_id.trim().to_string(),
                    role: entry.role.trim().to_string(),
                    equip_type: entry
                        .equip_type
                        .as_deref()
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                        .map(str::to_string),
                    unit: entry
                        .unit
                        .as_deref()
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                        .map(str::to_string),
                },
            )?;
        }
        Ok(resolver)
    }

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
                let incoming = ResolvedRole {
                    equipment_id: equip.equipment_id.trim().to_string(),
                    role: role.to_string(),
                    equip_type: None,
                    unit: None,
                };
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

    pub fn merge_binding_set_path(
        &mut self,
        path: &std::path::Path,
        expected_building: &str,
    ) -> Result<(), String> {
        let raw =
            std::fs::read_to_string(path).map_err(|_| "binding_set_unreadable".to_string())?;
        self.merge_binding_set_json(&raw, expected_building)
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
        attrs: raw.attrs.clone(),
    }
}

/// Map raw points in history-then-latest order. The first sample for a
/// `(provider_point_id, microsecond)` pair wins. Unmapped ids are dropped.
///
/// The hourly job calls [`normalize_mapped`] per accepted sample. This batch
/// helper is the offline contractor gate.
#[cfg(test)]
pub fn map_provider_samples(
    building_id: &str,
    provider_instance_id: &str,
    resolver: &RoleResolver,
    history: &[RawProviderPoint],
    latest: &[RawProviderPoint],
) -> Vec<NormalizedSample> {
    let mut samples = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for point in history.iter().chain(latest.iter()) {
        let Some(resolved) = resolver.resolve(&point.provider_point_id) else {
            continue;
        };
        let key = (point.provider_point_id.clone(), point.ts.timestamp_micros());
        if !seen.insert(key) {
            continue;
        }
        samples.push(normalize_mapped(
            building_id,
            provider_instance_id,
            point,
            resolved,
        ));
    }
    samples
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
            unit: None,
        }])
        .unwrap();
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
            unit: None,
        }])
        .unwrap();
        assert!(resolver.resolve("OA-T").is_none());
    }

    #[test]
    fn duplicate_role_and_wrong_building_fail() {
        let err = RoleResolver::from_point_map(&[
            PointMapEntry {
                provider_point_id: "a".into(),
                equipment_id: "AHU_1".into(),
                role: "sat".into(),
                equip_type: Some("ahu".into()),
                unit: None,
            },
            PointMapEntry {
                provider_point_id: "b".into(),
                equipment_id: "AHU_1".into(),
                role: "sat".into(),
                equip_type: None,
                unit: None,
            },
        ])
        .unwrap_err();
        assert_eq!(err, "duplicate_equipment_role");

        let mut resolver = RoleResolver::default();
        let mismatch = resolver.merge_binding_set_json(
            r#"{"building_id":"OTHER","equipment":[{"equipment_id":"AHU_1","points":[{"point_id":"u","canonical_role":"sat"}]}]}"#,
            "SITE",
        );
        assert_eq!(mismatch.unwrap_err(), "binding_building_mismatch");
    }
}
