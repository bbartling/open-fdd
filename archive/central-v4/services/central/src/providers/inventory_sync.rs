//! Portal inventory → historian identity, RDF overlay, and ingest plan.
//!
//! The portal inventory is the source of truth for the building model. Each
//! successful inventory read:
//!
//! 1. references every listed point in `point_map` (one row per portal point
//!    id; role, unit, and equipment link updated in place);
//! 2. marks points from this provider that are no longer listed unreferenced.
//!    Their samples stay and become orphaned historian data;
//! 3. upserts listed equipment and points into the writable RDF overlay and
//!    removes the ones this provider no longer lists, leaving a tombstone;
//! 4. activates an ingest plan built from the tagged points.
//!
//! A snapshot that may be truncated is applied without step 2 or the RDF
//! removals, and it does not replace the active ingest plan. Nothing here
//! deletes samples or `point_map` rows. The last complete plan is written
//! beside the overlay and restored on process start. An empty `totalCount`
//! is a finished inventory and does replace the plan.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use fdd_tsdb::{PortalInventoryPoint, PortalInventoryReport, Tsdb};
use open_fdd_edge_prototype::csv_ingest::model_overlay::{
    self, PortalEquip, PortalPoint, PortalSyncReport,
};
use open_fdd_edge_prototype::csv_ingest::semantic_selector;
use serde::Serialize;
use tracing::{debug, warn};

use super::committed_model::{
    apply_engineer_point_overlays, model_from_json, model_from_point_map,
    resolve_point_map_binding, validate_model, BootstrapPoint, CommittedModel, CommittedModelStore,
    ModelScope,
};
use super::config::SiteConfig;
use super::Runtime;
use crate::haystack_rdf::HaystackRdfCache;

/// One tagged point from a portal inventory read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InventoryPoint {
    pub portal_point_id: String,
    pub display_name: Option<String>,
    pub unit: Option<String>,
    pub equipment_id: String,
    pub equip_type: Option<String>,
    pub equip_dis: Option<String>,
    pub equip_markers: Vec<String>,
    pub role: String,
    pub markers: Vec<String>,
    pub kind: Option<String>,
    pub tz: Option<String>,
    pub his: Option<bool>,
    pub his_mode: Option<String>,
    pub enum_value: Option<String>,
    pub ref_rel: Option<String>,
    pub ref_id: Option<String>,
}

/// Why a walk did not replace the active plan. Absent when the snapshot is complete.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct InventoryDiagnostics {
    pub pages_fetched: u32,
    pub bytes_read: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_count: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub snapshot_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InventorySnapshot {
    pub points: Vec<InventoryPoint>,
    /// Points the portal returned, tagged or not.
    pub source_points: usize,
    /// True only when every page of this snapshot was accepted and the portal
    /// total was met, or a short page ended a result that did not advertise a
    /// total. `totalCount == 0` is complete. An empty body with no total is not.
    pub complete: bool,
    pub diagnostics: InventoryDiagnostics,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct InventorySyncOutcome {
    pub historian: Option<PortalInventoryReport>,
    pub rdf: Option<PortalSyncReport>,
    pub model_activated: bool,
    /// The previous plan is still the schedule.
    pub plan_retained: bool,
    /// Incomplete inventory or a plan that could not be saved.
    pub degraded: bool,
    pub diagnostics: InventoryDiagnostics,
    pub errors: Vec<String>,
}

const LAST_GOOD_SCHEMA: &str = "ofdd_portal_last_good_plan_v1";
const LAST_GOOD_FILE: &str = "portal_last_good_plan.json";

#[derive(Debug, Serialize, serde::Deserialize)]
struct LastGoodFile {
    schema: String,
    model: CommittedModel,
    source_points: u64,
    #[serde(default)]
    total_count: Option<u64>,
    #[serde(default)]
    snapshot_version: Option<String>,
}

pub fn portal_building_root(building_id: &str) -> PathBuf {
    open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(building_id)
}

/// Equipment and points for the RDF overlay. Point keys come from the
/// historian when it assigned one; otherwise `{equipment_id}.{role}`.
pub fn overlay_rows(
    snapshot: &InventorySnapshot,
    keys: &BTreeMap<String, String>,
) -> (Vec<PortalEquip>, Vec<PortalPoint>) {
    let mut equipment: BTreeMap<String, PortalEquip> = BTreeMap::new();
    let mut points = Vec::with_capacity(snapshot.points.len());
    for pt in &snapshot.points {
        let eq = equipment
            .entry(pt.equipment_id.clone())
            .or_insert_with(|| PortalEquip {
                equipment_id: pt.equipment_id.clone(),
                dis: None,
                kind: None,
                markers: Vec::new(),
            });
        if eq.dis.is_none() {
            eq.dis = pt.equip_dis.clone();
        }
        if eq.kind.is_none() {
            eq.kind = pt.equip_type.clone();
        }
        for marker in &pt.equip_markers {
            if !eq.markers.contains(marker) {
                eq.markers.push(marker.clone());
            }
        }
        let key = keys.get(&pt.portal_point_id).cloned().unwrap_or_else(|| {
            if pt.role.trim().is_empty() {
                pt.portal_point_id.clone()
            } else {
                format!("{}.{}", pt.equipment_id, pt.role)
            }
        });
        points.push(PortalPoint {
            point_id: pt.portal_point_id.clone(),
            equipment_id: pt.equipment_id.clone(),
            openfdd_key: key,
            role: pt.role.clone(),
            dis: pt.display_name.clone(),
            unit: pt.unit.clone(),
            markers: pt.markers.clone(),
            kind: pt.kind.clone(),
            tz: pt.tz.clone(),
            his: pt.his,
            his_mode: pt.his_mode.clone(),
            enum_value: pt.enum_value.clone(),
            ref_rel: pt.ref_rel.clone(),
            ref_id: pt.ref_id.clone(),
        });
    }
    for eq in equipment.values_mut() {
        eq.markers.sort();
    }
    (equipment.into_values().collect(), points)
}

pub fn historian_rows(
    snapshot: &InventorySnapshot,
    building_root: &Path,
) -> Result<Vec<PortalInventoryPoint>, String> {
    let overlay = open_fdd_edge_prototype::csv_ingest::model_overlay::load_engineer_point_overlay(
        building_root,
    )
    .map_err(|e| {
        format!(
            "engineer overlay unreadable under {}: {e}",
            building_root.display()
        )
    })?;
    snapshot
        .points
        .iter()
        .map(|pt| {
            let entry = overlay.points.get(&pt.portal_point_id);
            let binding =
                resolve_point_map_binding(pt.unit.as_deref(), pt.his_mode.as_deref(), entry)?;
            Ok(PortalInventoryPoint {
                portal_point_id: pt.portal_point_id.clone(),
                equipment_id: pt.equipment_id.clone(),
                equip_type: pt.equip_type.clone(),
                role: pt.role.clone(),
                source_unit: binding.source_unit,
                source_history_mode: binding.source_history_mode,
                unit: binding.unit,
                quantity: binding.quantity,
                cadence_secs: binding.cadence_secs,
                history_mode: binding.history_mode,
            })
        })
        .collect()
}

/// Ingest bindings for the tagged points that carry an equipment type.
pub fn bootstrap_points(snapshot: &InventorySnapshot) -> Vec<BootstrapPoint> {
    snapshot
        .points
        .iter()
        .filter(|pt| pt.equip_type.is_some() && !pt.role.trim().is_empty())
        .map(|pt| BootstrapPoint {
            provider_point_id: pt.portal_point_id.clone(),
            semantic_point_id: None,
            equipment_id: pt.equipment_id.clone(),
            role: pt.role.clone(),
            equip_type: pt.equip_type.clone(),
            unit: pt.unit.clone(),
            kind: pt.kind.clone(),
            provisional: false,
        })
        .collect()
}

/// Historian and RDF halves of one sync. `tsdb` is `None` without Timescale.
pub async fn apply_to_stores(
    tsdb: Option<&Tsdb>,
    building_root: &Path,
    building_id: &str,
    provider_instance_id: &str,
    snapshot: &InventorySnapshot,
) -> InventorySyncOutcome {
    let mut outcome = InventorySyncOutcome::default();
    let mut keys = BTreeMap::new();
    if let Some(tsdb) = tsdb {
        let rows = match historian_rows(snapshot, building_root) {
            Ok(rows) => rows,
            Err(message) => {
                warn!(%building_id, %message, "portal inventory overlay read failed");
                outcome.errors.push("engineer_overlay_unreadable".into());
                outcome.diagnostics.reason = Some(message);
                return outcome;
            }
        };
        match tsdb
            .sync_portal_inventory(building_id, provider_instance_id, &rows, snapshot.complete)
            .await
        {
            Ok(report) => {
                keys = report.keys.clone();
                outcome.historian = Some(report);
            }
            Err(err) => {
                warn!(%building_id, error = %err, "portal inventory historian sync failed");
                outcome.errors.push("historian_sync_failed".into());
                // Without the historian keys the overlay could advertise a key
                // the historian does not hold. Leave the model as it was.
                return outcome;
            }
        }
    }
    let (equipment, points) = overlay_rows(snapshot, &keys);
    let mut equipment_ids: Vec<String> =
        equipment.iter().map(|eq| eq.equipment_id.clone()).collect();
    equipment_ids.sort();
    equipment_ids.dedup();
    let root = building_root.to_path_buf();
    let bid = building_id.to_string();
    let source = provider_instance_id.to_string();
    let complete = snapshot.complete;
    let rdf = tokio::task::spawn_blocking(
        move || -> Result<(PortalSyncReport, Option<String>), String> {
            std::fs::create_dir_all(&root).map_err(|e| format!("building root: {e}"))?;
            let report = model_overlay::sync_portal_inventory(
                &root, &bid, &source, &equipment, &points, complete,
            )?;
            let requests = semantic_selector::optional_discharge_selectors(&equipment_ids);
            let selector_error =
                semantic_selector::bind_semantic_aliases(&root, &bid, &requests).err();
            Ok((report, selector_error))
        },
    )
    .await;
    match rdf {
        Ok(Ok((report, selector_error))) => {
            outcome.rdf = Some(report);
            if selector_error.is_some() {
                outcome.errors.push("selector_bind_failed".into());
            }
        }
        Ok(Err(err)) => {
            warn!(%building_id, error = %err, "portal inventory RDF sync failed");
            outcome.errors.push("rdf_sync_failed".into());
        }
        Err(err) => {
            warn!(%building_id, error = %err, "portal inventory RDF task failed");
            outcome.errors.push("rdf_sync_failed".into());
        }
    }
    outcome
}

/// Full sync for one site: historian, RDF overlay, SPARQL cache, ingest plan.
pub async fn apply(
    runtime: &Runtime,
    rdf_cache: &HaystackRdfCache,
    site: &SiteConfig,
    snapshot: &InventorySnapshot,
) -> InventorySyncOutcome {
    apply_at(
        runtime,
        rdf_cache,
        site,
        &portal_building_root(&site.building_id),
        snapshot,
    )
    .await
}

/// Same as [`apply`] with an explicit overlay directory. Tests use a temp root.
pub async fn apply_at(
    runtime: &Runtime,
    rdf_cache: &HaystackRdfCache,
    site: &SiteConfig,
    building_root: &Path,
    snapshot: &InventorySnapshot,
) -> InventorySyncOutcome {
    let tsdb = if crate::timescale_historian::historian_is_timescale() {
        match Tsdb::shared().await {
            Ok(tsdb) => Some(tsdb),
            Err(err) => {
                warn!(building_id = %site.building_id, error = %err, "portal inventory: historian unavailable");
                return InventorySyncOutcome {
                    diagnostics: snapshot.diagnostics.clone(),
                    degraded: true,
                    plan_retained: true,
                    errors: vec!["historian_unavailable".into()],
                    ..InventorySyncOutcome::default()
                };
            }
        }
    } else {
        None
    };
    let mut outcome = apply_to_stores(
        tsdb.as_deref(),
        building_root,
        &site.building_id,
        &site.provider_instance_id,
        snapshot,
    )
    .await;
    outcome.diagnostics = snapshot.diagnostics.clone();
    if outcome.rdf.as_ref().is_some_and(|r| r.changed) {
        rdf_cache.invalidate_building(&site.building_id);
    }
    if !snapshot.complete {
        let code = snapshot
            .diagnostics
            .reason
            .clone()
            .unwrap_or_else(|| "inventory_incomplete".to_string());
        warn!(building_id = %site.building_id, reason = %code, "incomplete inventory kept the last plan");
        if !outcome.errors.iter().any(|err| err == &code) {
            outcome.errors.push(code);
        }
        outcome.degraded = true;
        outcome.plan_retained = true;
        return outcome;
    }
    if !outcome.errors.is_empty() {
        outcome.degraded = true;
        outcome.plan_retained = true;
        return outcome;
    }
    // An empty complete inventory is a real schedule with no devices.
    // The historian keeps the connection id (`nf:…`). The plan slug drops
    // colons; using the connection id here fails validation and leaves
    // the startup plan unmatched.
    let entries = bootstrap_points(snapshot);
    let scope = ModelScope {
        tenant_id: site.tenant_id.clone(),
        site_id: site.building_id.clone(),
        provider_instance_id: site.model.provider_instance_id.clone(),
    };
    let mut model = match model_from_point_map(&scope, &entries) {
        Ok(model) => model,
        Err(err) => {
            warn!(building_id = %site.building_id, error = %err, "portal inventory plan invalid");
            outcome.errors.push("plan_invalid".into());
            outcome.degraded = true;
            outcome.plan_retained = true;
            return outcome;
        }
    };
    if let Err(err) = apply_engineer_point_overlays(building_root, &site.building_id, &mut model) {
        warn!(building_id = %site.building_id, error = %err, "engineer point overlay merge failed");
        outcome.errors.push("engineer_overlay_invalid".into());
        outcome.degraded = true;
        outcome.plan_retained = true;
        return outcome;
    }
    if let Err(err) = validate_model(&model) {
        warn!(building_id = %site.building_id, error = %err, "portal inventory plan invalid after engineer overlay");
        outcome.errors.push("plan_invalid".into());
        outcome.degraded = true;
        outcome.plan_retained = true;
        return outcome;
    }
    {
        let mut models = runtime.models.lock().unwrap_or_else(|e| e.into_inner());
        match models.try_activate(None, &model) {
            Ok(report) => {
                debug!(building_id = %site.building_id, revision = %report.revision_id, "portal inventory plan active");
                outcome.model_activated = true;
            }
            Err(err) => {
                warn!(building_id = %site.building_id, error = %err, "portal inventory plan did not activate");
                outcome.errors.push("plan_not_activated".into());
                outcome.degraded = true;
                outcome.plan_retained = true;
                return outcome;
            }
        }
    }
    if let Err(err) = persist_last_good(building_root, &model, snapshot).await {
        warn!(building_id = %site.building_id, error = %err, "last good inventory plan was not saved");
        outcome.errors.push(err);
        outcome.degraded = true;
    }
    outcome
}

async fn persist_last_good(
    root: &Path,
    model: &CommittedModel,
    snapshot: &InventorySnapshot,
) -> Result<(), String> {
    let file = LastGoodFile {
        schema: LAST_GOOD_SCHEMA.to_string(),
        model: model.clone(),
        source_points: u64::try_from(snapshot.source_points).unwrap_or(u64::MAX),
        total_count: snapshot.diagnostics.total_count,
        snapshot_version: snapshot.diagnostics.snapshot_version.clone(),
    };
    let bytes = serde_json::to_vec(&file).map_err(|_| "plan_not_persisted".to_string())?;
    tokio::fs::create_dir_all(root)
        .await
        .map_err(|_| "plan_not_persisted".to_string())?;
    let tmp = root.join(".portal_last_good_plan.json.tmp");
    let dest = root.join(LAST_GOOD_FILE);
    tokio::fs::write(&tmp, &bytes)
        .await
        .map_err(|_| "plan_not_persisted".to_string())?;
    if tokio::fs::rename(&tmp, &dest).await.is_err() {
        let _ = tokio::fs::remove_file(&tmp).await;
        return Err("plan_not_persisted".to_string());
    }
    Ok(())
}

/// Load the last complete inventory plan into `models`. Missing file is
/// `Ok(false)`. A corrupt file leaves the current plan in place.
pub fn restore_last_good_plan(
    models: &mut CommittedModelStore,
    building_root: &Path,
    scope: &ModelScope,
) -> Result<bool, String> {
    let path = building_root.join(LAST_GOOD_FILE);
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(_) => return Err("saved_plan_unreadable".to_string()),
    };
    let file: LastGoodFile =
        serde_json::from_slice(&bytes).map_err(|_| "saved_plan_invalid".to_string())?;
    if file.schema != LAST_GOOD_SCHEMA {
        return Err("saved_plan_schema".to_string());
    }
    let raw = serde_json::to_string(&file.model).map_err(|_| "saved_plan_invalid".to_string())?;
    let model = model_from_json(&raw, scope).map_err(|_| "saved_plan_invalid".to_string())?;
    models
        .try_activate(None, &model)
        .map_err(|_| "saved_plan_invalid".to_string())?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::nf::parse_inventory_json;
    use open_fdd_edge_prototype::csv_ingest::haystack_sparql_bindings;
    use serde_json::Value;

    const V1: &str = include_str!("fixtures/nf_inventory_v1.json");
    const V2: &str = include_str!("fixtures/nf_inventory_v2.json");
    const SOURCE: &str = "nf:site-a";

    fn snapshot(text: &str) -> InventorySnapshot {
        parse_inventory_json(text, 500).expect("inventory fixture")
    }

    fn sparql_rows(root: &Path, building: &str, query: &str) -> Vec<Value> {
        let overlay = model_overlay::load_ttl(root).expect("overlay");
        let out = haystack_sparql_bindings::execute_readonly_on_overlay(building, query, &overlay)
            .expect("sparql");
        out["rows"].as_array().cloned().unwrap_or_default()
    }

    fn ask(root: &Path, building: &str, query: &str) -> bool {
        let overlay = model_overlay::load_ttl(root).expect("overlay");
        let out = haystack_sparql_bindings::execute_readonly_on_overlay(building, query, &overlay)
            .expect("sparql");
        out["boolean"].as_bool().expect("ask")
    }

    #[test]
    fn inventory_parser_reads_tags_and_skips_untagged_points() {
        let snap = snapshot(V1);
        assert_eq!(snap.source_points, 6);
        assert!(snap.complete);
        assert_eq!(snap.points.len(), 5);
        let sat = &snap.points[0];
        assert_eq!(sat.equipment_id, "AHU_1");
        assert_eq!(sat.role, "sat");
        assert_eq!(sat.kind.as_deref(), Some("Number"));
        assert_eq!(sat.equip_type.as_deref(), Some("ahu"));
        assert_eq!(sat.markers, vec!["air", "discharge", "sensor", "temp"]);
        let roles: Vec<&str> = snap.points.iter().map(|p| p.role.as_str()).collect();
        assert_eq!(
            roles,
            vec!["sat", "duct_static", "fan_status", "zone_t", "zone_flow"]
        );
        assert!(!parse_inventory_json(V1, 6).expect("full page").complete);
        assert!(
            !parse_inventory_json(r#"{"points":[]}"#, 500)
                .expect("empty")
                .complete
        );
    }

    #[tokio::test]
    async fn unmapped_semantic_point_stays_without_becoming_the_temperature_input() {
        let body = r#"{
          "points": [
            {
              "uuid": "pt-sensor",
              "name": "Discharge Setpoint",
              "units": "°F",
              "attrs": {
                "equipRef": "AHU_1",
                "equipType": "ahu",
                "kind": "Number",
                "tz": "America/Chicago",
                "his": true,
                "hisMode": "cov",
                "markers": "discharge air temp sensor"
              }
            },
            {
              "uuid": "pt-sp",
              "name": "Discharge Air Temp",
              "units": "°C",
              "attrs": {
                "equipRef": "AHU_1",
                "equipType": "ahu",
                "kind": "Number",
                "markers": "discharge,air,temp,sp"
              }
            },
            {
              "uuid": "pt-pressure",
              "name": "Supply Temp",
              "units": "inH₂O",
              "attrs": {
                "equipRef": "AHU_1",
                "equipType": "ahu",
                "role": "discharge-air-temp",
                "kind": "Number",
                "markers": ["sensor", "pressure", "duct"]
              }
            },
            {
              "uuid": "pt-spare",
              "name": "Untagged",
              "attrs": { "markers": "sensor temp" }
            }
          ]
        }"#;
        let snap = parse_inventory_json(body, 500).expect("parse");
        assert_eq!(snap.source_points, 4);
        assert_eq!(snap.points.len(), 3);
        assert!(snap
            .points
            .iter()
            .any(|pt| pt.portal_point_id == "pt-sensor" && pt.role.is_empty()));
        assert_eq!(
            snap.points
                .iter()
                .find(|pt| pt.portal_point_id == "pt-sensor")
                .expect("sensor")
                .kind
                .as_deref(),
            Some("Number")
        );
        let dir = tempfile::tempdir().expect("tempdir");
        let root = dir.path().join("SITE_UNMAPPED");
        let synced = apply_to_stores(None, &root, "SITE_UNMAPPED", SOURCE, &snap).await;
        assert!(synced.errors.is_empty(), "{:?}", synced.errors);
        assert!(ask(
            &root,
            "SITE_UNMAPPED",
            r#"ASK { ?s ofdd:pointId "pt-sensor" ; ph:kind "Number" ; ph:tz "America/Chicago" ; phIoT:hisMode "cov" ; ph:hasTag phIoT:his }"#
        ));
        assert!(!ask(
            &root,
            "SITE_UNMAPPED",
            r#"ASK { ?s ofdd:pointId "pt-sensor" ; ofdd:role ?role }"#
        ));
        assert!(!ask(
            &root,
            "SITE_UNMAPPED",
            r#"ASK { ?s ofdd:pointId "pt-spare" }"#
        ));
        let bindings =
            open_fdd_edge_prototype::csv_ingest::semantic_selector::read_semantic_selectors(&root)
                .expect("selectors");
        let sat = bindings
            .iter()
            .find(|binding| binding.alias == "sat")
            .expect("sat");
        assert_eq!(sat.outcome, "selected");
        assert_eq!(sat.readiness, "runnable");
        assert_eq!(sat.selected_external_key.as_deref(), Some("pt-sensor"));
        assert!(!sat.candidate_ids.iter().any(|id| id == "pt-pressure"));
        let sp = bindings
            .iter()
            .find(|binding| binding.alias == "sat_sp")
            .expect("sp");
        assert_eq!(sp.selected_external_key.as_deref(), Some("pt-sp"));
        assert_eq!(
            sp.unit_conversion.as_ref().expect("conversion").conversion,
            "celsius_to_fahrenheit"
        );
        let kept = bootstrap_points(&snap);
        assert!(kept.iter().all(|pt| pt.provider_point_id != "pt-sensor"));
        assert!(kept.iter().any(|pt| pt.provider_point_id == "pt-pressure"));
        assert_eq!(
            kept.iter()
                .find(|pt| pt.provider_point_id == "pt-pressure")
                .expect("pressure")
                .kind
                .as_deref(),
            Some("Number")
        );
    }

    #[tokio::test]
    async fn repeated_inventory_is_idempotent_and_removed_equipment_leaves_sparql() {
        let dir = tempfile::tempdir().expect("tempdir");
        let root = dir.path().join("SITE_INV");
        let v1 = snapshot(V1);

        let first = apply_to_stores(None, &root, "SITE_INV", SOURCE, &v1).await;
        let first_rdf = first.rdf.expect("rdf");
        assert!(first_rdf.changed);
        assert_eq!(first_rdf.equipment_upserted, 2);
        assert_eq!(first_rdf.points_upserted, 5);
        let ttl_after_first = model_overlay::load_ttl(&root).expect("ttl");

        let second = apply_to_stores(None, &root, "SITE_INV", SOURCE, &v1).await;
        let second_rdf = second.rdf.expect("rdf");
        assert!(!second_rdf.changed, "re-poll rewrote an unchanged model");
        assert_eq!(second_rdf.revision, first_rdf.revision);
        assert_eq!(
            model_overlay::load_ttl(&root).expect("ttl"),
            ttl_after_first
        );

        let nodes = sparql_rows(
            &root,
            "SITE_INV",
            "SELECT ?id (COUNT(?s) AS ?n) WHERE { ?s ofdd:pointId ?id } GROUP BY ?id",
        );
        assert_eq!(nodes.len(), 5);
        for row in &nodes {
            assert_eq!(row["n"]["value"], "1", "twin point node: {row}");
        }
        assert!(ask(
            &root,
            "SITE_INV",
            r#"ASK { ?s ofdd:equipmentId "VAV_1" }"#
        ));

        let v2 = snapshot(V2);
        let third = apply_to_stores(None, &root, "SITE_INV", SOURCE, &v2).await;
        let third_rdf = third.rdf.expect("rdf");
        assert!(third_rdf.changed);
        assert_eq!(third_rdf.equipment_deleted, vec!["VAV_1".to_string()]);
        assert_eq!(third_rdf.points_deleted.len(), 2);
        assert!(!ask(
            &root,
            "SITE_INV",
            r#"ASK { ?s ofdd:equipmentId "VAV_1" }"#
        ));
        assert!(!ask(
            &root,
            "SITE_INV",
            r#"ASK { ?s ofdd:pointId "6a1f0c2a-0001-4000-8000-00000000b001" }"#
        ));
        assert!(ask(
            &root,
            "SITE_INV",
            r#"ASK { ?s ofdd:equipmentId "AHU_1" }"#
        ));
        // Display name and tags are replaced in place, not appended.
        let dis = sparql_rows(
            &root,
            "SITE_INV",
            r#"SELECT ?dis WHERE { ?s ofdd:pointId "6a1f0c2a-0001-4000-8000-00000000a001" ; ph:dis ?dis }"#,
        );
        assert_eq!(dis.len(), 1);
        assert_eq!(dis[0]["dis"]["value"], "AHU-1 Supply Air Temp");
        let tags = sparql_rows(
            &root,
            "SITE_INV",
            r#"SELECT ?t WHERE { ?s ofdd:pointId "6a1f0c2a-0001-4000-8000-00000000a001" ; ph:hasTag ?t }"#,
        );
        assert_eq!(tags.len(), 5);

        // A pack copy of the removed equipment stays hidden by the tombstone.
        let pack = r#"@prefix ofdd: <urn:openfdd:ns#> .
<urn:pack:vav1> ofdd:equipmentId "VAV_1" ."#;
        let overlay = model_overlay::load_ttl(&root).expect("overlay");
        let store = model_overlay::union_pack_overlay_for_sparql(pack, &overlay).expect("union");
        let hits = store
            .quads_for_pattern(None, None, None, None)
            .filter_map(Result::ok)
            .filter(|q| {
                q.to_string().contains("\"VAV_1\"") && q.to_string().contains("equipmentId")
            })
            .count();
        assert_eq!(hits, 0, "pack copy of a removed equipment is visible");
    }

    #[tokio::test]
    async fn truncated_inventory_never_removes() {
        let dir = tempfile::tempdir().expect("tempdir");
        let root = dir.path().join("SITE_TRUNC");
        apply_to_stores(None, &root, "SITE_TRUNC", SOURCE, &snapshot(V1)).await;
        let mut partial = snapshot(V2);
        partial.complete = false;
        let out = apply_to_stores(None, &root, "SITE_TRUNC", SOURCE, &partial).await;
        let rdf = out.rdf.expect("rdf");
        assert!(rdf.removals_skipped);
        assert!(rdf.equipment_deleted.is_empty());
        assert!(ask(
            &root,
            "SITE_TRUNC",
            r#"ASK { ?s ofdd:equipmentId "VAV_1" }"#
        ));
    }

    fn lab_site() -> SiteConfig {
        let scope = ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        };
        let model = model_from_point_map(&scope, &[]).expect("empty model");
        SiteConfig {
            building_id: "site-a".into(),
            tenant_id: "tenant-a".into(),
            provider_instance_id: "nf:conn-a".into(),
            kind: crate::providers::types::ProviderKind::Nf,
            endpoint: "http://127.0.0.1".into(),
            client_id: None,
            client_secret: None,
            anonymous: true,
            transport: crate::providers::config::SiteTransport::Rest,
            poll_secs: 300,
            latitude: None,
            longitude: None,
            schedule: crate::ingest_queue::schedule::IngestSchedule::Periodic,
            resolver: crate::providers::map::RoleResolver::default(),
            model,
        }
    }

    fn scheduled(runtime: &crate::providers::Runtime) -> (String, Vec<String>, Vec<String>) {
        let models = runtime.models.lock().unwrap_or_else(|err| err.into_inner());
        let revision = models
            .active_revision("tenant-a", "site-a")
            .unwrap_or("")
            .to_string();
        let Some(plan) = models.active_plan("tenant-a", "site-a") else {
            return (revision, Vec::new(), Vec::new());
        };
        let devices = crate::providers::committed_model::schedule_plan_devices(
            "tenant-a",
            "site-a",
            "nf:conn-a",
            plan,
        )
        .expect("schedule");
        let mut device_ids: Vec<String> = devices.into_iter().map(|d| d.equipment_id).collect();
        device_ids.sort();
        let mut point_ids: Vec<String> = plan
            .groups
            .iter()
            .flat_map(|group| group.points.iter().map(|pt| pt.source_point_id.clone()))
            .collect();
        point_ids.sort();
        (revision, device_ids, point_ids)
    }

    /// Clears the process-wide historian env for this test, then restores it.
    struct ClearedHistorian {
        historian: Option<String>,
        database: Option<String>,
    }

    impl ClearedHistorian {
        fn off() -> Self {
            let historian = std::env::var("OPENFDD_HISTORIAN").ok();
            let database = std::env::var("OPENFDD_DATABASE_URL").ok();
            std::env::remove_var("OPENFDD_HISTORIAN");
            std::env::remove_var("OPENFDD_DATABASE_URL");
            Self {
                historian,
                database,
            }
        }
    }

    impl Drop for ClearedHistorian {
        fn drop(&mut self) {
            match self.historian.take() {
                Some(value) => std::env::set_var("OPENFDD_HISTORIAN", value),
                None => std::env::remove_var("OPENFDD_HISTORIAN"),
            }
            match self.database.take() {
                Some(value) => std::env::set_var("OPENFDD_DATABASE_URL", value),
                None => std::env::remove_var("OPENFDD_DATABASE_URL"),
            }
        }
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_HISTORIAN is process-global while this plan is activated"
    )]
    async fn incomplete_inventory_keeps_the_last_plan_across_restart() {
        let _lock = crate::test_env_lock::lock_env();
        let _historian = ClearedHistorian::off();
        let bodies = crate::providers::nf::synthetic_inventory_bodies(501, 500);
        let owned: Vec<&str> = bodies.iter().map(String::as_str).collect();
        let full = crate::providers::nf::assemble_inventory_pages(&owned, 500).expect("501");
        assert!(full.complete);
        assert_eq!(full.points.len(), 501);

        let dir = tempfile::tempdir().expect("tempdir");
        let root = dir.path().join("site-a");
        let runtime = crate::providers::Runtime::health_only_for_test("site-a");
        let cache = crate::haystack_rdf::HaystackRdfCache::new();
        let site = lab_site();
        let first = apply_at(&runtime, &cache, &site, &root, &full).await;
        assert!(first.model_activated, "{:?}", first.errors);
        assert!(!first.plan_retained);
        assert!(!first.degraded, "{:?}", first.errors);
        let (revision, devices, points) = scheduled(&runtime);
        assert!(devices.iter().any(|id| id == "EQ_FINAL"), "{devices:?}");
        assert_eq!(points.len(), 501);
        assert_eq!(points[0], "pt-0000");
        assert_eq!(points[500], "pt-0500");

        let restarted = crate::providers::Runtime::health_only_for_test("site-a");
        {
            let mut models = restarted
                .models
                .lock()
                .unwrap_or_else(|err| err.into_inner());
            let restored = restore_last_good_plan(
                &mut models,
                &root,
                &ModelScope {
                    tenant_id: "tenant-a".into(),
                    site_id: "site-a".into(),
                    provider_instance_id: "nf-conn-a".into(),
                },
            )
            .expect("restore");
            assert!(restored);
        }
        let (restored_rev, restored_devices, restored_points) = scheduled(&restarted);
        assert_eq!(restored_rev, revision);
        assert_eq!(restored_devices, devices);
        assert_eq!(restored_points, points);

        let unspecified =
            crate::providers::nf::assemble_inventory_pages(&[r#"{"points":[]}"#], 500)
                .expect("empty");
        assert!(!unspecified.complete);
        let kept = apply_at(&restarted, &cache, &site, &root, &unspecified).await;
        assert!(kept.plan_retained);
        assert!(kept.degraded);
        assert!(!kept.model_activated);
        assert_eq!(scheduled(&restarted).0, revision);
        assert_eq!(scheduled(&restarted).2.len(), 501);

        let interrupted =
            crate::providers::nf::assemble_inventory_pages(&[&bodies[0]], 500).expect("page 1");
        assert!(!interrupted.complete);
        assert!(!interrupted
            .points
            .iter()
            .any(|pt| pt.equipment_id == "EQ_FINAL"));
        let still = apply_at(&restarted, &cache, &site, &root, &interrupted).await;
        assert!(still.plan_retained);
        assert_eq!(still.diagnostics.reason.as_deref(), Some("truncated"));
        let (_, devices_after, points_after) = scheduled(&restarted);
        assert!(devices_after.iter().any(|id| id == "EQ_FINAL"));
        assert_eq!(points_after, points);

        let empty = crate::providers::nf::assemble_inventory_pages(
            &[&crate::providers::nf::synthetic_inventory_bodies(0, 500)[0]],
            500,
        )
        .expect("empty complete");
        assert!(empty.complete);
        let cleared = apply_at(&restarted, &cache, &site, &root, &empty).await;
        assert!(cleared.model_activated, "{:?}", cleared.errors);
        assert!(!cleared.plan_retained);
        assert!(scheduled(&restarted).1.is_empty());
        assert!(scheduled(&restarted).2.is_empty());

        let after_clear = crate::providers::Runtime::health_only_for_test("site-a");
        {
            let mut models = after_clear
                .models
                .lock()
                .unwrap_or_else(|err| err.into_inner());
            assert!(restore_last_good_plan(
                &mut models,
                &root,
                &ModelScope {
                    tenant_id: "tenant-a".into(),
                    site_id: "site-a".into(),
                    provider_instance_id: "nf-conn-a".into(),
                },
            )
            .expect("restore empty"));
        }
        assert!(scheduled(&after_clear).1.is_empty());
        assert!(scheduled(&after_clear).2.is_empty());
        assert!(scheduled(&after_clear).0 != revision);
    }

    #[test]
    fn bootstrap_points_build_an_ingest_model() {
        let snap = snapshot(V1);
        let scope = ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        };
        let model = model_from_point_map(&scope, &bootstrap_points(&snap)).expect("model");
        assert_eq!(model.equipment.len(), 2);
    }

    #[tokio::test]
    async fn engineer_overlay_merged_into_committed_model_after_sync() {
        use crate::providers::committed_model::{
            apply_engineer_point_overlays, model_from_point_map,
        };
        let dir = tempfile::tempdir().expect("tempdir");
        let root = dir.path().join("SITE_OVL");
        let snap = snapshot(V1);
        let pid = "6a1f0c2a-0001-4000-8000-00000000a001";
        apply_to_stores(None, &root, "SITE_OVL", SOURCE, &snap).await;
        model_overlay::upsert_engineer_point_overlay(
            &root,
            "SITE_OVL",
            pid,
            model_overlay::EngineerPointOverlayPatch {
                unit: Some("degF"),
                quantity: Some("absolute_temperature"),
                cadence_secs: None,
                primary_reference: None,
            },
            false,
        )
        .expect("engineer");
        let scope = ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        };
        let mut model = model_from_point_map(&scope, &bootstrap_points(&snap)).expect("model");
        apply_engineer_point_overlays(&root, "SITE_OVL", &mut model).expect("merge");
        let sat = model
            .equipment
            .iter()
            .flat_map(|eq| eq.points.iter())
            .find(|pt| pt.provider_point_id == pid)
            .expect("sat");
        assert_eq!(sat.unit.as_deref(), Some("degF"));
        assert_eq!(sat.quantity.as_deref(), Some("absolute_temperature"));
        apply_to_stores(None, &root, "SITE_OVL", SOURCE, &snap).await;
        let mut again = model_from_point_map(&scope, &bootstrap_points(&snap)).expect("model");
        apply_engineer_point_overlays(&root, "SITE_OVL", &mut again).expect("merge");
        assert_eq!(again.equipment[0].points[0].unit.as_deref(), Some("degF"));
    }
}

#[cfg(test)]
#[path = "t1406_2_overlay_point_map_test.rs"]
mod t1406_2_overlay_point_map_test;

#[cfg(test)]
#[path = "t1406_schema_upgrade_test.rs"]
mod t1406_schema_upgrade_test;

#[cfg(test)]
#[path = "t1406_binding_resolution_test.rs"]
mod t1406_binding_resolution_test;
