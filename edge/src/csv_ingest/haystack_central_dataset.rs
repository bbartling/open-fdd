//! Central scoped Haystack RDF dataset (C4 / #1002 / #1123 H8).
//!
//! Derives an immutable snapshot from committed `openfdd_semantic_meta_v1`
//! authority + pinned Project Haystack defs. This is **not** the legacy
//! `edge/src/model` commissioning graph (`https://open-fdd.dev/model#`).
//! SPARQL templates → typed bindings ship in C4 H9 (`haystack_sparql_bindings`);
//! graph-driven FDD/ECM consumers remain later tips before #1002 closes.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::haystack_defs::{self, DEFS_PIN};
use super::haystack_projection::{self, ProjectionReport, PROFILE};
use super::semantic_meta::SemanticMetaV1;

pub const DATASET_SCHEMA: &str = "ofdd_haystack_central_dataset_v1";
pub const AUTHORITY: &str = "openfdd_semantic_meta_v1";
pub const GRAPH_KIND: &str = "central_package_scoped_rdf";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CentralDatasetSnapshot {
    pub schema: String,
    pub graph_kind: String,
    pub authority: String,
    pub profile: String,
    pub defs_pin: String,
    pub defs_sha256: String,
    pub building_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_revision: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub equipment_scope: Option<String>,
    pub turtle_sha256: String,
    pub turtle: String,
    pub report: ProjectionReport,
    /// Explicit honesty: legacy edge model SPARQL must not be claimed as this dataset.
    pub not_edge_prototype_graph: bool,
}

impl CentralDatasetSnapshot {
    pub fn cache_key(&self) -> String {
        format!(
            "{}|{}|{}|{}|{}",
            self.building_id,
            self.model_revision.as_deref().unwrap_or(""),
            self.equipment_scope.as_deref().unwrap_or(""),
            self.defs_pin,
            self.turtle_sha256
        )
    }

    pub fn to_json(&self, include_turtle: bool) -> Value {
        let mut v = json!({
            "ok": true,
            "schema": self.schema,
            "graph_kind": self.graph_kind,
            "authority": self.authority,
            "profile": self.profile,
            "defs_pin": self.defs_pin,
            "defs_sha256": self.defs_sha256,
            "building_id": self.building_id,
            "model_revision": self.model_revision,
            "equipment_scope": self.equipment_scope,
            "turtle_sha256": self.turtle_sha256,
            "report": self.report,
            "not_edge_prototype_graph": self.not_edge_prototype_graph,
            "sparql_status": "AVAILABLE",
            "sparql_note": "POST /api/model/sparql with query_id from GET /api/model/sparql/predefined (C4 H9 typed bindings)",
        });
        if include_turtle {
            v["turtle"] = json!(self.turtle);
        }
        v
    }
}

fn turtle_sha256(turtle: &str) -> String {
    let mut h = Sha256::new();
    h.update(turtle.as_bytes());
    format!("{:x}", h.finalize())
}

/// Materialize a central scoped RDF dataset from committed native metadata.
pub fn materialize(
    meta: &SemanticMetaV1,
    inventory: Option<&Value>,
    equipment_scope: Option<&str>,
) -> Result<CentralDatasetSnapshot, String> {
    let projected = haystack_projection::project_strict(meta, inventory);
    if projected
        .report
        .omitted
        .iter()
        .any(|o| o.reason == "projection_error")
    {
        let detail = projected
            .report
            .omitted
            .iter()
            .find(|o| o.reason == "projection_error")
            .and_then(|o| o.detail.clone())
            .unwrap_or_else(|| "projection failed".into());
        return Err(detail);
    }
    if projected.turtle.trim().is_empty() {
        return Err("central dataset projection produced empty Turtle".into());
    }
    let defs = haystack_defs::defs();
    Ok(CentralDatasetSnapshot {
        schema: DATASET_SCHEMA.to_string(),
        graph_kind: GRAPH_KIND.to_string(),
        authority: AUTHORITY.to_string(),
        profile: PROFILE.to_string(),
        defs_pin: DEFS_PIN.to_string(),
        defs_sha256: defs.sha256.clone(),
        building_id: projected.report.building_id.clone(),
        model_revision: meta.revision.clone(),
        equipment_scope: equipment_scope
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        turtle_sha256: turtle_sha256(&projected.turtle),
        turtle: projected.turtle,
        report: projected.report,
        not_edge_prototype_graph: true,
    })
}

/// Legacy Option-B honesty payload (kept for regression tests; routes now use H9 catalog).
pub fn sparql_unavailable_payload() -> Value {
    json!({
        "ok": false,
        "status": "UNAVAILABLE",
        "capability": "central_package_sparql",
        "feature_closeable_by_unavailable": false,
        "error": "Legacy Option B payload — product path is GET/POST /api/model/sparql (H9 templates).",
        "dataset_route": "/api/csv/import/package/mapping/haystack-dataset",
        "authority": AUTHORITY,
        "defs_pin": DEFS_PIN,
        "not_edge_prototype_graph": true,
        "legacy_edge_note": "edge/src/model SPARQL over https://open-fdd.dev/model# is not the package dataset",
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::csv_ingest::haystack_projection::fixtures::{sample_inventory, sample_meta};
    use crate::csv_ingest::semantic_meta::scope_meta;

    #[test]
    fn materialize_uses_authority_and_pinned_defs() {
        let snap = materialize(&sample_meta(), Some(&sample_inventory()), None).expect("snap");
        assert_eq!(snap.schema, DATASET_SCHEMA);
        assert_eq!(snap.authority, AUTHORITY);
        assert_eq!(snap.defs_pin, DEFS_PIN);
        assert!(snap.not_edge_prototype_graph);
        assert!(!snap.turtle_sha256.is_empty());
        assert!(snap.turtle.contains("urn:openfdd:site/"));
        assert!(!snap.turtle.contains("https://open-fdd.dev/model#"));
        assert_eq!(snap.report.emitted_equips, 3);
    }

    #[test]
    fn equipment_scope_shrinks_dataset() {
        let full = materialize(&sample_meta(), Some(&sample_inventory()), None).expect("full");
        let scoped_meta = scope_meta(&sample_meta(), Some("AHU_CASE_1")).expect("scope");
        let scoped = materialize(&scoped_meta, Some(&sample_inventory()), Some("AHU_CASE_1"))
            .expect("scoped");
        assert_eq!(scoped.equipment_scope.as_deref(), Some("AHU_CASE_1"));
        assert!(scoped.report.emitted_equips < full.report.emitted_equips);
        assert_ne!(scoped.turtle_sha256, full.turtle_sha256);
    }

    #[test]
    fn sparql_unavailable_cannot_close_feature() {
        let body = sparql_unavailable_payload();
        assert_eq!(body["status"], "UNAVAILABLE");
        assert_eq!(body["feature_closeable_by_unavailable"], false);
        assert_eq!(body["not_edge_prototype_graph"], true);
    }
}
