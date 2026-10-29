//! Central package Haystack RDF dataset cache + SPARQL bindings (C4 H8/H9).
//!
//! Materializes scoped RDF from committed `semantic_meta` + pinned defs.
//! Does **not** use the legacy `edge/src/model` commissioning graph.

use std::sync::Arc;

use dashmap::DashMap;
use open_fdd_edge_prototype::csv_ingest::haystack_binding_consumers;
use open_fdd_edge_prototype::csv_ingest::haystack_central_dataset::{self, CentralDatasetSnapshot};
use open_fdd_edge_prototype::csv_ingest::haystack_sparql_bindings;
use open_fdd_edge_prototype::csv_ingest::semantic_meta;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Clone, Default)]
pub struct HaystackRdfCache {
    by_key: Arc<DashMap<String, CentralDatasetSnapshot>>,
}

impl HaystackRdfCache {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get_or_materialize(
        &self,
        building_id: &str,
        equipment_id: Option<&str>,
        preferred_tenant: Option<&str>,
    ) -> Result<CentralDatasetSnapshot, Value> {
        self.get_or_materialize_with_inventory(building_id, equipment_id, preferred_tenant)
            .map(|(snap, _)| snap)
    }

    pub fn get_or_materialize_with_inventory(
        &self,
        building_id: &str,
        equipment_id: Option<&str>,
        preferred_tenant: Option<&str>,
    ) -> Result<(CentralDatasetSnapshot, Value), Value> {
        let root = open_fdd_edge_prototype::historian::store::workspace_dir()
            .join("data")
            .join("csv_buildings")
            .join(building_id);
        let meta = match semantic_meta::load_persisted(&root) {
            Ok(Some(m)) => m,
            Ok(None) => {
                return Err(json!({
                    "ok": false,
                    "error": "semantic_meta.json not present for building — central Haystack dataset requires native metadata (C2)",
                    "present": false,
                    "schema": haystack_central_dataset::DATASET_SCHEMA,
                }));
            }
            Err(e) => return Err(json!({"ok": false, "error": e})),
        };
        let scoped = match semantic_meta::scope_meta(&meta, equipment_id) {
            Ok(m) => m,
            Err(e) => {
                return Err(json!({
                    "ok": false,
                    "error": e,
                    "incomplete": true,
                    "schema": haystack_central_dataset::DATASET_SCHEMA,
                }));
            }
        };
        let inventory =
            open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler_scoped(
                building_id,
                equipment_id,
                preferred_tenant,
            );
        if inventory.get("ok").and_then(|v| v.as_bool()) == Some(false) {
            return Err(json!({
                "ok": false,
                "error": inventory.get("error").cloned().unwrap_or_else(|| json!("inventory unavailable for scoped Haystack dataset")),
                "incomplete": true,
                "inventory": inventory,
                "schema": haystack_central_dataset::DATASET_SCHEMA,
            }));
        }

        // Inventory + preferred tenant change Turtle (ambiguous roles, exclusions, parent_ahu).
        let inventory_token = inventory_cache_token(&inventory, preferred_tenant);
        let provisional_key = format!(
            "{}|{}|{}|{}|{}",
            building_id,
            scoped.revision.as_deref().unwrap_or(""),
            equipment_id.unwrap_or(""),
            open_fdd_edge_prototype::csv_ingest::haystack_defs::DEFS_PIN,
            inventory_token
        );
        if let Some(hit) = self.by_key.get(&provisional_key) {
            return Ok((hit.clone(), inventory));
        }

        let snap = haystack_central_dataset::materialize(&scoped, Some(&inventory), equipment_id)
            .map_err(|e| json!({"ok": false, "error": e}))?;

        // Index by both provisional and full cache key (includes turtle hash).
        self.by_key.insert(provisional_key, snap.clone());
        self.by_key.insert(snap.cache_key(), snap.clone());
        Ok((snap, inventory))
    }

    pub fn execute_sparql_template(
        &self,
        building_id: &str,
        equipment_id: Option<&str>,
        preferred_tenant: Option<&str>,
        template_id: &str,
    ) -> Result<Value, Value> {
        let (snap, inventory) =
            self.get_or_materialize_with_inventory(building_id, equipment_id, preferred_tenant)?;
        let overlay = Self::load_overlay_ttl(building_id, equipment_id)?;
        let set = haystack_sparql_bindings::execute_template_on_snapshot_with_overlay(
            &snap,
            Some(&inventory),
            template_id,
            &overlay,
        )
        .map_err(|e| {
            json!({
                "ok": false,
                "error": e,
                "schema": haystack_sparql_bindings::BINDING_SCHEMA,
                "query_engine": haystack_sparql_bindings::QUERY_ENGINE,
            })
        })?;
        let mut body = set.to_json();
        if let Some(obj) = body.as_object_mut() {
            obj.insert("ok".into(), json!(true));
            obj.insert("overlay_union".into(), json!(!overlay.trim().is_empty()));
        }
        Ok(body)
    }

    /// H10/H11: SPARQL typed bindings + FDD/history/ECM consumer plans.
    pub fn execute_binding_consumers(
        &self,
        building_id: &str,
        equipment_id: Option<&str>,
        preferred_tenant: Option<&str>,
        template_id: &str,
    ) -> Result<Value, Value> {
        let (snap, inventory) =
            self.get_or_materialize_with_inventory(building_id, equipment_id, preferred_tenant)?;
        let overlay = Self::load_overlay_ttl(building_id, equipment_id)?;
        let set = haystack_sparql_bindings::execute_template_on_snapshot_with_overlay(
            &snap,
            Some(&inventory),
            template_id,
            &overlay,
        )
        .map_err(|e| {
            json!({
                "ok": false,
                "error": e,
                "schema": haystack_sparql_bindings::BINDING_SCHEMA,
            })
        })?;
        let mut bundle = haystack_binding_consumers::consumer_bundle(&set, Some(&inventory));
        if let Some(obj) = bundle.as_object_mut() {
            obj.insert("bindings".into(), set.to_json());
            obj.insert("overlay_union".into(), json!(!overlay.trim().is_empty()));
        }
        Ok(bundle)
    }

    /// Bounded read-only SELECT/ASK free-form SPARQL (N5).
    /// Soft-OPEN R5: algebra policy (SELECT/ASK, no SERVICE/FROM/Update) runs
    /// **before** Haystack dataset materialize so missing `semantic_meta` does
    /// not mask mutation/federation rejects.
    pub fn execute_readonly_query(
        &self,
        building_id: &str,
        equipment_id: Option<&str>,
        preferred_tenant: Option<&str>,
        query_text: &str,
    ) -> Result<Value, Value> {
        haystack_sparql_bindings::prepare_readonly_query_text(query_text).map_err(|e| {
            json!({
                "ok": false,
                "error": e,
                "schema": haystack_sparql_bindings::READONLY_SCHEMA,
                "soft_open_neq_fq": true,
            })
        })?;
        let overlay = Self::load_overlay_ttl(building_id, equipment_id)?;
        let snap = match self.get_or_materialize_with_inventory(
            building_id,
            equipment_id,
            preferred_tenant,
        ) {
            Ok((snap, _inventory)) => snap,
            Err(err) if err.get("present") == Some(&json!(false)) && !overlay.trim().is_empty() => {
                return haystack_sparql_bindings::execute_readonly_on_overlay(
                    building_id,
                    query_text,
                    &overlay,
                )
                .map_err(|e| {
                    json!({
                        "ok": false,
                        "error": e,
                        "schema": haystack_sparql_bindings::READONLY_SCHEMA,
                    })
                });
            }
            Err(err) => return Err(err),
        };
        haystack_sparql_bindings::execute_readonly_on_snapshot_with_overlay(
            &snap, query_text, &overlay,
        )
        .map_err(|e| {
            json!({
                "ok": false,
                "error": e,
                "schema": haystack_sparql_bindings::READONLY_SCHEMA,
            })
        })
    }

    /// Drop cached snapshots for a building after semantic_meta commit (HR-07).
    pub fn invalidate_building(&self, building_id: &str) {
        let prefix = format!("{building_id}|");
        self.by_key.retain(|k, _| !k.starts_with(&prefix));
    }

    /// Soft-OPEN: load writable overlay TTL for SPARQL pack ∪ overlay.
    ///
    /// Missing overlay file → `Ok("")` (no overlay union). Read/parse/scope failures → `Err`.
    fn load_overlay_ttl(building_id: &str, equipment_id: Option<&str>) -> Result<String, Value> {
        let root = open_fdd_edge_prototype::historian::store::workspace_dir()
            .join("data")
            .join("csv_buildings")
            .join(building_id);
        open_fdd_edge_prototype::csv_ingest::model_overlay::overlay_turtle_for_sparql(
            &root,
            equipment_id,
        )
        .map_err(|e| {
            json!({
                "ok": false,
                "error": e,
                "overlay_error": true,
                "schema": haystack_central_dataset::DATASET_SCHEMA,
            })
        })
    }
}

/// HTTP status for package SPARQL errors (`404` = no native model, `400` = scoped failure).
pub fn sparql_route_status(err: &Value) -> axum::http::StatusCode {
    if err.get("present") == Some(&json!(false)) {
        axum::http::StatusCode::NOT_FOUND
    } else if err.get("overlay_error") == Some(&json!(true)) {
        axum::http::StatusCode::INTERNAL_SERVER_ERROR
    } else {
        axum::http::StatusCode::BAD_REQUEST
    }
}

fn inventory_cache_token(inventory: &Value, preferred_tenant: Option<&str>) -> String {
    let mut h = Sha256::new();
    h.update(preferred_tenant.unwrap_or("").as_bytes());
    h.update(b"|");
    // Stable subset that affects projection output.
    for key in [
        "ambiguous_roles",
        "excluded_columns",
        "parent_ahu",
        "equipment",
        "points",
        "mappings",
        "column_map",
        "equip_types",
        "equipment_types",
    ] {
        if let Some(v) = inventory.get(key) {
            h.update(key.as_bytes());
            h.update(b"=");
            h.update(v.to_string().as_bytes());
            h.update(b";");
        }
    }
    // Fallback: if none of the known keys are present, hash the full inventory.
    if ![
        "ambiguous_roles",
        "excluded_columns",
        "parent_ahu",
        "equipment",
        "points",
        "mappings",
        "column_map",
        "equip_types",
        "equipment_types",
    ]
    .iter()
    .any(|k| inventory.get(*k).is_some())
    {
        h.update(inventory.to_string().as_bytes());
    }
    format!("{:x}", h.finalize())
}

pub fn sparql_catalog() -> Value {
    haystack_sparql_bindings::catalog_payload()
}

pub fn sparql_freeform_rejected() -> Value {
    haystack_sparql_bindings::freeform_rejected()
}

#[cfg(test)]
mod tests {
    use super::*;
    use open_fdd_edge_prototype::csv_ingest::semantic_meta::{persist_atomic, SemanticMetaV1};
    use tempfile::tempdir;

    use crate::test_env_lock::{lock_env, WorkspaceEnv};

    fn synth_meta(building_id: &str) -> SemanticMetaV1 {
        let raw = serde_json::json!({
            "schema": semantic_meta::SCHEMA,
            "building_id": building_id,
            "points": [{
                "equipment_id": "EQ_A",
                "column": "SAT",
                "haystack_tags": ["sensor", "point", "air", "temp"],
                "unit": "°F",
            }],
            "equipment": [{
                "equipment_id": "EQ_A",
                "haystack_tags": ["ahu", "equip"],
            }, {
                "equipment_id": "EQ_B",
                "haystack_tags": ["vav", "equip"],
            }]
        });
        semantic_meta::parse_semantic_meta(&raw).expect("meta")
    }

    #[test]
    fn catalog_is_available_not_option_b() {
        let body = sparql_catalog();
        assert_eq!(body["status"], "AVAILABLE");
        assert_eq!(body["feature_closeable_by_unavailable"], false);
        assert!(body["queries"].as_array().unwrap().len() >= 3);
    }

    #[test]
    fn inventory_token_includes_tenant_and_roles() {
        let a = inventory_cache_token(&json!({"ambiguous_roles": ["x"]}), Some("t1"));
        let b = inventory_cache_token(&json!({"ambiguous_roles": ["x"]}), Some("t2"));
        let c = inventory_cache_token(&json!({"ambiguous_roles": ["y"]}), Some("t1"));
        assert_ne!(a, b);
        assert_ne!(a, c);
    }

    #[test]
    fn sparql_route_status_maps_missing_meta_to_404() {
        let missing = json!({"present": false, "error": "no meta"});
        assert_eq!(
            sparql_route_status(&missing),
            axum::http::StatusCode::NOT_FOUND
        );
        let scoped = json!({"incomplete": true, "error": "equipment missing"});
        assert_eq!(
            sparql_route_status(&scoped),
            axum::http::StatusCode::BAD_REQUEST
        );
        let overlay = json!({"overlay_error": true, "error": "load overlay turtle: bad"});
        assert_eq!(
            sparql_route_status(&overlay),
            axum::http::StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    #[test]
    fn execute_sparql_template_errors_for_missing_meta_and_unknown_equipment() {
        let _guard = lock_env();
        let dir = tempdir().expect("tempdir");
        let _ws = WorkspaceEnv::set(dir.path());
        let bid = "T1441_SPARQL_SCOPE";
        let root = dir.path().join("data").join("csv_buildings").join(bid);
        std::fs::create_dir_all(&root).expect("mkdir");
        let cache = HaystackRdfCache::new();
        let missing = cache
            .execute_sparql_template(bid, None, None, "fdd_role_candidates")
            .unwrap_err();
        assert_eq!(missing.get("present"), Some(&json!(false)));
        assert_eq!(
            sparql_route_status(&missing),
            axum::http::StatusCode::NOT_FOUND
        );

        persist_atomic(&root, synth_meta(bid), None).expect("persist");
        let unknown = cache
            .execute_sparql_template(bid, Some("EQ_MISSING"), None, "fdd_role_candidates")
            .unwrap_err();
        assert_eq!(unknown.get("incomplete"), Some(&json!(true)));
        assert_eq!(
            sparql_route_status(&unknown),
            axum::http::StatusCode::BAD_REQUEST
        );
    }

    #[test]
    fn corrupt_overlay_ttl_maps_to_overlay_error_and_500_status() {
        let _guard = lock_env();
        let dir = tempdir().expect("tempdir");
        let _ws = WorkspaceEnv::set(dir.path());
        let bid = "T1441_CORRUPT_OVERLAY";
        let root = dir.path().join("data").join("csv_buildings").join(bid);
        std::fs::create_dir_all(&root).expect("mkdir");
        std::fs::write(
            root.join(open_fdd_edge_prototype::csv_ingest::model_overlay::OVERLAY_TTL_FILE),
            "@prefix x: . x:not valid turtle {{{",
        )
        .expect("write corrupt overlay");
        let parse = open_fdd_edge_prototype::csv_ingest::model_overlay::overlay_turtle_for_sparql(
            &root,
            Some("EQ_A"),
        );
        let msg = parse.expect_err("scoped overlay must fail turtle parse");
        let body = json!({
            "ok": false,
            "error": msg,
            "overlay_error": true,
        });
        assert_eq!(
            sparql_route_status(&body),
            axum::http::StatusCode::INTERNAL_SERVER_ERROR
        );
    }
}
