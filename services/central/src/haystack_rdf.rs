//! Central package Haystack RDF dataset cache + SPARQL bindings (C4 H8/H9).
//!
//! Materializes scoped RDF from committed `semantic_meta` + pinned defs.
//! Does **not** use the legacy `edge/src/model` commissioning graph.

use std::sync::Arc;

use dashmap::DashMap;
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
        let set = haystack_sparql_bindings::execute_template_on_snapshot(
            &snap,
            Some(&inventory),
            template_id,
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
        }
        Ok(body)
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
}
