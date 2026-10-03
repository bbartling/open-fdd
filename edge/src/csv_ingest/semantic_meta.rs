//! Versioned native semantic metadata for Haystack RDF C2 (#1000).
//!
//! Schema `openfdd_semantic_meta_v1` persists point tags/units/refs/provenance and
//! optional engineering quantities so C3 can project to Project Haystack RDF.
//! Old packages without this sidecar keep prior FDD/analytics meaning (HR-01).
//! Custom Open-FDD fields stay engineering-only — Haystack tags are preferred.

use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub const SCHEMA: &str = "openfdd_semantic_meta_v1";
/// Accepted C1 sketch schema — upgraded on load, never fabricated for old ZIPs.
pub const SKETCH_SCHEMA: &str = "openfdd_point_metadata_v1_sketch";
pub const SEMANTIC_META_FILE: &str = "semantic_meta.json";
pub const SEMANTIC_META_REVISION_FILE: &str = "semantic_meta.revision.json";
/// Package path aliases (building-root relative).
pub const PACKAGE_CANDIDATES: &[&str] = &[
    "semantic_meta.json",
    "openfdd_semantic_meta_v1.json",
    "point_metadata.json",
    "openfdd_point_metadata_v1.json",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SemanticMetaV1 {
    pub schema: String,
    pub building_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revision: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default)]
    pub points: Vec<PointMeta>,
    #[serde(default)]
    pub equipment: Vec<EquipmentMeta>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub engineering_quantities: Option<Vec<EngineeringQuantity>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PointMeta {
    pub equipment_id: String,
    pub column: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub haystack_tags: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit_source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit_status: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_equip: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EquipmentMeta {
    pub equipment_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub haystack_tags: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub site_ref: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_equip: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EngineeringQuantity {
    pub equipment_id: String,
    pub kind: String,
    pub value: f64,
    pub unit: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub basis: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub review: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SemanticMetaRevision {
    pub schema: String,
    pub building_id: String,
    pub revision: String,
    pub content_sha256: String,
}

fn atomic_write(path: &Path, body: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    let tmp = path.with_extension("json.tmp");
    {
        let mut f = fs::File::create(&tmp).map_err(|e| format!("create tmp: {e}"))?;
        f.write_all(body.as_bytes())
            .map_err(|e| format!("write tmp: {e}"))?;
        f.sync_all().map_err(|e| format!("sync tmp: {e}"))?;
    }
    fs::rename(&tmp, path).map_err(|e| format!("rename {}: {e}", path.display()))?;
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

/// Parse + validate. Upgrades C1 sketch schema to `openfdd_semantic_meta_v1`.
pub fn parse_semantic_meta(raw: &Value) -> Result<SemanticMetaV1, String> {
    let schema = raw
        .get("schema")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if schema != SCHEMA && schema != SKETCH_SCHEMA {
        return Err(format!(
            "unsupported semantic meta schema {schema:?}; expected {SCHEMA} or {SKETCH_SCHEMA}"
        ));
    }
    let building_id = raw
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "semantic meta building_id required".to_string())?
        .to_string();

    let mut meta: SemanticMetaV1 =
        serde_json::from_value(raw.clone()).map_err(|e| format!("semantic meta parse: {e}"))?;
    meta.schema = SCHEMA.to_string();
    meta.building_id = building_id;

    // Identity hygiene (HR-02): reject empty equipment/column ids.
    for (i, p) in meta.points.iter().enumerate() {
        if p.equipment_id.trim().is_empty() || p.column.trim().is_empty() {
            return Err(format!(
                "semantic meta points[{i}]: equipment_id and column required"
            ));
        }
    }
    for (i, e) in meta.equipment.iter().enumerate() {
        if e.equipment_id.trim().is_empty() {
            return Err(format!(
                "semantic meta equipment[{i}]: equipment_id required"
            ));
        }
    }
    Ok(meta)
}

pub fn find_package_semantic_meta(
    in_building: &BTreeMap<PathBuf, &Vec<u8>>,
) -> Option<Result<SemanticMetaV1, String>> {
    for name in PACKAGE_CANDIDATES {
        if let Some(bytes) = in_building.get(Path::new(name)) {
            let raw: Value = match serde_json::from_slice(bytes) {
                Ok(v) => v,
                Err(e) => return Some(Err(format!("{name}: {e}"))),
            };
            return Some(parse_semantic_meta(&raw));
        }
    }
    None
}

pub fn building_meta_path(building_root: &Path) -> PathBuf {
    building_root.join(SEMANTIC_META_FILE)
}

pub fn building_revision_path(building_root: &Path) -> PathBuf {
    building_root.join(SEMANTIC_META_REVISION_FILE)
}

pub fn load_persisted(building_root: &Path) -> Result<Option<SemanticMetaV1>, String> {
    let path = building_meta_path(building_root);
    if !path.is_file() {
        return Ok(None);
    }
    let body = fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let raw: Value =
        serde_json::from_str(&body).map_err(|e| format!("parse {}: {e}", path.display()))?;
    Ok(Some(parse_semantic_meta(&raw)?))
}

/// Atomically persist meta + revision. On conflict (`expected_revision` set and
/// mismatches disk), returns Err without writing (HR-07).
pub fn persist_atomic(
    building_root: &Path,
    mut meta: SemanticMetaV1,
    expected_revision: Option<&str>,
) -> Result<SemanticMetaRevision, String> {
    let rev_path = building_revision_path(building_root);
    if let Some(want) = expected_revision {
        if rev_path.is_file() {
            let cur = fs::read_to_string(&rev_path).map_err(|e| format!("read revision: {e}"))?;
            let cur_rev: SemanticMetaRevision =
                serde_json::from_str(&cur).map_err(|e| format!("parse revision: {e}"))?;
            if cur_rev.revision != want {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have {}",
                    cur_rev.revision
                ));
            }
        } else if !want.is_empty() {
            return Err(format!(
                "semantic meta revision conflict: expected {want}, have none"
            ));
        }
    }

    let next_rev = format!("r{}", chrono_lite_now_ms());
    meta.revision = Some(next_rev.clone());
    let body = serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?;
    let body = format!("{body}\n");
    let digest = sha256_hex(body.as_bytes());
    let rev = SemanticMetaRevision {
        schema: SCHEMA.to_string(),
        building_id: meta.building_id.clone(),
        revision: next_rev,
        content_sha256: digest,
    };
    let rev_body = serde_json::to_string_pretty(&rev).map_err(|e| e.to_string())?;
    let rev_body = format!("{rev_body}\n");

    // Write meta first to tmp+rename, then revision — if revision fails, meta tip
    // still has embedded revision field matching intended next_rev.
    atomic_write(&building_meta_path(building_root), &body)?;
    atomic_write(&rev_path, &rev_body)?;
    Ok(rev)
}

fn chrono_lite_now_ms() -> u128 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// Import helper: persist package sidecar or leave prior revision intact on error.
pub fn import_from_package_map(
    building_root: &Path,
    building_id: &str,
    in_building: &BTreeMap<PathBuf, &Vec<u8>>,
    warnings: &mut Vec<String>,
) -> Value {
    match find_package_semantic_meta(in_building) {
        None => json!({
            "ok": true,
            "present": false,
            "schema": SCHEMA,
        }),
        Some(Err(e)) => {
            warnings.push(format!(
                "semantic_meta rejected (prior revision kept if any): {e}"
            ));
            json!({
                "ok": false,
                "present": true,
                "error": e,
                "prior_intact": building_meta_path(building_root).is_file(),
            })
        }
        Some(Ok(mut meta)) => {
            if meta.building_id != building_id {
                warnings.push(format!(
                    "semantic_meta building_id {} overridden by package {}",
                    meta.building_id, building_id
                ));
                meta.building_id = building_id.to_string();
            }
            match persist_atomic(building_root, meta, None) {
                Ok(rev) => json!({
                    "ok": true,
                    "present": true,
                    "schema": SCHEMA,
                    "revision": rev.revision,
                    "content_sha256": rev.content_sha256,
                }),
                Err(e) => {
                    warnings.push(format!("semantic_meta persist failed: {e}"));
                    json!({"ok": false, "present": true, "error": e})
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn sample_raw() -> Value {
        json!({
            "schema": SKETCH_SCHEMA,
            "building_id": "SITE_A",
            "points": [{
                "equipment_id": "AHU_1",
                "column": "SAT",
                "haystack_tags": ["sensor", "point", "air", "temp"],
                "unit": "°F",
                "unit_source": "package_map"
            }],
            "equipment": [{
                "equipment_id": "AHU_1",
                "haystack_tags": ["ahu", "equip"],
                "display_name": "AHU 1"
            }]
        })
    }

    #[test]
    fn upgrades_c1_sketch_and_roundtrips() {
        let meta = parse_semantic_meta(&sample_raw()).unwrap();
        assert_eq!(meta.schema, SCHEMA);
        assert_eq!(meta.points.len(), 1);
        let dir = tempdir().unwrap();
        let rev = persist_atomic(dir.path(), meta.clone(), None).unwrap();
        let loaded = load_persisted(dir.path()).unwrap().unwrap();
        assert_eq!(loaded.schema, SCHEMA);
        assert_eq!(loaded.points[0].column, "SAT");
        assert_eq!(loaded.revision.as_deref(), Some(rev.revision.as_str()));
    }

    #[test]
    fn invalid_meta_leaves_prior_intact() {
        let dir = tempdir().unwrap();
        let meta = parse_semantic_meta(&sample_raw()).unwrap();
        persist_atomic(dir.path(), meta, None).unwrap();
        let prior = fs::read_to_string(building_meta_path(dir.path())).unwrap();

        let bad = json!({"schema": "not_a_schema", "building_id": "SITE_A"});
        assert!(parse_semantic_meta(&bad).is_err());
        // Simulate import reject: do not call persist
        let after = fs::read_to_string(building_meta_path(dir.path())).unwrap();
        assert_eq!(prior, after);
    }

    #[test]
    fn revision_conflict_is_explicit() {
        let dir = tempdir().unwrap();
        let meta = parse_semantic_meta(&sample_raw()).unwrap();
        let rev = persist_atomic(dir.path(), meta.clone(), None).unwrap();
        let err = persist_atomic(dir.path(), meta, Some("wrong-rev")).unwrap_err();
        assert!(err.contains("conflict"), "{err}");
        assert!(err.contains(&rev.revision) || err.contains("wrong-rev"));
    }

    #[test]
    fn rejects_empty_point_identity() {
        let raw = json!({
            "schema": SCHEMA,
            "building_id": "SITE_A",
            "points": [{"equipment_id": "", "column": "SAT"}]
        });
        assert!(parse_semantic_meta(&raw).is_err());
    }
}
