//! H12 integration KATs — ZIP authority → RDF → SPARQL → typed bindings → FDD plan.
//!
//! Uses committed sample meta/inventory (same fixtures as C3/H8). Negatives cover
//! decoy equipment ids and unbound roles. Dual-tenant ACL remains a live gate-36
//! concern; these unit KATs prove the product graph path without greenwashing.

use serde_json::json;

use super::haystack_binding_consumers::{ecm_binding_plan, fdd_binding_plan, history_binding_plan};
use super::haystack_central_dataset;
use super::haystack_projection::fixtures::{sample_inventory, sample_meta};
use super::haystack_sparql_bindings::{execute_template_from_meta, BINDING_SCHEMA};
use super::semantic_meta::scope_meta;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zip_authority_to_fdd_plan_known_answers() {
        let meta = sample_meta();
        let inv = sample_inventory();
        let snap = haystack_central_dataset::materialize(&meta, Some(&inv), None).expect("dataset");
        assert!(!snap.turtle.is_empty());
        assert!(snap.not_edge_prototype_graph);

        let bindings = execute_template_from_meta(&meta, Some(&inv), None, "fdd_role_candidates")
            .expect("sparql");
        assert_eq!(bindings.schema, BINDING_SCHEMA);
        assert_eq!(bindings.turtle_sha256, snap.turtle_sha256);

        let fdd = fdd_binding_plan(&bindings);
        assert_eq!(fdd["role_map"]["AHU_CASE_1"]["sat"], "SAT");
        assert!(fdd["ready_point_count"].as_u64().unwrap() >= 1);

        // Decoy: opaque rename of equipment id must not invent membership.
        let decoy_ids = fdd["equipment_ids"].as_array().unwrap();
        assert!(!decoy_ids.iter().any(|v| v.as_str() == Some("AHU_DECOY")));
        assert!(!decoy_ids.iter().any(|v| v.as_str() == Some("VAV_1"))); // label ≠ membership

        let ecm = ecm_binding_plan(&bindings);
        assert!(ecm["assets"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["equipment_id"] == "AHU_CASE_1"));
    }

    #[test]
    fn equipment_scope_excludes_other_ahu() {
        let meta = sample_meta();
        let inv = sample_inventory();
        let scoped = scope_meta(&meta, Some("AHU_CASE_1")).expect("scope");
        let bindings = execute_template_from_meta(
            &scoped,
            Some(&inv),
            Some("AHU_CASE_1"),
            "equip_by_ahu_class",
        )
        .expect("scoped sparql");
        let ids: Vec<_> = bindings
            .equipment
            .iter()
            .map(|e| e.equipment_id.as_str())
            .collect();
        assert_eq!(ids, vec!["AHU_CASE_1"]);
    }

    #[test]
    fn corrupting_role_binding_makes_fdd_unready() {
        let meta = sample_meta();
        let mut inv = sample_inventory();
        // Remove approved SAT role — telemetry unchanged, binding unready.
        if let Some(eq) = inv
            .get_mut("equipment")
            .and_then(|v| v.as_array_mut())
            .and_then(|a| a.iter_mut().find(|e| e["equipment_id"] == "AHU_CASE_1"))
        {
            eq["roles"] = json!({});
        }
        let bindings = execute_template_from_meta(&meta, Some(&inv), None, "fdd_role_candidates")
            .expect("sparql");
        let fdd = fdd_binding_plan(&bindings);
        assert!(
            fdd["role_map"]
                .get("AHU_CASE_1")
                .and_then(|v| v.get("sat"))
                .is_none(),
            "SAT must not be FDD-ready without approved inventory role"
        );
    }

    #[test]
    fn history_bind_requires_approved_series() {
        let meta = sample_meta();
        let inv = sample_inventory();
        let bindings = execute_template_from_meta(&meta, Some(&inv), None, "fdd_role_candidates")
            .expect("sparql");
        let hist = history_binding_plan(&bindings, Some(&inv));
        assert_eq!(hist["arbitrary_url_fetch"], false);
        assert!(hist["series"].as_array().unwrap().is_empty());
        assert!(!hist["rejected"].as_array().unwrap().is_empty());
    }
}
