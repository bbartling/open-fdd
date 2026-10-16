//! Soft-OPEN revisioned Turtle overlay store (BPS `PUT /api/model/overlay` shape).
//!
//! Writable sidecar under the CSV building root. Pack RDF / Haystack projection
//! stay immutable. Soft-OPEN ≠ FQ: this store is **not** yet unioned into the
//! SPARQL pack graph and does **not** ship equip/point tombstone CRUD.

use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};

use chrono::Utc;
use oxigraph::io::RdfFormat;
use oxigraph::store::Store;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub const OVERLAY_TTL_FILE: &str = "model_overlay.ttl";
pub const OVERLAY_META_FILE: &str = "model_overlay.meta.json";
pub const OVERLAY_TMP_SUFFIX: &str = ".tmp";
/// BPS-compatible body size cap (chars).
pub const MAX_TTL_CHARS: usize = 2_000_000;
pub const WRITABLE_LAYER: &str = "model_overlay_ttl";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OverlayMeta {
    pub building_id: String,
    pub revision: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ttl_sha256_16: Option<String>,
}

fn ttl_path(building_root: &Path) -> PathBuf {
    building_root.join(OVERLAY_TTL_FILE)
}

fn meta_path(building_root: &Path) -> PathBuf {
    building_root.join(OVERLAY_META_FILE)
}

fn now_rfc3339_z() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn sha256_16(ttl: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(ttl.as_bytes());
    let full = hasher.finalize();
    hex::encode(&full[..8])
}

/// Validate Turtle by loading into an ephemeral oxigraph store.
pub fn validate_turtle(ttl: &str) -> Result<usize, String> {
    if ttl.len() > MAX_TTL_CHARS {
        return Err(format!(
            "ttl too large ({} chars; max {MAX_TTL_CHARS})",
            ttl.len()
        ));
    }
    let store = Store::new().map_err(|e| format!("oxigraph store: {e}"))?;
    store
        .load_from_reader(RdfFormat::Turtle, Cursor::new(ttl.as_bytes()))
        .map_err(|e| format!("invalid turtle: {e}"))?;
    let count = store.len().map_err(|e| format!("oxigraph len: {e}"))?;
    Ok(count)
}

pub fn load_revision(building_root: &Path) -> Result<u64, String> {
    let path = meta_path(building_root);
    if !path.is_file() {
        return Ok(0);
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read overlay meta: {e}"))?;
    let meta: OverlayMeta =
        serde_json::from_str(&raw).map_err(|e| format!("parse overlay meta: {e}"))?;
    Ok(meta.revision)
}

pub fn load_ttl(building_root: &Path) -> Result<String, String> {
    let path = ttl_path(building_root);
    if !path.is_file() {
        return Ok(String::new());
    }
    fs::read_to_string(&path).map_err(|e| format!("read overlay ttl: {e}"))
}

pub fn load_meta(building_root: &Path) -> Result<Option<OverlayMeta>, String> {
    let path = meta_path(building_root);
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read overlay meta: {e}"))?;
    let meta: OverlayMeta =
        serde_json::from_str(&raw).map_err(|e| format!("parse overlay meta: {e}"))?;
    Ok(Some(meta))
}

/// Replace overlay TTL with BPS-compatible dry_run + expected_revision CAS.
pub fn put_overlay_ttl(
    building_root: &Path,
    building_id: &str,
    ttl: &str,
    expected_revision: Option<u64>,
    dry_run: bool,
) -> Result<Value, Value> {
    let quad_count = validate_turtle(ttl).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    let current = load_revision(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    if let Some(want) = expected_revision {
        if want != current {
            return Err(json!({
                "ok": false,
                "conflict": true,
                "building_id": building_id,
                "site_id": building_id,
                "revision": current,
                "expected_revision": want,
                "error": "revision mismatch (reload overlay and retry)",
                "soft_open_neq_fq": true,
            }));
        }
    }

    let digest = sha256_16(ttl);
    let next_rev = current + 1;
    if dry_run {
        return Ok(json!({
            "ok": true,
            "dry_run": true,
            "building_id": building_id,
            "site_id": building_id,
            "revision": current,
            "would_revision": next_rev,
            "ttl_sha256_16": digest,
            "ttl_chars": ttl.len(),
            "quad_count": quad_count,
            "writable_layer": WRITABLE_LAYER,
            "soft_open_neq_fq": true,
            "note": "dry_run validated turtle + CAS; overlay not published",
            "gaps": soft_open_gaps(),
        }));
    }

    fs::create_dir_all(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("create building root: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    let ttl_dest = ttl_path(building_root);
    let ttl_tmp = building_root.join(format!("{OVERLAY_TTL_FILE}{OVERLAY_TMP_SUFFIX}"));
    fs::write(&ttl_tmp, ttl.as_bytes()).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("write overlay ttl tmp: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    fs::rename(&ttl_tmp, &ttl_dest).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("publish overlay ttl: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    let meta = OverlayMeta {
        building_id: building_id.to_string(),
        revision: next_rev,
        updated_at: Some(now_rfc3339_z()),
        note: Some("put_overlay_ttl".into()),
        ttl_sha256_16: Some(digest.clone()),
    };
    let meta_dest = meta_path(building_root);
    let meta_tmp = building_root.join(format!("{OVERLAY_META_FILE}{OVERLAY_TMP_SUFFIX}"));
    let meta_json = serde_json::to_string_pretty(&meta).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("serialize overlay meta: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    fs::write(&meta_tmp, format!("{meta_json}\n")).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("write overlay meta tmp: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    fs::rename(&meta_tmp, &meta_dest).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("publish overlay meta: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    Ok(json!({
        "ok": true,
        "dry_run": false,
        "building_id": building_id,
        "site_id": building_id,
        "revision": next_rev,
        "overlay": ttl_dest.display().to_string(),
        "ttl_sha256_16": digest,
        "ttl_chars": ttl.len(),
        "quad_count": quad_count,
        "writable_layer": WRITABLE_LAYER,
        "pack_immutable": true,
        "soft_open_neq_fq": true,
        "note": "put_overlay_ttl",
        "gaps": soft_open_gaps(),
    }))
}

pub fn soft_open_gaps() -> Vec<&'static str> {
    vec![
        "overlay TTL not yet unioned into SPARQL pack graph",
        "POST/DELETE /api/model/equip|point tombstones not Soft-OPEN yet",
    ]
}

pub fn get_overlay_payload(building_root: &Path, building_id: &str) -> Result<Value, String> {
    let revision = load_revision(building_root)?;
    let ttl = load_ttl(building_root)?;
    let present = ttl_path(building_root).is_file();
    Ok(json!({
        "ok": true,
        "building_id": building_id,
        "site_id": building_id,
        "revision": revision,
        "ttl": ttl,
        "overlay_present": present,
        "pack_immutable": true,
        "writable_layer": WRITABLE_LAYER,
        "soft_open_neq_fq": true,
        "gaps": soft_open_gaps(),
        "note": "Soft-OPEN overlay sidecar — not SPARQL pack authority (≠ FQ)",
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    const SAMPLE_TTL: &str = r#"
@prefix ph: <https://project-haystack.org/def/ph#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<urn:openfdd:site/SYNTH_OVERLAY#equip-AHU_1> a ph:equip ;
  ph:dis "AHU 1" .
"#;

    #[test]
    fn validate_rejects_garbage() {
        let err = validate_turtle("this is not turtle {{{").unwrap_err();
        assert!(err.contains("invalid turtle"), "{err}");
    }

    #[test]
    fn put_dry_run_conflict_and_publish() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "SYNTH_OVERLAY";

        let dry = put_overlay_ttl(root, bid, SAMPLE_TTL, None, true).unwrap();
        assert_eq!(dry.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(dry.get("dry_run").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(dry.get("revision").and_then(|v| v.as_u64()), Some(0));
        assert_eq!(dry.get("would_revision").and_then(|v| v.as_u64()), Some(1));
        assert!(!ttl_path(root).is_file());

        let pub1 = put_overlay_ttl(root, bid, SAMPLE_TTL, Some(0), false).unwrap();
        assert_eq!(pub1.get("revision").and_then(|v| v.as_u64()), Some(1));
        assert!(ttl_path(root).is_file());
        assert_eq!(load_revision(root).unwrap(), 1);

        let conflict = put_overlay_ttl(root, bid, SAMPLE_TTL, Some(0), false).unwrap_err();
        assert_eq!(
            conflict.get("conflict").and_then(|v| v.as_bool()),
            Some(true)
        );

        let pub2 = put_overlay_ttl(root, bid, SAMPLE_TTL, Some(1), false).unwrap();
        assert_eq!(pub2.get("revision").and_then(|v| v.as_u64()), Some(2));

        let got = get_overlay_payload(root, bid).unwrap();
        assert_eq!(got.get("revision").and_then(|v| v.as_u64()), Some(2));
        assert!(got
            .get("ttl")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .contains("AHU_1"));
    }
}
