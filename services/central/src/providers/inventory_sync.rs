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
//! A snapshot that may be truncated (a full page) is applied without step 2
//! or the RDF removals. Nothing here deletes samples or `point_map` rows.

use std::collections::BTreeMap;
use std::path::Path;

use fdd_tsdb::{PortalInventoryPoint, PortalInventoryReport, Tsdb};
use open_fdd_edge_prototype::csv_ingest::model_overlay::{
    self, PortalEquip, PortalPoint, PortalSyncReport,
};
use open_fdd_edge_prototype::csv_ingest::semantic_selector;
use serde::Serialize;
use tracing::{debug, warn};

use super::committed_model::{model_from_point_map, BootstrapPoint, ModelScope};
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

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InventorySnapshot {
    pub points: Vec<InventoryPoint>,
    /// Points the portal returned, tagged or not.
    pub source_points: usize,
    /// False when the response may be truncated or carried no points at all.
    pub complete: bool,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct InventorySyncOutcome {
    pub historian: Option<PortalInventoryReport>,
    pub rdf: Option<PortalSyncReport>,
    pub model_activated: bool,
    pub errors: Vec<String>,
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

pub fn historian_rows(snapshot: &InventorySnapshot) -> Vec<PortalInventoryPoint> {
    snapshot
        .points
        .iter()
        .map(|pt| PortalInventoryPoint {
            portal_point_id: pt.portal_point_id.clone(),
            equipment_id: pt.equipment_id.clone(),
            equip_type: pt.equip_type.clone(),
            role: pt.role.clone(),
            unit: pt.unit.clone(),
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
        match tsdb
            .sync_portal_inventory(
                building_id,
                provider_instance_id,
                &historian_rows(snapshot),
                snapshot.complete,
            )
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
    let tsdb = if crate::timescale_historian::historian_is_timescale() {
        match Tsdb::shared().await {
            Ok(tsdb) => Some(tsdb),
            Err(err) => {
                warn!(building_id = %site.building_id, error = %err, "portal inventory: historian unavailable");
                let mut outcome = InventorySyncOutcome::default();
                outcome.errors.push("historian_unavailable".into());
                return outcome;
            }
        }
    } else {
        None
    };
    let root = open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(&site.building_id);
    let mut outcome = apply_to_stores(
        tsdb.as_deref(),
        &root,
        &site.building_id,
        &site.provider_instance_id,
        snapshot,
    )
    .await;
    if outcome.rdf.as_ref().is_some_and(|r| r.changed) {
        rdf_cache.invalidate_building(&site.building_id);
    }
    let entries = bootstrap_points(snapshot);
    if !entries.is_empty() && outcome.errors.is_empty() {
        // The historian keeps the connection id (`nf:…`). The plan slug drops
        // colons; using the connection id here fails validation and leaves
        // the startup plan unmatched.
        let scope = ModelScope {
            tenant_id: site.tenant_id.clone(),
            site_id: site.building_id.clone(),
            provider_instance_id: site.model.provider_instance_id.clone(),
        };
        match model_from_point_map(&scope, &entries) {
            Ok(model) => {
                let mut models = runtime.models.lock().unwrap_or_else(|e| e.into_inner());
                match models.try_activate(None, &model) {
                    Ok(report) => {
                        debug!(building_id = %site.building_id, revision = %report.revision_id, "portal inventory plan active");
                        outcome.model_activated = true;
                    }
                    Err(err) => {
                        warn!(building_id = %site.building_id, error = %err, "portal inventory plan did not activate");
                        outcome.errors.push("plan_not_activated".into());
                    }
                }
            }
            Err(err) => {
                warn!(building_id = %site.building_id, error = %err, "portal inventory plan invalid");
                outcome.errors.push("plan_invalid".into());
            }
        }
    }
    outcome
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
}
