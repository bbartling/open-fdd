//! Source-neutral committed model (Wave-NF N3).
//!
//! One revision is the authority for tenant → site → equipment → point.
//! Validated `point_map` config and typed SPARQL rows are bootstrap inputs.
//! They compile once into a deterministic ingest plan. A failed revision
//! leaves the last valid plan active.

use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use open_fdd_edge_prototype::csv_ingest::model_overlay::{
    effective_point_quantity, effective_point_unit, effective_primary_reference,
    load_engineer_point_overlay,
};
use open_fdd_edge_prototype::csv_ingest::portal_ingest_sparql::{
    validate_binding_rows, validate_slug, validate_unit, IngestBindingRow,
};

pub const SCHEMA: &str = "ofdd_portal_committed_model_v1";
pub const PLAN_SCHEMA: &str = "ofdd_portal_ingest_plan_v1";

const FORBIDDEN_KEYS: &[&str] = &[
    "url",
    "request_url",
    "requesturl",
    "http_method",
    "httpmethod",
    "http_verb",
    "httpverb",
    "verb",
    "headers",
    "header",
    "authorization",
    "credential",
    "credentials",
    "secret",
    "password",
    "client_secret",
    "access_token",
    "sql",
    "script",
    "javascript",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModelScope {
    pub tenant_id: String,
    pub site_id: String,
    pub provider_instance_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootstrapPoint {
    pub provider_point_id: String,
    pub semantic_point_id: Option<String>,
    pub equipment_id: String,
    pub role: String,
    pub equip_type: Option<String>,
    pub unit: Option<String>,
    pub kind: Option<String>,
    pub provisional: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct CommittedModel {
    pub schema: String,
    pub tenant_id: String,
    #[serde(alias = "building_id")]
    pub site_id: String,
    pub provider_instance_id: String,
    pub truncated: bool,
    #[serde(default)]
    pub equipment: Vec<CommittedEquipment>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct CommittedEquipment {
    pub equipment_id: String,
    pub equip_type: String,
    #[serde(default)]
    pub points: Vec<CommittedPoint>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct CommittedPoint {
    pub point_id: String,
    pub provider_point_id: String,
    #[serde(default)]
    pub canonical_role: Option<String>,
    pub selection_status: String,
    pub fdd_ready: bool,
    #[serde(default)]
    pub unit: Option<String>,
    #[serde(default)]
    pub canonical_unit: Option<String>,
    #[serde(default)]
    pub kind: Option<String>,
    #[serde(default)]
    pub quantity: Option<String>,
    #[serde(default)]
    pub provisional: bool,
    /// UX label only. Never a role source.
    #[serde(default)]
    pub display_name: Option<String>,
    /// `interval` or `cov`. Absent means the queue must not invent a cadence.
    #[serde(default)]
    pub history_mode: Option<String>,
    #[serde(default)]
    pub cadence_secs: Option<u64>,
    #[serde(default)]
    pub heartbeat_secs: Option<u64>,
    /// Engineer-declared primary reference for this role (for example local OAT).
    #[serde(default)]
    pub primary_reference: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlannedPoint {
    pub semantic_point_id: String,
    pub source_point_id: String,
    pub canonical_role: String,
    pub kind: Option<String>,
    pub source_unit: Option<String>,
    pub canonical_unit: Option<String>,
    pub quantity: Option<String>,
    pub history_mode: Option<String>,
    pub cadence_secs: Option<u64>,
    pub heartbeat_secs: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestDeviceGroup {
    pub provider_instance_id: String,
    pub equipment_id: String,
    pub equip_type: String,
    pub points: Vec<PlannedPoint>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WithheldPoint {
    pub provider_instance_id: String,
    pub equipment_id: String,
    pub semantic_point_id: String,
    pub source_point_id: String,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestPlan {
    pub schema: String,
    pub revision_id: String,
    pub tenant_id: String,
    pub site_id: String,
    pub groups: Vec<IngestDeviceGroup>,
    pub withheld: Vec<WithheldPoint>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationReport {
    pub revision_id: String,
    pub previous_revision_id: Option<String>,
    pub added_source_ids: Vec<String>,
    pub removed_source_ids: Vec<String>,
    pub remapped_source_ids: Vec<String>,
    pub scheduled_points: usize,
    pub withheld_points: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ActiveRevision {
    revision_id: String,
    plan: IngestPlan,
}

#[derive(Debug, Default)]
pub struct CommittedModelStore {
    active: BTreeMap<(String, String), ActiveRevision>,
    plans: BTreeMap<String, IngestPlan>,
    compile_count: u32,
}

impl CommittedModelStore {
    pub fn compile_count(&self) -> u32 {
        self.compile_count
    }

    pub fn active_revision(&self, tenant_id: &str, site_id: &str) -> Option<&str> {
        self.active
            .get(&(tenant_id.to_string(), site_id.to_string()))
            .map(|active| active.revision_id.as_str())
    }

    pub fn active_plan(&self, tenant_id: &str, site_id: &str) -> Option<&IngestPlan> {
        self.active
            .get(&(tenant_id.to_string(), site_id.to_string()))
            .map(|active| &active.plan)
    }
}

pub fn model_from_json(raw: &str, scope: &ModelScope) -> Result<CommittedModel, String> {
    let value: Value =
        serde_json::from_str(raw).map_err(|e| format!("committed model JSON: {e}"))?;
    reject_forbidden_keys(&value, "model")?;
    let model: CommittedModel =
        serde_json::from_value(value).map_err(|e| format!("committed model JSON: {e}"))?;
    if model.schema != SCHEMA {
        return Err(format!(
            "committed model schema must be {SCHEMA}, got {}",
            model.schema
        ));
    }
    ensure_scope(&model, scope)?;
    validate_model(&model)?;
    Ok(model)
}

/// Merge engineer unit / quantity / primary-reference overlay onto a committed model.
pub fn apply_engineer_point_overlays(
    building_root: &Path,
    building_id: &str,
    model: &mut CommittedModel,
) -> Result<(), String> {
    let store = load_engineer_point_overlay(building_root)?;
    if store.points.is_empty() {
        return Ok(());
    }
    if !store.building_id.is_empty() && store.building_id != building_id {
        return Err("engineer overlay building_id mismatch".into());
    }
    for equip in &mut model.equipment {
        for point in &mut equip.points {
            let portal_unit = point.unit.clone();
            let entry = store.points.get(&point.provider_point_id);
            point.unit = effective_point_unit(portal_unit.as_deref(), entry);
            if let Some(q) = effective_point_quantity(entry) {
                point.quantity = Some(q);
            }
            point.primary_reference = effective_primary_reference(entry);
            if let Some(unit) = point.unit.as_deref() {
                validate_unit(unit)?;
            }
            if let Some(q) = point.quantity.as_deref() {
                validate_slug("quantity", q, 64)?;
            }
        }
    }
    Ok(())
}

pub fn model_from_point_map(
    scope: &ModelScope,
    entries: &[BootstrapPoint],
) -> Result<CommittedModel, String> {
    validate_slug("tenant_id", &scope.tenant_id, 128)?;
    validate_slug("site_id", &scope.site_id, 128)?;
    validate_slug("provider_instance_id", &scope.provider_instance_id, 128)?;
    let mut by_equip: BTreeMap<String, CommittedEquipment> = BTreeMap::new();
    for entry in entries {
        let equip_type = entry
            .equip_type
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| format!("empty type for {}", entry.equipment_id))?;
        let role = entry.role.trim();
        if role.is_empty() {
            return Err("approved binding requires canonical_role".into());
        }
        let semantic = entry.semantic_point_id.clone().unwrap_or_else(|| {
            format!(
                "urn:openfdd:point:{}:{}:{role}",
                scope.site_id, entry.equipment_id
            )
        });
        let fdd_ready = !entry.provisional;
        let point = CommittedPoint {
            point_id: semantic,
            provider_point_id: entry.provider_point_id.trim().to_string(),
            canonical_role: Some(role.to_string()),
            selection_status: "approved".into(),
            fdd_ready,
            unit: entry.unit.clone(),
            canonical_unit: None,
            kind: entry.kind.clone(),
            quantity: None,
            provisional: entry.provisional,
            display_name: None,
            history_mode: None,
            cadence_secs: None,
            heartbeat_secs: None,
            primary_reference: false,
        };
        let equip = by_equip
            .entry(entry.equipment_id.trim().to_string())
            .or_insert_with(|| CommittedEquipment {
                equipment_id: entry.equipment_id.trim().to_string(),
                equip_type: equip_type.to_string(),
                points: Vec::new(),
            });
        if equip.equip_type != equip_type {
            return Err(format!("conflicting equip type on {}", entry.equipment_id));
        }
        equip.points.push(point);
    }
    let model = CommittedModel {
        schema: SCHEMA.to_string(),
        tenant_id: scope.tenant_id.clone(),
        site_id: scope.site_id.clone(),
        provider_instance_id: scope.provider_instance_id.clone(),
        truncated: false,
        equipment: by_equip.into_values().collect(),
    };
    validate_model(&model)?;
    Ok(model)
}

pub fn model_from_sparql_rows(
    scope: &ModelScope,
    rows: &[IngestBindingRow],
) -> Result<CommittedModel, String> {
    validate_binding_rows(rows)?;
    let mut by_equip: BTreeMap<String, CommittedEquipment> = BTreeMap::new();
    for row in rows {
        if row.tenant_id != scope.tenant_id || row.site_id != scope.site_id {
            return Err(format!("wrong-site binding {}", row.site_id));
        }
        if row.provider_instance_id != scope.provider_instance_id {
            return Err(format!(
                "wrong-provider binding {}",
                row.provider_instance_id
            ));
        }
        let fdd_ready = row.selection_status == "approved" && !row.provisional;
        let point = CommittedPoint {
            point_id: row.semantic_point_id.clone(),
            provider_point_id: row.source_point_id.clone(),
            canonical_role: Some(row.canonical_role.clone()),
            selection_status: row.selection_status.clone(),
            fdd_ready,
            unit: row.source_unit.clone(),
            canonical_unit: row.canonical_unit.clone(),
            kind: row.kind.clone(),
            quantity: row.quantity.clone(),
            provisional: row.provisional,
            display_name: None,
            history_mode: row.history_mode.clone(),
            cadence_secs: row.cadence_secs,
            heartbeat_secs: row.heartbeat_secs,
            primary_reference: false,
        };
        let equip =
            by_equip
                .entry(row.equipment_id.clone())
                .or_insert_with(|| CommittedEquipment {
                    equipment_id: row.equipment_id.clone(),
                    equip_type: row.equip_type.clone(),
                    points: Vec::new(),
                });
        if equip.equip_type != row.equip_type {
            return Err(format!("conflicting equip type on {}", row.equipment_id));
        }
        equip.points.push(point);
    }
    let model = CommittedModel {
        schema: SCHEMA.to_string(),
        tenant_id: scope.tenant_id.clone(),
        site_id: scope.site_id.clone(),
        provider_instance_id: scope.provider_instance_id.clone(),
        truncated: false,
        equipment: by_equip.into_values().collect(),
    };
    validate_model(&model)?;
    Ok(model)
}

pub fn validate_model(model: &CommittedModel) -> Result<(), String> {
    if model.schema != SCHEMA {
        return Err(format!("committed model schema must be {SCHEMA}"));
    }
    if model.truncated {
        return Err("truncated model export".into());
    }
    validate_slug("tenant_id", &model.tenant_id, 128)?;
    validate_slug("site_id", &model.site_id, 128)?;
    validate_slug("provider_instance_id", &model.provider_instance_id, 128)?;
    let mut rows = Vec::new();
    for equip in &model.equipment {
        validate_slug("equipment_id", &equip.equipment_id, 128)?;
        if equip.equip_type.trim().is_empty() {
            return Err(format!("empty type for {}", equip.equipment_id));
        }
        validate_slug("equip_type", &equip.equip_type, 64)?;
        for point in &equip.points {
            let selection = point.selection_status.trim();
            if !matches!(
                selection,
                "approved" | "unresolved" | "ambiguous" | "excluded" | "disabled"
            ) {
                return Err(format!("malformed selection {selection}"));
            }
            let role = point
                .canonical_role
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty());
            if selection == "approved" && role.is_none() {
                return Err("approved binding requires canonical_role".into());
            }
            if let Some(role) = role {
                validate_slug("canonical_role", role, 128)?;
            }
            let derived = selection == "approved" && !point.provisional && role.is_some();
            if point.fdd_ready != derived {
                return Err(format!(
                    "fdd_ready does not match selection for {}",
                    point.point_id
                ));
            }
            if let Some(unit) = point.unit.as_deref() {
                validate_unit(unit)?;
            }
            if let Some(unit) = point.canonical_unit.as_deref() {
                validate_unit(unit)?;
            }
            match point.history_mode.as_deref() {
                None => {}
                Some("interval") => match point.cadence_secs {
                    Some(secs) if (1..=86_400).contains(&secs) => {}
                    _ => {
                        return Err(format!(
                            "interval history requires cadence_secs for {}",
                            point.point_id
                        ))
                    }
                },
                Some("cov") => {
                    if let Some(secs) = point.heartbeat_secs {
                        if secs == 0 || secs > 86_400 * 7 {
                            return Err(format!(
                                "cov heartbeat_secs is out of range for {}",
                                point.point_id
                            ));
                        }
                    }
                }
                Some(mode) => return Err(format!("history_mode {mode} is not interval or cov")),
            }
            rows.push(IngestBindingRow {
                tenant_id: model.tenant_id.clone(),
                site_id: model.site_id.clone(),
                provider_instance_id: model.provider_instance_id.clone(),
                equipment_id: equip.equipment_id.clone(),
                equip_type: equip.equip_type.clone(),
                semantic_point_id: point.point_id.clone(),
                source_point_id: point.provider_point_id.clone(),
                canonical_role: role.unwrap_or("unset").to_string(),
                selection_status: selection.to_string(),
                source_unit: point.unit.clone(),
                canonical_unit: point.canonical_unit.clone(),
                kind: point.kind.clone(),
                provisional: point.provisional,
                quantity: point.quantity.clone(),
                history_mode: point.history_mode.clone(),
                cadence_secs: point.cadence_secs,
                heartbeat_secs: point.heartbeat_secs,
            });
        }
    }
    validate_binding_rows(&rows)
}

fn ensure_scope(model: &CommittedModel, scope: &ModelScope) -> Result<(), String> {
    if model.tenant_id != scope.tenant_id {
        return Err(format!(
            "wrong-tenant binding {} for scope {}",
            model.tenant_id, scope.tenant_id
        ));
    }
    if model.site_id != scope.site_id {
        return Err(format!(
            "wrong-site binding {} for scope {}",
            model.site_id, scope.site_id
        ));
    }
    if model.provider_instance_id != scope.provider_instance_id {
        return Err(format!(
            "wrong-provider binding {} for scope {}",
            model.provider_instance_id, scope.provider_instance_id
        ));
    }
    Ok(())
}

fn revision_id(model: &CommittedModel) -> Result<String, String> {
    let mut equipment = Vec::new();
    let mut equips = model.equipment.clone();
    equips.sort_by(|a, b| a.equipment_id.cmp(&b.equipment_id));
    for equip in equips {
        let mut points = equip.points;
        points.sort_by(|a, b| a.point_id.cmp(&b.point_id));
        let points: Vec<_> = points
            .into_iter()
            .map(|point| {
                let mut body = json!({
                    "point_id": point.point_id,
                    "provider_point_id": point.provider_point_id,
                    "canonical_role": point.canonical_role,
                    "selection_status": point.selection_status,
                    "fdd_ready": point.fdd_ready,
                    "unit": point.unit,
                    "canonical_unit": point.canonical_unit,
                    "kind": point.kind,
                    "quantity": point.quantity,
                    "provisional": point.provisional,
                    "primary_reference": point.primary_reference,
                });
                if let Some(mode) = point.history_mode.clone() {
                    body["history_mode"] = json!(mode);
                }
                if let Some(secs) = point.cadence_secs {
                    body["cadence_secs"] = json!(secs);
                }
                if let Some(secs) = point.heartbeat_secs {
                    body["heartbeat_secs"] = json!(secs);
                }
                body
            })
            .collect();
        equipment.push(json!({
            "equipment_id": equip.equipment_id,
            "equip_type": equip.equip_type,
            "points": points,
        }));
    }
    let body = json!({
        "schema": model.schema,
        "tenant_id": model.tenant_id,
        "site_id": model.site_id,
        "provider_instance_id": model.provider_instance_id,
        "truncated": model.truncated,
        "equipment": equipment,
    });
    let bytes = serde_json::to_vec(&body).map_err(|e| format!("revision hash: {e}"))?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn build_plan(model: &CommittedModel, revision_id: &str) -> Result<IngestPlan, String> {
    validate_model(model)?;
    let mut groups: BTreeMap<(String, String), IngestDeviceGroup> = BTreeMap::new();
    let mut withheld = Vec::new();
    for equip in &model.equipment {
        for point in &equip.points {
            if point.fdd_ready {
                let key = (
                    model.provider_instance_id.clone(),
                    equip.equipment_id.clone(),
                );
                let group = groups.entry(key).or_insert_with(|| IngestDeviceGroup {
                    provider_instance_id: model.provider_instance_id.clone(),
                    equipment_id: equip.equipment_id.clone(),
                    equip_type: equip.equip_type.clone(),
                    points: Vec::new(),
                });
                group.points.push(PlannedPoint {
                    semantic_point_id: point.point_id.clone(),
                    source_point_id: point.provider_point_id.clone(),
                    canonical_role: point.canonical_role.clone().unwrap_or_default(),
                    kind: point.kind.clone(),
                    source_unit: point.unit.clone(),
                    canonical_unit: point.canonical_unit.clone(),
                    quantity: point.quantity.clone(),
                    history_mode: point.history_mode.clone(),
                    cadence_secs: point.cadence_secs,
                    heartbeat_secs: point.heartbeat_secs,
                });
            } else {
                withheld.push(WithheldPoint {
                    provider_instance_id: model.provider_instance_id.clone(),
                    equipment_id: equip.equipment_id.clone(),
                    semantic_point_id: point.point_id.clone(),
                    source_point_id: point.provider_point_id.clone(),
                    reason: if point.provisional {
                        "provisional".into()
                    } else {
                        point.selection_status.clone()
                    },
                });
            }
        }
    }
    let mut groups: Vec<_> = groups.into_values().collect();
    for group in &mut groups {
        group
            .points
            .sort_by(|a, b| a.semantic_point_id.cmp(&b.semantic_point_id));
    }
    groups.sort_by(|a, b| {
        (&a.provider_instance_id, &a.equipment_id).cmp(&(&b.provider_instance_id, &b.equipment_id))
    });
    withheld.sort_by(|a, b| a.semantic_point_id.cmp(&b.semantic_point_id));
    Ok(IngestPlan {
        schema: PLAN_SCHEMA.to_string(),
        revision_id: revision_id.to_string(),
        tenant_id: model.tenant_id.clone(),
        site_id: model.site_id.clone(),
        groups,
        withheld,
    })
}

/// One device the scheduler may enqueue. `provider_instance_id` is the site
/// connection id (`nf:…`), which is what 4.0.2 jobs and provider health use.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlanDevice {
    pub equipment_id: String,
    pub provider_instance_id: String,
    pub revision_id: String,
    pub estimated_cost: u32,
}

/// Devices whose plan identity matches this configured site.
///
/// `Err` is a safe reason code (`plan_tenant_mismatch`, `plan_site_mismatch`,
/// `plan_provider_mismatch`). An empty `Ok` means the plan has no groups.
pub fn schedule_plan_devices(
    tenant_id: &str,
    site_id: &str,
    connection_id: &str,
    plan: &IngestPlan,
) -> Result<Vec<PlanDevice>, &'static str> {
    if plan.tenant_id != tenant_id {
        return Err("plan_tenant_mismatch");
    }
    if plan.site_id != site_id {
        return Err("plan_site_mismatch");
    }
    let matched: Vec<&IngestDeviceGroup> = plan
        .groups
        .iter()
        .filter(|group| {
            super::http_policy::provider_ids_equivalent(&group.provider_instance_id, connection_id)
        })
        .collect();
    if matched.is_empty() {
        if plan.groups.is_empty() {
            return Ok(Vec::new());
        }
        return Err("plan_provider_mismatch");
    }
    Ok(matched
        .into_iter()
        .map(|group| PlanDevice {
            equipment_id: group.equipment_id.clone(),
            provider_instance_id: connection_id.to_string(),
            revision_id: plan.revision_id.clone(),
            estimated_cost: u32::try_from(group.points.len()).unwrap_or(1).max(1),
        })
        .collect())
}

fn source_index(plan: &IngestPlan) -> BTreeMap<String, (String, String, String)> {
    let mut out = BTreeMap::new();
    for group in &plan.groups {
        for point in &group.points {
            out.insert(
                point.source_point_id.clone(),
                (
                    group.equipment_id.clone(),
                    point.canonical_role.clone(),
                    point.source_unit.clone().unwrap_or_default(),
                ),
            );
        }
    }
    out
}

impl CommittedModelStore {
    pub fn try_activate(
        &mut self,
        expected_revision: Option<&str>,
        model: &CommittedModel,
    ) -> Result<ActivationReport, String> {
        validate_model(model)?;
        let key = (model.tenant_id.clone(), model.site_id.clone());
        let previous = self.active.get(&key).map(|active| active.plan.clone());
        let previous_revision = previous.as_ref().map(|plan| plan.revision_id.clone());
        if let Some(expected) = expected_revision {
            if previous_revision.as_deref() != Some(expected) {
                return Err(format!(
                    "compare-and-swap conflict: active {} != expected {expected}",
                    previous_revision.as_deref().unwrap_or("<none>")
                ));
            }
        }
        let revision_id = revision_id(model)?;
        let plan = if let Some(cached) = self.plans.get(&revision_id) {
            cached.clone()
        } else {
            let plan = build_plan(model, &revision_id)?;
            self.compile_count = self.compile_count.saturating_add(1);
            self.plans.insert(revision_id.clone(), plan.clone());
            plan
        };
        let mut report = ActivationReport {
            revision_id: plan.revision_id.clone(),
            previous_revision_id: previous_revision,
            added_source_ids: Vec::new(),
            removed_source_ids: Vec::new(),
            remapped_source_ids: Vec::new(),
            scheduled_points: plan.groups.iter().map(|g| g.points.len()).sum(),
            withheld_points: plan.withheld.len(),
        };
        if let Some(prev) = previous.as_ref() {
            let before = source_index(prev);
            let after = source_index(&plan);
            for (id, signature) in &after {
                match before.get(id) {
                    None => report.added_source_ids.push(id.clone()),
                    Some(old) if old != signature => report.remapped_source_ids.push(id.clone()),
                    Some(_) => {}
                }
            }
            for id in before.keys() {
                if !after.contains_key(id) {
                    report.removed_source_ids.push(id.clone());
                }
            }
        } else {
            report.added_source_ids = source_index(&plan).into_keys().collect();
        }
        self.active.insert(
            key,
            ActiveRevision {
                revision_id: plan.revision_id.clone(),
                plan,
            },
        );
        Ok(report)
    }
}

fn reject_forbidden_keys(value: &Value, path: &str) -> Result<(), String> {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                let normalized = key.to_ascii_lowercase().replace('-', "_");
                if FORBIDDEN_KEYS.contains(&normalized.as_str()) {
                    return Err(format!(
                        "model must not carry executable field {path}.{key}"
                    ));
                }
                reject_forbidden_keys(child, &format!("{path}.{key}"))?;
            }
            Ok(())
        }
        Value::Array(items) => {
            for (idx, child) in items.iter().enumerate() {
                reject_forbidden_keys(child, &format!("{path}[{idx}]"))?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use open_fdd_edge_prototype::csv_ingest::portal_ingest_sparql::{
        compile_bindings_from_snapshot, IngestSparqlScope,
    };

    fn scope() -> ModelScope {
        ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        }
    }

    fn point(
        semantic: &str,
        source: &str,
        role: &str,
        selection: &str,
        fdd_ready: bool,
        provisional: bool,
    ) -> CommittedPoint {
        CommittedPoint {
            point_id: semantic.into(),
            provider_point_id: source.into(),
            canonical_role: Some(role.into()),
            selection_status: selection.into(),
            fdd_ready,
            unit: Some("degF".into()),
            canonical_unit: None,
            kind: Some("Number".into()),
            quantity: None,
            provisional,
            display_name: Some("Supply Air Temp".into()),
            history_mode: None,
            cadence_secs: None,
            heartbeat_secs: None,
            primary_reference: false,
        }
    }

    fn model_with(points: Vec<CommittedPoint>) -> CommittedModel {
        CommittedModel {
            schema: SCHEMA.into(),
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
            truncated: false,
            equipment: vec![CommittedEquipment {
                equipment_id: "AHU_1".into(),
                equip_type: "ahu".into(),
                points,
            }],
        }
    }

    #[test]
    fn engineer_overlay_unit_changes_model_revision() {
        let dir = tempfile::tempdir().expect("tempdir");
        let root = dir.path();
        let bid = "site-overlay-rev";
        let pid = "pt-oa";
        let base = point(
            "urn:openfdd:point:site-a:AHU_1:oa_t",
            pid,
            "oa_t",
            "approved",
            true,
            false,
        );
        let mut bare = base.clone();
        bare.unit = None;
        let rev_bare = revision_id(&model_with(vec![bare])).unwrap();
        open_fdd_edge_prototype::csv_ingest::model_overlay::upsert_engineer_point_overlay(
            root,
            bid,
            pid,
            Some("degF"),
            Some("absolute_temperature"),
            None,
            false,
        )
        .expect("overlay");
        let mut with_unit = base.clone();
        with_unit.unit = None;
        let mut model = model_with(vec![with_unit]);
        apply_engineer_point_overlays(root, bid, &mut model).expect("merge");
        let rev_eng = revision_id(&model).unwrap();
        assert_ne!(rev_bare, rev_eng);
        assert_eq!(model.equipment[0].points[0].unit.as_deref(), Some("degF"));
        use fdd_core::sensor_sweep::sweep_assessable_sql_role;
        assert!(!sweep_assessable_sql_role("oa_t", bare.unit.as_deref()));
    }

    #[test]
    fn cadence_change_changes_the_model_revision() {
        let mut base = point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        );
        base.history_mode = Some("interval".into());
        base.cadence_secs = Some(300);
        let mut changed = base.clone();
        changed.cadence_secs = Some(900);
        let mut cov = base.clone();
        cov.history_mode = Some("cov".into());
        cov.cadence_secs = None;
        let hourly = revision_id(&model_with(vec![base])).unwrap();
        let fifteen = revision_id(&model_with(vec![changed])).unwrap();
        let change_of_value = revision_id(&model_with(vec![cov])).unwrap();
        assert_ne!(hourly, fifteen);
        assert_ne!(hourly, change_of_value);
        let plain = point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        );
        let again = plain.clone();
        assert_eq!(
            revision_id(&model_with(vec![plain])).unwrap(),
            revision_id(&model_with(vec![again])).unwrap()
        );
    }

    #[test]
    fn semantic_id_is_not_the_source_id_and_display_name_is_not_a_role() {
        let model = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        let mut store = CommittedModelStore::default();
        let report = store.try_activate(None, &model).unwrap();
        let plan = store.active_plan("tenant-a", "site-a").unwrap();
        let scheduled = &plan.groups[0].points[0];
        assert_eq!(
            scheduled.semantic_point_id,
            "urn:openfdd:point:site-a:AHU_1:sat"
        );
        assert_eq!(scheduled.source_point_id, "uuid-sat");
        assert_eq!(scheduled.canonical_role, "sat");
        assert_ne!(scheduled.canonical_role, "Supply Air Temp");
        assert_eq!(report.scheduled_points, 1);
        assert!(!format!("{plan:?}").contains("httpMethod"));
    }

    #[test]
    fn excluded_and_provisional_are_withheld() {
        let model = model_with(vec![
            point(
                "urn:openfdd:point:site-a:AHU_1:sat",
                "uuid-sat",
                "sat",
                "approved",
                true,
                false,
            ),
            point(
                "urn:openfdd:point:site-a:AHU_1:plate",
                "uuid-plate",
                "mixed-air-temp",
                "approved",
                false,
                true,
            ),
            point(
                "urn:openfdd:point:site-a:AHU_1:x",
                "uuid-x",
                "sat",
                "excluded",
                false,
                false,
            ),
        ]);
        let mut store = CommittedModelStore::default();
        store.try_activate(None, &model).unwrap();
        let plan = store.active_plan("tenant-a", "site-a").unwrap();
        assert_eq!(plan.groups[0].points.len(), 1);
        assert_eq!(plan.groups[0].points[0].source_point_id, "uuid-sat");
        let reasons: Vec<_> = plan.withheld.iter().map(|w| w.reason.as_str()).collect();
        assert!(reasons.contains(&"provisional"));
        assert!(reasons.contains(&"excluded"));
    }

    #[test]
    fn rejected_revision_preserves_last_valid_plan() {
        let good = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        let mut store = CommittedModelStore::default();
        let first = store.try_activate(None, &good).unwrap();
        let mut bad = good.clone();
        bad.truncated = true;
        let err = store
            .try_activate(Some(&first.revision_id), &bad)
            .unwrap_err();
        assert!(err.contains("truncated"), "{err}");
        assert_eq!(
            store.active_revision("tenant-a", "site-a"),
            Some(first.revision_id.as_str())
        );
        assert_eq!(store.compile_count(), 1);
    }

    #[test]
    fn same_revision_compiles_once_and_cas_guards_replacement() {
        let model = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        let mut store = CommittedModelStore::default();
        let first = store.try_activate(None, &model).unwrap();
        store
            .try_activate(Some(&first.revision_id), &model)
            .unwrap();
        assert_eq!(store.compile_count(), 1);
        let err = store
            .try_activate(Some("not-the-revision"), &model)
            .unwrap_err();
        assert!(err.contains("compare-and-swap"), "{err}");
        assert_eq!(
            store.active_revision("tenant-a", "site-a"),
            Some(first.revision_id.as_str())
        );
    }

    #[test]
    fn valid_edit_changes_the_active_plan_without_a_second_compile_of_the_old_revision() {
        let first_model = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        let second_model = model_with(vec![
            point(
                "urn:openfdd:point:site-a:AHU_1:sat",
                "uuid-sat",
                "zone-air-temp",
                "approved",
                true,
                false,
            ),
            point(
                "urn:openfdd:point:site-a:AHU_1:oat",
                "uuid-oat",
                "outside-air-temp",
                "approved",
                true,
                false,
            ),
        ]);
        let mut store = CommittedModelStore::default();
        let first = store.try_activate(None, &first_model).unwrap();
        let second = store
            .try_activate(Some(&first.revision_id), &second_model)
            .unwrap();
        assert_eq!(store.compile_count(), 2);
        assert!(second.remapped_source_ids.contains(&"uuid-sat".into()));
        assert!(second.added_source_ids.contains(&"uuid-oat".into()));
        let roles: Vec<_> = store.active_plan("tenant-a", "site-a").unwrap().groups[0]
            .points
            .iter()
            .map(|p| p.canonical_role.as_str())
            .collect();
        assert_eq!(roles, vec!["outside-air-temp", "zone-air-temp"]);
    }

    #[test]
    fn wrong_site_duplicate_conflict_and_executable_json_fail() {
        let mut wrong = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        wrong.site_id = "other-site".into();
        let err = model_from_json(
            &serde_json::to_string(&json_model(&wrong)).unwrap(),
            &scope(),
        )
        .unwrap_err();
        assert!(err.contains("wrong-site"), "{err}");

        let dup = model_with(vec![
            point(
                "urn:openfdd:point:site-a:AHU_1:sat",
                "uuid-same",
                "sat",
                "approved",
                true,
                false,
            ),
            point(
                "urn:openfdd:point:site-a:AHU_1:oat",
                "uuid-same",
                "outside-air-temp",
                "approved",
                true,
                false,
            ),
        ]);
        assert!(validate_model(&dup).unwrap_err().contains("duplicate"));

        let conflict = model_with(vec![
            point(
                "urn:openfdd:point:site-a:AHU_1:a",
                "uuid-a",
                "sat",
                "approved",
                true,
                false,
            ),
            point(
                "urn:openfdd:point:site-a:AHU_1:b",
                "uuid-b",
                "sat",
                "approved",
                true,
                false,
            ),
        ]);
        assert!(validate_model(&conflict)
            .unwrap_err()
            .contains("conflicting active role"));

        let mut executable = json_model(&model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]));
        executable["equipment"][0]["points"][0]["http_method"] = json!("POST");
        let err = model_from_json(&executable.to_string(), &scope()).unwrap_err();
        assert!(err.contains("executable"), "{err}");
    }

    #[test]
    fn empty_type_and_malformed_unit_reject() {
        let mut empty_type = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        empty_type.equipment[0].equip_type.clear();
        assert!(validate_model(&empty_type)
            .unwrap_err()
            .contains("empty type"));

        let mut bad_unit = model_with(vec![point(
            "urn:openfdd:point:site-a:AHU_1:sat",
            "uuid-sat",
            "sat",
            "approved",
            true,
            false,
        )]);
        bad_unit.equipment[0].points[0].unit = Some("<F>".into());
        assert!(validate_model(&bad_unit)
            .unwrap_err()
            .contains("malformed unit"));
    }

    #[test]
    fn point_map_bootstrap_does_not_reuse_the_provider_id_as_semantic_id() {
        let model = model_from_point_map(
            &scope(),
            &[BootstrapPoint {
                provider_point_id: "uuid-sat".into(),
                semantic_point_id: None,
                equipment_id: "AHU_1".into(),
                role: "sat".into(),
                equip_type: Some("ahu".into()),
                unit: None,
                kind: None,
                provisional: false,
            }],
        )
        .unwrap();
        assert_ne!(
            model.equipment[0].points[0].point_id,
            model.equipment[0].points[0].provider_point_id
        );
    }

    #[test]
    fn sparql_rows_compile_to_one_cached_plan() {
        let ttl = r#"
@prefix ing: <urn:openfdd:ingest:v1:> .
<urn:openfdd:binding/sat> ing:tenantRef "tenant-a" ;
  ing:siteRef "site-a" ;
  ing:providerInstanceId "nf-conn-a" ;
  ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
  ing:equipmentRef "AHU_1" ;
  ing:pointRef "urn:openfdd:point:site-a:AHU_1:sat" ;
  ing:sourcePointId "uuid-sat" ;
  ing:canonicalRole "sat" ;
  ing:approvalState "approved" ;
  ing:equipType "ahu" .
<urn:openfdd:binding/vav> ing:tenantRef "tenant-a" ;
  ing:siteRef "site-a" ;
  ing:providerInstanceId "nf-conn-a" ;
  ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
  ing:equipmentRef "VAV_1" ;
  ing:pointRef "urn:openfdd:point:site-a:VAV_1:zone" ;
  ing:sourcePointId "uuid-zone" ;
  ing:canonicalRole "zone-air-temp" ;
  ing:approvalState "approved" ;
  ing:equipType "vav" .
"#;
        let rows = compile_bindings_from_snapshot(
            ttl,
            &IngestSparqlScope::new(
                "tenant-a",
                "site-a",
                "urn:openfdd:ingest:v1:graph/tenant-a/site-a",
                "nf-conn-a",
            ),
        )
        .unwrap();
        let model = model_from_sparql_rows(&scope(), &rows).unwrap();
        let mut store = CommittedModelStore::default();
        store.try_activate(None, &model).unwrap();
        store.try_activate(None, &model).unwrap();
        assert_eq!(store.compile_count(), 1);
        let plan = store.active_plan("tenant-a", "site-a").unwrap();
        assert_eq!(plan.schema, PLAN_SCHEMA);
        let devices: Vec<_> = plan
            .groups
            .iter()
            .map(|g| g.equipment_id.as_str())
            .collect();
        assert_eq!(devices, vec!["AHU_1", "VAV_1"]);
        assert_eq!(plan.groups[0].equip_type, "ahu");
        assert_eq!(plan.groups[1].equip_type, "vav");
    }

    fn expectation_snapshot(extra: &str) -> String {
        format!(
            r#"
@prefix ing: <urn:openfdd:ingest:v1:> .
<urn:openfdd:binding/sat> ing:tenantRef "tenant-a" ;
  ing:siteRef "site-a" ;
  ing:providerInstanceId "nf-conn-a" ;
  ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
  ing:equipmentRef "AHU_1" ;
  ing:pointRef "urn:openfdd:point:site-a:AHU_1:sat" ;
  ing:sourcePointId "uuid-sat" ;
  ing:canonicalRole "sat" ;
  {extra}
  ing:equipType "ahu" .
"#
        )
    }

    fn sparql_scope() -> IngestSparqlScope {
        IngestSparqlScope::new(
            "tenant-a",
            "site-a",
            "urn:openfdd:ingest:v1:graph/tenant-a/site-a",
            "nf-conn-a",
        )
    }

    fn revision_for(extra: &str) -> Result<(String, CommittedModel), String> {
        let rows = compile_bindings_from_snapshot(&expectation_snapshot(extra), &sparql_scope())?;
        let model = model_from_sparql_rows(&scope(), &rows)?;
        Ok((revision_id(&model)?, model))
    }

    #[test]
    fn binding_expectations_enter_the_plan_and_the_revision() {
        let base = r#"ing:approvalState "approved" ; ing:sourceUnit "degF" ; ing:quantity "temperature" ; ing:historyMode "interval" ; ing:cadenceSecs "300" ;"#;
        let (base_rev, model) = revision_for(base).unwrap();
        let point = &model.equipment[0].points[0];
        assert_eq!(point.history_mode.as_deref(), Some("interval"));
        assert_eq!(point.cadence_secs, Some(300));
        assert_eq!(point.quantity.as_deref(), Some("temperature"));
        let mut store = CommittedModelStore::default();
        store.try_activate(None, &model).unwrap();
        let plan = store.active_plan("tenant-a", "site-a").unwrap();
        assert_eq!(plan.groups[0].points[0].cadence_secs, Some(300));
        assert_eq!(
            plan.groups[0].points[0].history_mode.as_deref(),
            Some("interval")
        );

        // Control: the same snapshot compiles to the same revision.
        assert_eq!(revision_for(base).unwrap().0, base_rev);

        let variants = [
            (
                "cadence",
                r#"ing:approvalState "approved" ; ing:sourceUnit "degF" ; ing:quantity "temperature" ; ing:historyMode "interval" ; ing:cadenceSecs "900" ;"#,
            ),
            (
                "cov",
                r#"ing:approvalState "approved" ; ing:sourceUnit "degF" ; ing:quantity "temperature" ; ing:historyMode "cov" ;"#,
            ),
            (
                "heartbeat",
                r#"ing:approvalState "approved" ; ing:sourceUnit "degF" ; ing:quantity "temperature" ; ing:historyMode "cov" ; ing:heartbeatSecs "3600" ;"#,
            ),
            (
                "unit",
                r#"ing:approvalState "approved" ; ing:sourceUnit "degC" ; ing:quantity "temperature" ; ing:historyMode "interval" ; ing:cadenceSecs "300" ;"#,
            ),
            (
                "quantity",
                r#"ing:approvalState "approved" ; ing:sourceUnit "degF" ; ing:quantity "other" ; ing:historyMode "interval" ; ing:cadenceSecs "300" ;"#,
            ),
            (
                "approval",
                r#"ing:approvalState "unresolved" ; ing:sourceUnit "degF" ; ing:quantity "temperature" ; ing:historyMode "interval" ; ing:cadenceSecs "300" ;"#,
            ),
            (
                "unknown",
                r#"ing:approvalState "approved" ; ing:sourceUnit "degF" ; ing:quantity "temperature" ;"#,
            ),
        ];
        let mut seen = vec![base_rev];
        for (label, extra) in variants {
            let (rev, _) = revision_for(extra).unwrap_or_else(|e| panic!("{label}: {e}"));
            assert!(!seen.contains(&rev), "{label} did not change the revision");
            seen.push(rev);
        }

        // No stated expectation stays unknown in the plan, never a default cadence.
        let (_, unknown) = revision_for(variants[6].1).unwrap();
        assert_eq!(unknown.equipment[0].points[0].history_mode, None);
        assert_eq!(unknown.equipment[0].points[0].cadence_secs, None);
    }

    #[test]
    fn malformed_binding_expectations_are_rejected() {
        let cases = [
            (
                "words",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ; ing:cadenceSecs "5m" ;"#,
            ),
            (
                "negative",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ; ing:cadenceSecs "-300" ;"#,
            ),
            (
                "zero",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ; ing:cadenceSecs "0" ;"#,
            ),
            (
                "too long",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ; ing:cadenceSecs "86401" ;"#,
            ),
            (
                "no cadence",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ;"#,
            ),
            (
                "orphan cadence",
                r#"ing:approvalState "approved" ; ing:cadenceSecs "300" ;"#,
            ),
            (
                "interval heartbeat",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ; ing:cadenceSecs "300" ; ing:heartbeatSecs "600" ;"#,
            ),
            (
                "cov cadence",
                r#"ing:approvalState "approved" ; ing:historyMode "cov" ; ing:cadenceSecs "300" ;"#,
            ),
            (
                "cov heartbeat range",
                r#"ing:approvalState "approved" ; ing:historyMode "cov" ; ing:heartbeatSecs "604801" ;"#,
            ),
            (
                "mode",
                r#"ing:approvalState "approved" ; ing:historyMode "poll" ; ing:cadenceSecs "300" ;"#,
            ),
            (
                "blank",
                r#"ing:approvalState "approved" ; ing:historyMode "interval" ; ing:cadenceSecs " " ;"#,
            ),
            (
                "quantity",
                r#"ing:approvalState "approved" ; ing:quantity "air temp" ;"#,
            ),
        ];
        for (label, extra) in cases {
            assert!(revision_for(extra).is_err(), "{label} was accepted");
        }
    }

    #[test]
    fn connection_id_schedules_the_slug_plan() {
        let plan = IngestPlan {
            schema: PLAN_SCHEMA.into(),
            revision_id: "rev".into(),
            tenant_id: "lab".into(),
            site_id: "BOSSPI".into(),
            groups: vec![IngestDeviceGroup {
                provider_instance_id: "nf-bosspi".into(),
                equipment_id: "NF_EDGE".into(),
                equip_type: "ahu".into(),
                points: vec![],
            }],
            withheld: vec![],
        };
        let devices =
            schedule_plan_devices("lab", "BOSSPI", "nf:nf-bosspi", &plan).expect("alias match");
        assert_eq!(devices.len(), 1);
        assert_eq!(devices[0].provider_instance_id, "nf:nf-bosspi");
        assert_eq!(devices[0].equipment_id, "NF_EDGE");
        assert_eq!(
            schedule_plan_devices("other", "BOSSPI", "nf:nf-bosspi", &plan),
            Err("plan_tenant_mismatch")
        );
        assert_eq!(
            schedule_plan_devices("lab", "BOSSPI", "nf:other", &plan),
            Err("plan_provider_mismatch")
        );
    }

    fn json_model(model: &CommittedModel) -> Value {
        serde_json::to_value(model).unwrap_or_else(|_| json!({}))
    }
}
