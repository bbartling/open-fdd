//! Versioned native semantic metadata for Haystack RDF C2 (#1000).
//!
//! Schema `openfdd_semantic_meta_v1` persists point tags/units/refs/provenance and
//! optional engineering quantities so C3 can project to Project Haystack RDF.
//! Old packages without this sidecar keep prior FDD/analytics meaning (HR-01).
//! Custom Open-FDD fields stay engineering-only — Haystack tags are preferred.

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
#[cfg(unix)]
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub const SCHEMA: &str = "openfdd_semantic_meta_v1";
/// Accepted C1 sketch schema — upgraded on load, never fabricated for old ZIPs.
pub const SKETCH_SCHEMA: &str = "openfdd_point_metadata_v1_sketch";
pub const SEMANTIC_META_FILE: &str = "semantic_meta.json";
pub const SEMANTIC_META_REVISION_FILE: &str = "semantic_meta.revision.json";
pub const SEMANTIC_META_LOCK_FILE: &str = "semantic_meta.lock";
pub const SEMANTIC_META_REVISIONS_DIR: &str = "semantic_meta_revisions";
/// Package path aliases (building-root relative).
pub const PACKAGE_CANDIDATES: &[&str] = &[
    "semantic_meta.json",
    "openfdd_semantic_meta_v1.json",
    "point_metadata.json",
    "openfdd_point_metadata_v1.json",
];

// Test-only: fail after durable immutable revision write, before head publication.
#[cfg(test)]
thread_local! {
    static FAIL_BEFORE_HEAD: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(1);

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
    /// Stable point identity independent of mutable CSV header / display name.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub point_id: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub haystack_tags: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit_source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit_status: Option<String>,
    /// Haystack `kind` string tag (Number, Bool, Str, …).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    /// Haystack timezone id (`tz`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tz: Option<String>,
    /// When true, emit `phIoT:his` marker (historized point).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub his: Option<bool>,
    /// Containment equip ref (must exist in scoped model when set).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_equip: Option<String>,
    /// Air-flow ref only with explicit evidence (`airRef` direction).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub air_ref: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub site_ref: Option<String>,
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
    /// Parent equipment id. Relationship kind is required separately.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_equip: Option<String>,
    /// `equipRef` (containment) or `airRef` (air flows from referent). Required
    /// to emit a topology edge from `parent_equip`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_relation: Option<String>,
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

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

fn unique_tmp_path(path: &Path) -> PathBuf {
    let seq = TMP_SEQ.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("semantic_meta.json");
    path.with_file_name(format!(".{name}.tmp.{nanos}.{seq}"))
}

fn atomic_write(path: &Path, body: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    let tmp = unique_tmp_path(path);
    {
        let mut f = File::create(&tmp).map_err(|e| format!("create tmp: {e}"))?;
        f.write_all(body.as_bytes())
            .map_err(|e| format!("write tmp: {e}"))?;
        f.sync_all().map_err(|e| format!("sync tmp: {e}"))?;
    }
    fs::rename(&tmp, path).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        format!("rename {}: {e}", path.display())
    })?;
    Ok(())
}

struct SiteLock {
    _file: File,
}

impl SiteLock {
    fn acquire(building_root: &Path) -> Result<Self, String> {
        fs::create_dir_all(building_root)
            .map_err(|e| format!("mkdir {}: {e}", building_root.display()))?;
        let lock_path = building_root.join(SEMANTIC_META_LOCK_FILE);
        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|e| format!("open lock {}: {e}", lock_path.display()))?;
        #[cfg(unix)]
        {
            let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) };
            if rc != 0 {
                return Err(format!(
                    "flock {}: {}",
                    lock_path.display(),
                    std::io::Error::last_os_error()
                ));
            }
        }
        Ok(Self { _file: file })
    }
}

impl Drop for SiteLock {
    fn drop(&mut self) {
        #[cfg(unix)]
        {
            let _ = unsafe { libc::flock(self._file.as_raw_fd(), libc::LOCK_UN) };
        }
    }
}

fn revisions_dir(building_root: &Path) -> PathBuf {
    building_root.join(SEMANTIC_META_REVISIONS_DIR)
}

fn revision_object_path(building_root: &Path, revision: &str) -> PathBuf {
    revisions_dir(building_root).join(format!("{revision}.json"))
}

fn read_head(building_root: &Path) -> Result<Option<SemanticMetaRevision>, String> {
    let rev_path = building_revision_path(building_root);
    if !rev_path.is_file() {
        return Ok(None);
    }
    let cur = fs::read_to_string(&rev_path).map_err(|e| format!("read revision: {e}"))?;
    let cur_rev: SemanticMetaRevision =
        serde_json::from_str(&cur).map_err(|e| format!("parse revision: {e}"))?;
    Ok(Some(cur_rev))
}

fn encode_meta_body(meta: &SemanticMetaV1) -> Result<String, String> {
    let body = serde_json::to_string_pretty(meta).map_err(|e| e.to_string())?;
    Ok(format!("{body}\n"))
}

fn next_revision_id(content_sha256: &str) -> String {
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let seq = TMP_SEQ.fetch_add(1, Ordering::Relaxed);
    let prefix: String = content_sha256.chars().take(12).collect();
    format!("r{ms}-{seq:x}-{prefix}")
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

    // Identity hygiene (HR-02): normalize once; reject empty / padded / duplicate ids.
    let mut equip_keys = BTreeMap::<String, ()>::new();
    for (i, e) in meta.equipment.iter_mut().enumerate() {
        let raw_id = e.equipment_id.clone();
        let id = raw_id.trim().to_string();
        if id.is_empty() {
            return Err(format!(
                "semantic meta equipment[{i}]: equipment_id required"
            ));
        }
        if id != raw_id {
            return Err(format!(
                "semantic meta equipment[{i}]: noncanonical equipment_id (leading/trailing whitespace)"
            ));
        }
        if equip_keys.insert(id.clone(), ()).is_some() {
            return Err(format!(
                "semantic meta equipment: duplicate equipment_id {id:?}"
            ));
        }
        e.equipment_id = id;
        if let Some(rel) = e.parent_relation.as_deref().map(str::trim) {
            if !(rel.is_empty() || rel == "equipRef" || rel == "airRef") {
                return Err(format!(
                    "semantic meta equipment[{i}]: parent_relation must be equipRef or airRef"
                ));
            }
            if rel.is_empty() {
                e.parent_relation = None;
            } else {
                e.parent_relation = Some(rel.to_string());
            }
        }
    }

    let mut point_keys = BTreeMap::<String, ()>::new();
    for (i, p) in meta.points.iter_mut().enumerate() {
        let raw_eid = p.equipment_id.clone();
        let raw_col = p.column.clone();
        let eid = raw_eid.trim();
        let col = raw_col.trim();
        if eid.is_empty() || col.is_empty() {
            return Err(format!(
                "semantic meta points[{i}]: equipment_id and column required"
            ));
        }
        if eid != raw_eid || col != raw_col {
            return Err(format!(
                "semantic meta points[{i}]: noncanonical equipment_id/column (whitespace)"
            ));
        }
        if let Some(pid) = p.point_id.as_deref() {
            let trimmed = pid.trim();
            if trimmed.is_empty() {
                return Err(format!("semantic meta points[{i}]: point_id empty"));
            }
            if trimmed != pid {
                return Err(format!(
                    "semantic meta points[{i}]: noncanonical point_id (whitespace)"
                ));
            }
            p.point_id = Some(trimmed.to_string());
        }
        let key = format!("{}|{}", eid, p.point_id.as_deref().unwrap_or(col));
        if point_keys.insert(key, ()).is_some() {
            return Err(format!(
                "semantic meta points: duplicate point identity for equipment {eid:?}"
            ));
        }
        p.equipment_id = eid.to_string();
        p.column = col.to_string();
    }
    Ok(meta)
}

/// Exact equipment scope + optional parent/site closure for export/query.
pub fn scope_meta(
    meta: &SemanticMetaV1,
    equipment_id: Option<&str>,
) -> Result<SemanticMetaV1, String> {
    let Some(want) = equipment_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(meta.clone());
    };
    let selected: Vec<EquipmentMeta> = meta
        .equipment
        .iter()
        .filter(|e| e.equipment_id == want)
        .cloned()
        .collect();
    if selected.is_empty() {
        return Err(format!(
            "equipment_id {want:?} not present in semantic_meta for building {}",
            meta.building_id
        ));
    }
    let mut keep = std::collections::BTreeSet::new();
    keep.insert(want.to_string());
    // Bounded closure: include explicitly referenced parents when present.
    for e in &selected {
        if let Some(parent) = e
            .parent_equip
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            if meta.equipment.iter().any(|x| x.equipment_id == parent) {
                keep.insert(parent.to_string());
            }
        }
    }
    for p in &meta.points {
        if p.equipment_id != want {
            continue;
        }
        if let Some(r) = p
            .ref_equip
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            if meta.equipment.iter().any(|x| x.equipment_id == r) {
                keep.insert(r.to_string());
            }
        }
        if let Some(r) = p
            .air_ref
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            if meta.equipment.iter().any(|x| x.equipment_id == r) {
                keep.insert(r.to_string());
            }
        }
    }
    Ok(SemanticMetaV1 {
        schema: meta.schema.clone(),
        building_id: meta.building_id.clone(),
        revision: meta.revision.clone(),
        note: meta.note.clone(),
        points: meta
            .points
            .iter()
            .filter(|p| p.equipment_id == want)
            .cloned()
            .collect(),
        equipment: meta
            .equipment
            .iter()
            .filter(|e| keep.contains(&e.equipment_id))
            .cloned()
            .collect(),
        engineering_quantities: meta.engineering_quantities.clone(),
    })
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

/// Load tip meta and verify companion head hash (HR-07 recovery).
pub fn load_persisted(building_root: &Path) -> Result<Option<SemanticMetaV1>, String> {
    let _lock = SiteLock::acquire(building_root)?;
    load_persisted_locked(building_root)
}

fn load_persisted_locked(building_root: &Path) -> Result<Option<SemanticMetaV1>, String> {
    let head = read_head(building_root)?;
    let path = building_meta_path(building_root);
    if !path.is_file() {
        if head.is_some() {
            return Err("semantic meta head present but tip semantic_meta.json missing".into());
        }
        return Ok(None);
    }
    let body = fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let digest = sha256_hex(body.as_bytes());
    let parsed = serde_json::from_str::<Value>(&body)
        .map_err(|e| format!("parse {}: {e}", path.display()))
        .and_then(|raw| parse_semantic_meta(&raw));
    match (head, parsed) {
        (None, Ok(meta)) => Ok(Some(meta)),
        (None, Err(e)) => Err(e),
        (Some(h), Ok(meta)) => {
            if meta.revision.as_deref() != Some(h.revision.as_str()) || digest != h.content_sha256 {
                return recover_tip_from_revision(building_root, &path, &h);
            }
            Ok(Some(meta))
        }
        (Some(h), Err(_)) => recover_tip_from_revision(building_root, &path, &h),
    }
}

fn recover_tip_from_revision(
    building_root: &Path,
    tip_path: &Path,
    head: &SemanticMetaRevision,
) -> Result<Option<SemanticMetaV1>, String> {
    let recovered = load_revision_object(building_root, &head.revision)?;
    let recovered_body = encode_meta_body(&recovered)?;
    if sha256_hex(recovered_body.as_bytes()) != head.content_sha256 {
        return Err(format!(
            "semantic meta immutable revision {} hash mismatch versus head",
            head.revision
        ));
    }
    atomic_write(tip_path, &recovered_body)?;
    Ok(Some(recovered))
}

fn load_revision_object(building_root: &Path, revision: &str) -> Result<SemanticMetaV1, String> {
    let path = revision_object_path(building_root, revision);
    let body = fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let raw: Value =
        serde_json::from_str(&body).map_err(|e| format!("parse {}: {e}", path.display()))?;
    parse_semantic_meta(&raw)
}

/// Transactional persist: immutable revision object + atomic head CAS (HR-07 / #1123 F7).
///
/// Publication order under a per-site lock:
/// 1. validate + CAS expected head
/// 2. write immutable `semantic_meta_revisions/{rev}.json`
/// 3. write tip `semantic_meta.json`
/// 4. write head `semantic_meta.revision.json` (**commit point**)
///
/// Identical content to the current head is idempotent (returns existing head).
pub fn persist_atomic(
    building_root: &Path,
    mut meta: SemanticMetaV1,
    expected_revision: Option<&str>,
) -> Result<SemanticMetaRevision, String> {
    let _lock = SiteLock::acquire(building_root)?;
    let current = read_head(building_root)?;
    if let Some(want) = expected_revision {
        match &current {
            Some(cur) if cur.revision == want => {}
            Some(cur) => {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have {}",
                    cur.revision
                ));
            }
            None if want.is_empty() => {}
            None => {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have none"
                ));
            }
        }
    }

    // Provisional encode without revision for content-addressed idempotence.
    meta.revision = None;
    let provisional = encode_meta_body(&meta)?;
    let provisional_digest = sha256_hex(provisional.as_bytes());
    if let Some(cur) = &current {
        // Compare against stored tip bytes if available.
        if let Ok(Some(existing)) = load_persisted_locked(building_root) {
            let mut existing_cmp = existing.clone();
            existing_cmp.revision = None;
            if let Ok(ex_body) = encode_meta_body(&existing_cmp) {
                if sha256_hex(ex_body.as_bytes()) == provisional_digest {
                    return Ok(cur.clone());
                }
            }
        }
    }

    let next_rev = next_revision_id(&provisional_digest);
    meta.revision = Some(next_rev.clone());
    let body = encode_meta_body(&meta)?;
    let digest = sha256_hex(body.as_bytes());
    let rev = SemanticMetaRevision {
        schema: SCHEMA.to_string(),
        building_id: meta.building_id.clone(),
        revision: next_rev.clone(),
        content_sha256: digest,
    };
    let rev_body = serde_json::to_string_pretty(&rev).map_err(|e| e.to_string())?;
    let rev_body = format!("{rev_body}\n");

    // 1) Immutable revision object (never overwritten).
    atomic_write(&revision_object_path(building_root, &next_rev), &body)?;

    #[cfg(test)]
    {
        if FAIL_BEFORE_HEAD.with(|c| c.get()) {
            return Err("injected failure before head publication".into());
        }
    }

    // 2) Tip convenience file, then 3) head commit.
    atomic_write(&building_meta_path(building_root), &body)?;
    atomic_write(&building_revision_path(building_root), &rev_body)?;
    Ok(rev)
}

/// Roll tip/head back to a previously published immutable revision (HR-07).
pub fn rollback_to(
    building_root: &Path,
    target_revision: &str,
    expected_revision: Option<&str>,
) -> Result<SemanticMetaRevision, String> {
    let meta = {
        let _lock = SiteLock::acquire(building_root)?;
        if let Some(want) = expected_revision {
            match read_head(building_root)? {
                Some(cur) if cur.revision == want => {}
                Some(cur) => {
                    return Err(format!(
                        "semantic meta revision conflict: expected {want}, have {}",
                        cur.revision
                    ));
                }
                None => {
                    return Err(format!(
                        "semantic meta revision conflict: expected {want}, have none"
                    ));
                }
            }
        }
        load_revision_object(building_root, target_revision)?
    };
    // Re-publish the historical body as a new head via normal CAS path would mint a
    // new revision id; for rollback we restore the exact historical revision/hash.
    let _lock = SiteLock::acquire(building_root)?;
    if let Some(want) = expected_revision {
        match read_head(building_root)? {
            Some(cur) if cur.revision == want => {}
            Some(cur) => {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have {}",
                    cur.revision
                ));
            }
            None => {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have none"
                ));
            }
        }
    }
    let body = encode_meta_body(&meta)?;
    let digest = sha256_hex(body.as_bytes());
    let rev = SemanticMetaRevision {
        schema: SCHEMA.to_string(),
        building_id: meta.building_id.clone(),
        revision: target_revision.to_string(),
        content_sha256: digest,
    };
    let rev_body = serde_json::to_string_pretty(&rev).map_err(|e| e.to_string())?;
    let rev_body = format!("{rev_body}\n");
    atomic_write(&building_meta_path(building_root), &body)?;
    atomic_write(&building_revision_path(building_root), &rev_body)?;
    Ok(rev)
}

/// Delete tip+head after CAS. Immutable revision objects are retained.
pub fn delete_persisted(
    building_root: &Path,
    expected_revision: Option<&str>,
) -> Result<(), String> {
    let _lock = SiteLock::acquire(building_root)?;
    if let Some(want) = expected_revision {
        match read_head(building_root)? {
            Some(cur) if cur.revision == want => {}
            Some(cur) => {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have {}",
                    cur.revision
                ));
            }
            None if want.is_empty() => {}
            None => {
                return Err(format!(
                    "semantic meta revision conflict: expected {want}, have none"
                ));
            }
        }
    }
    let tip = building_meta_path(building_root);
    let head = building_revision_path(building_root);
    if tip.is_file() {
        fs::remove_file(&tip).map_err(|e| format!("remove tip: {e}"))?;
    }
    if head.is_file() {
        fs::remove_file(&head).map_err(|e| format!("remove head: {e}"))?;
    }
    Ok(())
}

/// Import helper: persist package sidecar or leave prior revision intact on error.
/// Uses CAS against the current head when one exists (HR-07).
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
            match persist_replace_current(building_root, meta) {
                Ok(rev) => json!({
                    "ok": true,
                    "present": true,
                    "schema": SCHEMA,
                    "revision": rev.revision,
                    "content_sha256": rev.content_sha256,
                }),
                Err(e) => {
                    warnings.push(format!("semantic_meta persist failed: {e}"));
                    json!({
                        "ok": false,
                        "present": true,
                        "error": e,
                        "prior_intact": building_meta_path(building_root).is_file(),
                    })
                }
            }
        }
    }
}

/// Package-import CAS: lock, read current head, publish against that expected revision.
pub fn persist_replace_current(
    building_root: &Path,
    meta: SemanticMetaV1,
) -> Result<SemanticMetaRevision, String> {
    let expected = {
        let _lock = SiteLock::acquire(building_root)?;
        read_head(building_root)?.map(|h| h.revision)
    };
    persist_atomic(building_root, meta, expected.as_deref())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};
    use std::thread;
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

    fn sample_meta() -> SemanticMetaV1 {
        parse_semantic_meta(&sample_raw()).unwrap()
    }

    #[test]
    fn upgrades_c1_sketch_and_roundtrips() {
        let meta = sample_meta();
        assert_eq!(meta.schema, SCHEMA);
        assert_eq!(meta.points.len(), 1);
        let dir = tempdir().unwrap();
        let rev = persist_atomic(dir.path(), meta.clone(), None).unwrap();
        let loaded = load_persisted(dir.path()).unwrap().unwrap();
        assert_eq!(loaded.schema, SCHEMA);
        assert_eq!(loaded.points[0].column, "SAT");
        assert_eq!(loaded.revision.as_deref(), Some(rev.revision.as_str()));
        assert!(revision_object_path(dir.path(), &rev.revision).is_file());
    }

    #[test]
    fn invalid_meta_leaves_prior_intact() {
        let dir = tempdir().unwrap();
        let meta = sample_meta();
        persist_atomic(dir.path(), meta, None).unwrap();
        let prior = fs::read_to_string(building_meta_path(dir.path())).unwrap();

        let bad = json!({"schema": "not_a_schema", "building_id": "SITE_A"});
        assert!(parse_semantic_meta(&bad).is_err());
        let after = fs::read_to_string(building_meta_path(dir.path())).unwrap();
        assert_eq!(prior, after);
    }

    #[test]
    fn revision_conflict_is_explicit() {
        let dir = tempdir().unwrap();
        let meta = sample_meta();
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

    #[test]
    fn injected_failure_before_head_keeps_prior_tip() {
        let dir = tempdir().unwrap();
        let first = persist_atomic(dir.path(), sample_meta(), None).unwrap();
        let prior_tip = fs::read_to_string(building_meta_path(dir.path())).unwrap();
        let prior_head = fs::read_to_string(building_revision_path(dir.path())).unwrap();

        FAIL_BEFORE_HEAD.with(|c| c.set(true));
        let mut next = sample_meta();
        next.note = Some("mutated".into());
        let err = persist_atomic(dir.path(), next, Some(&first.revision)).unwrap_err();
        FAIL_BEFORE_HEAD.with(|c| c.set(false));
        assert!(err.contains("injected failure"), "{err}");
        assert_eq!(
            fs::read_to_string(building_meta_path(dir.path())).unwrap(),
            prior_tip
        );
        assert_eq!(
            fs::read_to_string(building_revision_path(dir.path())).unwrap(),
            prior_head
        );
        let loaded = load_persisted(dir.path()).unwrap().unwrap();
        assert_eq!(loaded.revision.as_deref(), Some(first.revision.as_str()));
        assert!(loaded.note.is_none());
    }

    #[test]
    fn concurrent_cas_one_wins() {
        let dir = tempdir().unwrap();
        let root = Arc::new(dir.path().to_path_buf());
        let first = persist_atomic(root.as_path(), sample_meta(), None).unwrap();
        let barrier = Arc::new(Barrier::new(2));
        let mut handles = Vec::new();
        for i in 0..2 {
            let root = Arc::clone(&root);
            let barrier = Arc::clone(&barrier);
            let base = first.revision.clone();
            handles.push(thread::spawn(move || {
                barrier.wait();
                let mut meta = sample_meta();
                meta.note = Some(format!("writer-{i}"));
                persist_atomic(root.as_path(), meta, Some(&base))
            }));
        }
        let results: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        let wins = results.iter().filter(|r| r.is_ok()).count();
        let losses = results.iter().filter(|r| r.is_err()).count();
        assert_eq!(wins, 1, "{results:?}");
        assert_eq!(losses, 1, "{results:?}");
        let tip = load_persisted(root.as_path()).unwrap().unwrap();
        assert!(tip.note.as_deref() == Some("writer-0") || tip.note.as_deref() == Some("writer-1"));
    }

    #[test]
    fn idempotent_reimport_same_content() {
        let dir = tempdir().unwrap();
        let meta = sample_meta();
        let first = persist_atomic(dir.path(), meta.clone(), None).unwrap();
        let second = persist_replace_current(dir.path(), meta).unwrap();
        assert_eq!(first.revision, second.revision);
        assert_eq!(first.content_sha256, second.content_sha256);
    }

    #[test]
    fn rollback_and_delete_preserve_immutable_objects() {
        let dir = tempdir().unwrap();
        let r1 = persist_atomic(dir.path(), sample_meta(), None).unwrap();
        let mut m2 = sample_meta();
        m2.note = Some("v2".into());
        let r2 = persist_atomic(dir.path(), m2, Some(&r1.revision)).unwrap();
        assert_ne!(r1.revision, r2.revision);
        let rolled = rollback_to(dir.path(), &r1.revision, Some(&r2.revision)).unwrap();
        assert_eq!(rolled.revision, r1.revision);
        let loaded = load_persisted(dir.path()).unwrap().unwrap();
        assert!(loaded.note.is_none());
        assert!(revision_object_path(dir.path(), &r2.revision).is_file());
        delete_persisted(dir.path(), Some(&r1.revision)).unwrap();
        assert!(load_persisted(dir.path()).unwrap().is_none());
        assert!(revision_object_path(dir.path(), &r1.revision).is_file());
    }

    #[test]
    fn load_recovers_corrupt_tip_from_immutable_revision() {
        let dir = tempdir().unwrap();
        let rev = persist_atomic(dir.path(), sample_meta(), None).unwrap();
        fs::write(building_meta_path(dir.path()), "{}\n").unwrap();
        let loaded = load_persisted(dir.path()).unwrap().unwrap();
        assert_eq!(loaded.revision.as_deref(), Some(rev.revision.as_str()));
        assert_eq!(loaded.points[0].column, "SAT");
        // Tip file repaired.
        let tip = fs::read_to_string(building_meta_path(dir.path())).unwrap();
        assert!(tip.contains("AHU_1"));
    }
}
