//! `openfdd_package_v1` ZIP loader (#514).
//!
//! Accepts the vibe19 package layout (see vibe19 `docs/PACKAGE_SPEC.md`):
//! `manifest.json` + per-equipment `history_wide.csv` with a sibling Haystack-style
//! column map (`history_wide.json` / `history_wide.column_map.json` / `column_map.json`),
//! optional root `column_map.json`, `session_config.json`, and `weather/history_wide.csv`.
//!
//! The package is staged under `workspace/data/csv_buildings/<building_id>.incoming/`
//! (manifest `grid_minutes` → poll_seconds, per-equipment `columns.csv` role map).
//! Central seeds Timescale from `package_root` (`needs_timescale_seed: true`) and
//! publishes the tree only after that transaction commits. No dual-write.

use crate::csv_ingest::portal_ingest_sparql::{
    compile_bindings_from_snapshot, validate_slug, IngestSparqlScope,
};
use crate::historian::store::workspace_dir;
use fdd_core::haystack_point_to_role;
use serde_json::{json, Map, Value};
use sqlx::Row;
use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::path::{Path, PathBuf};

pub const PACKAGE_SCHEMA: &str = "openfdd_package_v1";

fn is_incoming_root(root: &Path) -> bool {
    root.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.ends_with(".incoming"))
}

/// Delete a staged package tree. Live `csv_buildings/<id>` is left in place.
pub fn abort_staged_package(staging_root: &Path) {
    if is_incoming_root(staging_root) {
        let _ = std::fs::remove_dir_all(staging_root);
    }
}

/// Publish a staged package after its historian writes have committed.
///
/// The live tree is replaced only here. A rename failure puts the previous
/// tree back and leaves the staged directory for the caller to abort.
pub fn commit_staged_package(
    staging_root: &Path,
    samples: u64,
    equipment_count: usize,
) -> Result<PathBuf, String> {
    if !is_incoming_root(staging_root) {
        return Err("package commit requires a staged .incoming directory".into());
    }
    if !staging_root.is_dir() {
        return Err(format!(
            "staged package is missing: {}",
            staging_root.display()
        ));
    }
    let file_name = staging_root
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| "staged package name is not utf-8".to_string())?;
    let building_id = file_name
        .strip_suffix(".incoming")
        .filter(|id| !id.is_empty())
        .ok_or_else(|| "staged package name is missing its building id".to_string())?;
    let parent = staging_root
        .parent()
        .ok_or_else(|| "staged package has no parent directory".to_string())?;
    let live = parent.join(building_id);
    let backup = parent.join(format!("{building_id}.previous"));
    if backup.exists() {
        std::fs::remove_dir_all(&backup)
            .map_err(|e| format!("remove previous package backup: {e}"))?;
    }
    if live.exists() {
        std::fs::rename(&live, &backup).map_err(|e| {
            format!(
                "move live package aside: {e} (live {} left in place)",
                live.display()
            )
        })?;
    }
    if let Err(e) = std::fs::rename(staging_root, &live) {
        if backup.exists() {
            let _ = std::fs::rename(&backup, &live);
        }
        return Err(format!("publish staged package: {e}"));
    }
    if backup.exists() {
        let _ = std::fs::remove_dir_all(&backup);
    }
    activate_staged_session(&live, building_id);
    if let Err(e) = crate::csv_ingest::dataset::register_package_dataset(
        building_id,
        samples,
        equipment_count,
        &json!({
            "package_root": live.display().to_string(),
            "historian": "timescale",
        }),
    ) {
        tracing::warn!(%e, "dataset registry not updated after package commit");
    }
    Ok(live)
}

fn activate_staged_session(live: &Path, building_id: &str) {
    let path = live.join("session_config.json");
    let Ok(text) = std::fs::read_to_string(&path) else {
        return;
    };
    let Ok(cfg) = serde_json::from_str::<Value>(&text) else {
        return;
    };
    let Ok((normalized, _)) = crate::fdd::session_config::normalize_session_config(&cfg) else {
        return;
    };
    let scope = crate::fdd::session_config::SessionConfigScope::new(None, Some(building_id));
    if crate::fdd::session_config::save_session_config_scoped(&scope, &normalized).is_ok()
        && scope.tenant_id.is_none()
    {
        let _ = crate::fdd::session_config::save_session_config(&normalized);
    }
}

fn env_cap_mb(name: &str, default_mb: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .filter(|v| *v > 0)
        .unwrap_or(default_mb)
}

fn max_uncompressed_bytes() -> u64 {
    // Cap default at 512 MiB so concurrent uploads cannot pin multi-GiB in RAM.
    env_cap_mb("OPENFDD_MAX_UNCOMPRESSED_MB", 512) * 1024 * 1024
}

fn max_entries() -> usize {
    std::env::var("OPENFDD_MAX_ENTRIES")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|v| *v > 0)
        .unwrap_or(2000)
}

/// Max path depth inside the archive (matches vibe19 `package_io.MAX_PATH_DEPTH`).
const MAX_PATH_DEPTH: usize = 8;

/// Reject zip entries whose declared uncompressed/compressed ratio exceeds this (zip bomb heuristic).
const MAX_COMPRESSION_RATIO: f64 = 100.0;

/// Unix symlink mode nibble — mirrors vibe19 `package_io.stat_is_symlink`.
const UNIX_SYMLINK_MODE: u32 = 0o120000;

#[derive(Debug)]
struct PackageManifest {
    building_id: String,
    grid_minutes: u32,
    timezone: Option<String>,
    notes: Option<String>,
}

fn parse_manifest(raw: &Value) -> Result<PackageManifest, String> {
    let schema = raw
        .get("schema_version")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if schema != PACKAGE_SCHEMA {
        return Err(format!(
            "manifest.json schema_version must be {PACKAGE_SCHEMA:?}, got {schema:?}"
        ));
    }
    let building_id = raw
        .get("building_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if building_id.is_empty() {
        return Err("manifest.json building_id must be a non-empty string".into());
    }
    let grid_minutes = raw
        .get("grid_minutes")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    if grid_minutes <= 0.0 || !grid_minutes.is_finite() {
        return Err("manifest.json grid_minutes must be > 0".into());
    }
    Ok(PackageManifest {
        building_id,
        grid_minutes: (grid_minutes.round() as u32).clamp(1, 24 * 60),
        timezone: raw
            .get("timezone")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        notes: raw
            .get("notes")
            .and_then(|v| v.as_str())
            .map(str::to_string),
    })
}

/// Accept only a single safe path component (no slash / traversal / empty).
/// Distinct inputs must not collapse into the same directory name.
fn validate_id(id: &str) -> Result<String, String> {
    let id = id.trim();
    if id.is_empty() {
        return Err("id must be non-empty".into());
    }
    if id == "." || id == ".." || id.contains('/') || id.contains('\\') || id.contains(':') {
        return Err(format!("id {id:?} is not a single safe path component"));
    }
    if !id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err(format!(
            "id {id:?} may only contain ASCII alphanumeric, '-', or '_'"
        ));
    }
    Ok(id.to_string())
}

/// Normalize a zip entry name: forward slashes, reject traversal / absolute paths.
fn safe_member_path(name: &str) -> Result<PathBuf, String> {
    let raw = name.replace('\\', "/");
    let parts_src = raw.trim_end_matches('/');
    if parts_src.is_empty() {
        return Err(format!("empty zip entry path: {name:?}"));
    }
    if parts_src.starts_with('/') || (parts_src.len() > 1 && parts_src.as_bytes()[1] == b':') {
        return Err(format!("absolute path in zip rejected: {name:?}"));
    }
    let parts: Vec<&str> = parts_src
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect();
    if parts.contains(&"..") {
        return Err(format!("path traversal rejected: {name:?}"));
    }
    if parts.len() > MAX_PATH_DEPTH {
        return Err(format!("path too deep (>{MAX_PATH_DEPTH}): {name:?}"));
    }
    Ok(parts.iter().collect())
}

fn zip_entry_is_symlink<R: std::io::Read>(entry: &zip::read::ZipFile<'_, R>) -> bool {
    if entry.is_symlink() {
        return true;
    }
    entry
        .unix_mode()
        .is_some_and(|mode| (mode & 0o170000) == UNIX_SYMLINK_MODE)
}

/// In-memory extraction of the package zip: relative path → bytes.
///
/// Rejected cases (hostile archive defenses):
/// - path traversal (`../`), absolute paths (`/etc/passwd`, `C:\…`)
/// - symlink entries (Unix mode or zip symlink marker)
/// - too many entries (`OPENFDD_MAX_ENTRIES`)
/// - uncompressed total over cap (`OPENFDD_MAX_UNCOMPRESSED_MB`)
/// - suspicious per-entry compression ratio (>100:1)
/// - duplicate paths differing only by case
/// - declared size mismatch vs bytes actually read
fn read_zip_entries(bytes: &[u8]) -> Result<BTreeMap<PathBuf, Vec<u8>>, String> {
    let cursor = std::io::Cursor::new(bytes);
    let mut archive =
        zip::ZipArchive::new(cursor).map_err(|e| format!("not a readable zip: {e}"))?;
    if archive.len() > max_entries() {
        return Err(format!(
            "zip has {} entries; cap is {} (OPENFDD_MAX_ENTRIES)",
            archive.len(),
            max_entries()
        ));
    }
    let cap = max_uncompressed_bytes();
    let mut total: u64 = 0;
    let mut out = BTreeMap::new();
    let mut names_lower: BTreeSet<String> = BTreeSet::new();
    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| format!("zip entry {i}: {e}"))?;
        if entry.is_dir() {
            continue;
        }
        let entry_name = entry
            .name()
            .map_err(|e| format!("bad zip entry name: {e}"))?
            .to_string();
        if zip_entry_is_symlink(&entry) {
            return Err(format!("symlink entries are not allowed: {entry_name}"));
        }
        let declared = entry.size();
        let compressed = entry.compressed_size();
        if compressed > 0 && (declared as f64) / (compressed as f64) > MAX_COMPRESSION_RATIO {
            return Err(format!("suspicious compression ratio: {entry_name}"));
        }
        let path = safe_member_path(&entry_name)?;
        let key = path
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !names_lower.insert(key) {
            return Err(format!("duplicate / case-colliding path: {entry_name}"));
        }
        total = total.saturating_add(declared);
        if total > cap {
            return Err(format!(
                "zip expands past {} MB cap (OPENFDD_MAX_UNCOMPRESSED_MB)",
                cap / (1024 * 1024)
            ));
        }
        let mut buf = Vec::with_capacity(declared as usize);
        entry
            .read_to_end(&mut buf)
            .map_err(|e| format!("zip entry {:?}: {e}", entry_name))?;
        let read_len = buf.len() as u64;
        if read_len > cap || total.saturating_sub(declared) + read_len > cap {
            return Err(format!(
                "zip expands past {} MB cap (OPENFDD_MAX_UNCOMPRESSED_MB)",
                cap / (1024 * 1024)
            ));
        }
        if declared > 0 && read_len > declared {
            return Err(format!(
                "zip entry expanded past declared size: {entry_name}"
            ));
        }
        out.insert(path, buf);
    }
    if out.is_empty() {
        return Err("zip contains no files".into());
    }
    Ok(out)
}

/// Root may be the building folder holding `openfdd_package_v1` manifest.json at any
/// safe depth (wrapper folders: `OpenFdd_<job>/.../<building_id>/manifest.json`).
fn resolve_building_prefix(entries: &BTreeMap<PathBuf, Vec<u8>>) -> Result<PathBuf, String> {
    if entries.contains_key(Path::new("manifest.json")) {
        return Ok(PathBuf::new());
    }
    let mut package_roots: Vec<PathBuf> = entries
        .iter()
        .filter(|(p, _)| p.file_name().map(|f| f == "manifest.json").unwrap_or(false))
        .filter(|(_, bytes)| is_package_manifest(bytes))
        .filter(|(p, _)| p.components().count() <= MAX_PATH_DEPTH)
        .filter_map(|(p, _)| p.parent().map(Path::to_path_buf))
        .collect();
    package_roots.sort();
    package_roots.dedup();
    match package_roots.len() {
        1 => Ok(package_roots.remove(0)),
        0 => Err(
            "package is missing openfdd_package_v1 manifest.json (root or nested folder)".into(),
        ),
        n => Err(format!(
            "found {n} openfdd_package_v1 manifest.json files; expected 1"
        )),
    }
}

fn is_package_manifest(bytes: &[u8]) -> bool {
    let Ok(v) = serde_json::from_slice::<Value>(bytes) else {
        return false;
    };
    v.get("schema_version")
        .and_then(|s| s.as_str())
        .map(|s| s == PACKAGE_SCHEMA)
        .unwrap_or(false)
}

/// Wrapper-level utility files (sibling to nested package folders), e.g.
/// `OpenFdd_<job>/utility_bills_monthly.csv` alongside `.../<building_id>/manifest.json`.
fn collect_wrapper_utility_files(
    entries: &BTreeMap<PathBuf, Vec<u8>>,
    building_prefix: &Path,
) -> Vec<(String, Vec<u8>)> {
    let mut out = Vec::new();
    let wrapper_root = building_prefix
        .components()
        .next()
        .map(|c| PathBuf::from(c.as_os_str()));
    let search_roots: Vec<PathBuf> = match wrapper_root {
        Some(w) if !w.as_os_str().is_empty() => vec![w],
        _ => vec![PathBuf::new()],
    };
    for (path, bytes) in entries {
        if building_prefix.as_os_str().is_empty() || !path.starts_with(building_prefix) {
            // only files under a known wrapper root, not the building tree itself
            let under_wrapper = search_roots
                .iter()
                .any(|w| w.as_os_str().is_empty() || path.starts_with(w));
            if !under_wrapper {
                continue;
            }
        } else {
            continue;
        }
        let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let rel = path.to_string_lossy().replace('\\', "/");
        if name.eq_ignore_ascii_case("utility_bills_monthly.csv") {
            out.push((rel, bytes.clone()));
        }
    }
    // Also accept utilities/ inside the building prefix.
    for (path, bytes) in entries {
        if !building_prefix.as_os_str().is_empty() && !path.starts_with(building_prefix) {
            continue;
        }
        let rel = if building_prefix.as_os_str().is_empty() {
            path.clone()
        } else {
            path.strip_prefix(building_prefix)
                .map(Path::to_path_buf)
                .unwrap_or_else(|_| path.clone())
        };
        let rel_s = rel.to_string_lossy().replace('\\', "/");
        if rel_s.starts_with("utilities/") && !rel_s.ends_with('/') {
            out.push((rel_s, bytes.clone()));
        }
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out.dedup_by(|a, b| a.0 == b.0);
    out
}

fn materialize_utilities(
    building_root: &Path,
    utility_files: &[(String, Vec<u8>)],
) -> Result<Vec<String>, String> {
    if utility_files.is_empty() {
        return Ok(Vec::new());
    }
    let util_root = building_root.join("utilities");
    std::fs::create_dir_all(&util_root).map_err(|e| format!("mkdir utilities: {e}"))?;
    let mut written = Vec::new();
    for (rel, bytes) in utility_files {
        let dest = if rel.eq_ignore_ascii_case("utility_bills_monthly.csv")
            || rel.ends_with("/utility_bills_monthly.csv")
        {
            util_root.join("electric").join("monthly_bills.csv")
        } else {
            util_root.join(rel.strip_prefix("utilities/").unwrap_or(rel))
        };
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
        }
        std::fs::write(&dest, bytes).map_err(|e| format!("write {}: {e}", dest.display()))?;
        written.push(
            dest.strip_prefix(building_root)
                .unwrap_or(&dest)
                .display()
                .to_string(),
        );
    }
    let manifest = json!({
        "schema_version": "utilities_v1",
        "electric": { "monthly_bills": "utilities/electric/monthly_bills.csv" },
    });
    std::fs::write(
        util_root.join("manifest.json"),
        serde_json::to_string_pretty(&manifest).unwrap_or_default(),
    )
    .map_err(|e| format!("utilities manifest: {e}"))?;
    Ok(written)
}

/// Extract `{point/role → csv column}` pairs for one equipment from any accepted
/// map JSON shape: full package map (`equip`/`equipment`/`devices`/`role_map`),
/// single-equip `{equipType, points: {…}}`, or a flat role → column object.
fn points_from_map_json(map: &Value, equip_id: &str) -> Option<BTreeMap<String, String>> {
    fn string_map(v: &Value) -> Option<BTreeMap<String, String>> {
        let obj = v.as_object()?;
        if obj.is_empty() {
            return None;
        }
        let mut out = BTreeMap::new();
        for (k, val) in obj {
            out.insert(k.clone(), val.as_str()?.to_string());
        }
        Some(out)
    }
    fn block_points(block: &Value) -> Option<BTreeMap<String, String>> {
        for key in ["points", "column_roles", "roles"] {
            if let Some(p) = block.get(key).and_then(string_map) {
                return Some(p);
            }
        }
        None
    }
    let obj = map.as_object()?;
    for key in ["equip", "equipment", "devices", "role_map"] {
        if let Some(blocks) = obj.get(key).and_then(|v| v.as_object()) {
            if let Some(block) = blocks.get(equip_id) {
                return block_points(block).or_else(|| string_map(block));
            }
            // Full-document map that doesn't mention this equipment.
            if !blocks.is_empty() {
                return None;
            }
        }
    }
    if let Some(p) = block_points(map) {
        return Some(p);
    }
    // Flat role → column object (ignore metadata keys).
    let meta = [
        "schema_version",
        "version",
        "building",
        "building_id",
        "siteRef",
        "site_id",
        "site",
        "generated_by",
        "notes",
        "units",
        "equipType",
        "equipment_type",
        "device",
    ];
    let flat: Map<String, Value> = obj
        .iter()
        .filter(|(k, _)| !meta.contains(&k.as_str()))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    string_map(&Value::Object(flat))
}

struct EquipmentPlan {
    equipment_id: String,
    dir: PathBuf,
    headers: Vec<String>,
    roles: BTreeMap<String, String>,
    map_source: String,
    equipment_type: Option<String>,
    parent_ahu: Option<String>,
}

fn csv_headers(bytes: &[u8]) -> Result<Vec<String>, String> {
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_reader(bytes);
    Ok(rdr
        .headers()
        .map_err(|e| format!("history_wide.csv headers: {e}"))?
        .iter()
        .map(|h| h.trim().to_string())
        .collect())
}

/// Convert map-file points (point/role name → CSV column) to column → cookbook role.
///
/// Every referenced column must exist in the history header. An empty result is
/// a preflight failure: the importer does not install a package and then discover
/// the gap during historian seeding.
fn roles_for_equipment(
    points: &BTreeMap<String, String>,
    headers: &[String],
    equip_id: &str,
) -> Result<BTreeMap<String, String>, Vec<String>> {
    let mut out = BTreeMap::new();
    let mut problems = Vec::new();
    for (point, column) in points {
        if point.trim().is_empty() || column.trim().is_empty() {
            problems.push(format!(
                "{equip_id}: map entry has an empty point or column"
            ));
            continue;
        }
        if !headers.iter().any(|h| h == column.trim()) {
            problems.push(format!(
                "{equip_id}: map references column {column:?} not present in history_wide.csv"
            ));
            continue;
        }
        let role = haystack_point_to_role(point);
        if role.is_empty() || role == "ignore" {
            continue;
        }
        out.entry(column.trim().to_string()).or_insert(role);
    }
    if !problems.is_empty() {
        return Err(problems);
    }
    if out.is_empty() {
        return Err(vec![format!("{equip_id}: column map resolved no roles")]);
    }
    Ok(out)
}

fn write_columns_csv(
    path: &Path,
    headers: &[String],
    roles: &BTreeMap<String, String>,
) -> Result<(), String> {
    let mut body = String::from("column,role\n");
    for h in headers {
        if h == "timestamp_utc" || h == "timestamp" || h.is_empty() {
            continue;
        }
        let role = roles.get(h).map(String::as_str).unwrap_or("");
        let col = if h.contains(',') || h.contains('"') {
            format!("\"{}\"", h.replace('"', "\"\""))
        } else {
            h.clone()
        };
        body.push_str(&format!("{col},{role}\n"));
    }
    std::fs::write(path, body).map_err(|e| format!("write {}: {e}", path.display()))
}

/// Root for JSON sidecars (equipment type maps) shared with central.
fn sidecar_root() -> PathBuf {
    if let Some(p) = fdd_store::local_file_root_from_env() {
        return p;
    }
    workspace_dir().join(".cache/parquet")
}

/// Load `openfdd_package_v1` zip bytes: validate, materialize under
/// `workspace/data/csv_buildings/<building_id>.incoming/` for the central Timescale seed.
pub fn import_package_zip(zip_bytes: &[u8]) -> Value {
    let entries = match read_zip_entries(zip_bytes) {
        Ok(e) => e,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let prefix = match resolve_building_prefix(&entries) {
        Ok(p) => p,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let rel = |p: &Path| -> PathBuf {
        if prefix.as_os_str().is_empty() {
            p.to_path_buf()
        } else {
            p.strip_prefix(&prefix)
                .map(Path::to_path_buf)
                .unwrap_or_default()
        }
    };
    let in_building: BTreeMap<PathBuf, &Vec<u8>> = entries
        .iter()
        .filter(|(p, _)| prefix.as_os_str().is_empty() || p.starts_with(&prefix))
        .map(|(p, b)| (rel(p), b))
        .filter(|(p, _)| !p.as_os_str().is_empty())
        .collect();

    let manifest_raw: Value = match in_building
        .get(Path::new("manifest.json"))
        .ok_or("manifest.json missing".to_string())
        .and_then(|b| serde_json::from_slice(b).map_err(|e| format!("manifest.json: {e}")))
    {
        Ok(v) => v,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let manifest = match parse_manifest(&manifest_raw) {
        Ok(m) => m,
        Err(e) => return json!({"ok": false, "error": e}),
    };

    let mut warnings: Vec<String> = Vec::new();
    for p in in_building.keys() {
        if p.extension().map(|e| e == "zip").unwrap_or(false) {
            warnings.push(format!(
                "nested zip {:?} ignored (expand nested zips before upload)",
                p.display()
            ));
        }
    }

    let root_map: Option<Value> = in_building
        .get(Path::new("column_map.json"))
        .and_then(|b| serde_json::from_slice(b).ok());
    let session_config: Option<Value> = in_building
        .get(Path::new("session_config.json"))
        .and_then(|b| serde_json::from_slice(b).ok());

    // Discover equipment: any folder (depth 1-2) holding history_wide.csv.
    let mut equip_dirs: Vec<PathBuf> = in_building
        .keys()
        .filter(|p| {
            p.file_name()
                .map(|f| f == "history_wide.csv")
                .unwrap_or(false)
        })
        .filter_map(|p| p.parent().map(Path::to_path_buf))
        .filter(|d| !d.as_os_str().is_empty())
        .collect();
    equip_dirs.sort();
    equip_dirs.dedup();

    let mut plans: Vec<EquipmentPlan> = Vec::new();
    let mut missing_maps: Vec<String> = Vec::new();
    let mut bad_references: Vec<String> = Vec::new();
    let mut seen_leaf_ids: BTreeSet<String> = BTreeSet::new();
    for dir in &equip_dirs {
        let equip_id = dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("equipment")
            .to_string();
        let equip_id = match validate_id(&equip_id) {
            Ok(id) => id,
            Err(e) => {
                warnings.push(format!("{}: {e} — skipped", dir.display()));
                continue;
            }
        };
        if !seen_leaf_ids.insert(equip_id.clone()) {
            return json!({
                "ok": false,
                "error": format!(
                    "duplicate equipment id {equip_id:?} — two folders flatten to the same leaf name under the building root"
                ),
                "hint": "rename equipment folders so each leaf directory name is unique",
            });
        }
        let Some(history) = in_building.get(&dir.join("history_wide.csv")) else {
            warnings.push(format!(
                "{equip_id}: history_wide.csv disappeared after discovery — skipped"
            ));
            continue;
        };
        let headers = match csv_headers(history) {
            Ok(h) => h,
            Err(e) => {
                warnings.push(format!("{equip_id}: {e}"));
                continue;
            }
        };
        if !headers
            .iter()
            .any(|h| h == "timestamp_utc" || h == "timestamp")
        {
            warnings.push(format!(
                "{equip_id}: history_wide.csv missing timestamp_utc column — skipped"
            ));
            continue;
        }

        // Sibling map (first match wins), then root column_map.json supplement.
        let mut map_source = String::new();
        let mut points: Option<BTreeMap<String, String>> = None;
        let mut equipment_type: Option<String> = None;
        let mut parent_ahu: Option<String> = None;
        for name in [
            "history_wide.json",
            "history_wide.column_map.json",
            "column_map.json",
        ] {
            if let Some(bytes) = in_building.get(&dir.join(name)) {
                match serde_json::from_slice::<Value>(bytes) {
                    Ok(v) => {
                        if equipment_type.is_none() {
                            equipment_type =
                                crate::equipment_types::stamped_type_from_map_json(&v, &equip_id);
                        }
                        if parent_ahu.is_none() {
                            parent_ahu = crate::equipment_types::declared_parent_from_map_json(
                                &v, &equip_id,
                            );
                        }
                        points = points_from_map_json(&v, &equip_id);
                        if points.is_some() {
                            map_source = format!("{}/{name}", dir.display());
                            break;
                        }
                        warnings.push(format!("{equip_id}: {name} has no usable point map"));
                    }
                    Err(e) => warnings.push(format!("{equip_id}: {name}: {e}")),
                }
            }
        }
        if equipment_type.is_none() {
            if let Some(root) = &root_map {
                equipment_type =
                    crate::equipment_types::stamped_type_from_map_json(root, &equip_id);
            }
        }
        if parent_ahu.is_none() {
            if let Some(root) = &root_map {
                parent_ahu = crate::equipment_types::declared_parent_from_map_json(root, &equip_id);
            }
        }
        if points.is_none() {
            if let Some(root) = &root_map {
                points = points_from_map_json(root, &equip_id);
                if points.is_some() {
                    map_source = "column_map.json (package root)".into();
                }
            }
        }

        let roles = match &points {
            Some(p) => match roles_for_equipment(p, &headers, &equip_id) {
                Ok(roles) => roles,
                Err(problems) => {
                    bad_references.extend(problems);
                    continue;
                }
            },
            None => {
                missing_maps.push(format!("{}/history_wide.csv", dir.display()));
                continue;
            }
        };
        plans.push(EquipmentPlan {
            equipment_id: equip_id,
            dir: dir.clone(),
            headers,
            roles,
            map_source,
            equipment_type,
            parent_ahu,
        });
    }

    if !missing_maps.is_empty() || !bad_references.is_empty() {
        return json!({
            "ok": false,
            "error": "package rejected before install — column maps are missing or reference columns that are not in the history file",
            "missing_maps": missing_maps,
            "bad_references": bad_references,
            "hint": "each equipment folder, including weather, needs a column map whose columns exist in history_wide.csv. Nothing is written until every map resolves.",
        });
    }
    if plans.is_empty() {
        return json!({
            "ok": false,
            "error": "no equipment folders with history_wide.csv found in package",
            "warnings": warnings,
        });
    }

    // Materialize csv_buildings/<building_id>/ layout.
    let building_id = match validate_id(&manifest.building_id) {
        Ok(id) => id,
        Err(e) => {
            return json!({"ok": false, "error": format!("manifest building_id: {e}")});
        }
    };
    let data_root = workspace_dir().join("data").join("csv_buildings");
    // Timescale imports land in `<id>.incoming` until the historian transaction
    // commits. The live tree is not removed on a rejected or failed package.
    let building_root = data_root.join(format!("{building_id}.incoming"));
    let _ = std::fs::remove_dir_all(&building_root);
    if let Err(e) = std::fs::create_dir_all(&building_root) {
        abort_staged_package(&building_root);
        return json!({"ok": false, "error": format!("mkdir {}: {e}", building_root.display())});
    }
    let manifest_out = json!({
        "grid_minutes": manifest.grid_minutes,
        "export_metadata": {
            "source": "openfdd_package_v1",
            "schema_version": PACKAGE_SCHEMA,
            "building_id": manifest.building_id,
            "timezone": manifest.timezone,
            "notes": manifest.notes,
        }
    });
    if let Err(e) = std::fs::write(
        building_root.join("manifest.json"),
        serde_json::to_string_pretty(&manifest_out).unwrap_or_default(),
    ) {
        abort_staged_package(&building_root);
        return json!({"ok": false, "error": format!("manifest write: {e}")});
    }
    if let Some(cfg) = &session_config {
        let _ = std::fs::write(
            building_root.join("session_config.json"),
            serde_json::to_string_pretty(cfg).unwrap_or_default(),
        );
        // Honor packaged session config (#515). Invalid configs only warn — never
        // block ingest. The staged config activates only after the historian commit.
        match crate::fdd::session_config::normalize_session_config(cfg) {
            Ok((_, mut cfg_warnings)) => {
                warnings.append(&mut cfg_warnings);
            }
            Err(e) => warnings.push(format!("session_config.json invalid: {e}")),
        }
    }

    let utility_files = collect_wrapper_utility_files(&entries, &prefix);
    let utilities_written = match materialize_utilities(&building_root, &utility_files) {
        Ok(paths) => paths,
        Err(e) => {
            warnings.push(format!("utilities ingest: {e}"));
            Vec::new()
        }
    };

    let stamped_types: BTreeMap<String, String> = plans
        .iter()
        .filter_map(|plan| {
            plan.equipment_type
                .as_ref()
                .map(|t| (plan.equipment_id.clone(), t.clone()))
        })
        .collect();
    if !stamped_types.is_empty() {
        match serde_json::to_string_pretty(&stamped_types) {
            Ok(body) => {
                if let Err(e) = std::fs::write(
                    building_root.join(crate::equipment_types::EQUIPMENT_TYPES_FILE),
                    body,
                ) {
                    warnings.push(format!("equipment type registry not materialized: {e}"));
                }
            }
            Err(e) => warnings.push(format!("equipment type registry serialize: {e}")),
        }
    }

    // Haystack RDF C2 (#1000): optional versioned semantic metadata. Absent on
    // old ZIPs — never fabricate. Invalid sidecar keeps any prior revision.
    let semantic_meta_result = crate::csv_ingest::semantic_meta::import_from_package_map(
        &building_root,
        &building_id,
        &in_building,
        &mut warnings,
    );

    let known_ids: std::collections::BTreeSet<&str> =
        plans.iter().map(|p| p.equipment_id.as_str()).collect();
    let mut parents_out: BTreeMap<String, String> = BTreeMap::new();
    let mut equipment_report = Vec::new();
    for plan in &plans {
        let eq_dir = building_root.join(plan.dir.file_name().unwrap_or_default());
        if let Err(e) = std::fs::create_dir_all(&eq_dir) {
            abort_staged_package(&building_root);
            return json!({"ok": false, "error": format!("mkdir {}: {e}", eq_dir.display())});
        }
        let history = match in_building.get(&plan.dir.join("history_wide.csv")) {
            Some(bytes) => bytes,
            None => {
                abort_staged_package(&building_root);
                return json!({
                    "ok": false,
                    "error": format!("history bytes missing for {}", plan.equipment_id),
                });
            }
        };
        if let Err(e) = std::fs::write(eq_dir.join("history_wide.csv"), history) {
            abort_staged_package(&building_root);
            return json!({"ok": false, "error": format!("history write: {e}")});
        }
        if let Err(e) = write_columns_csv(&eq_dir.join("columns.csv"), &plan.headers, &plan.roles) {
            abort_staged_package(&building_root);
            return json!({"ok": false, "error": e});
        }
        let parent = plan
            .parent_ahu
            .as_deref()
            .filter(|parent| known_ids.contains(*parent) && *parent != plan.equipment_id.as_str());
        if let Some(parent) = parent {
            parents_out.insert(plan.equipment_id.clone(), parent.to_string());
        }
        if plan.equipment_type.is_some() || parent.is_some() {
            let mut meta = serde_json::Map::new();
            meta.insert("equipment_id".into(), json!(plan.equipment_id));
            if let Some(raw_type) = plan.equipment_type.as_deref() {
                meta.insert("equipType".into(), json!(raw_type));
                meta.insert(
                    "canonical_kind".into(),
                    json!(crate::equipment_types::canonical_kind(raw_type)),
                );
            }
            if let Some(parent) = parent {
                meta.insert("parentAhu".into(), json!(parent));
            }
            let _ = std::fs::write(
                eq_dir.join("equipment.json"),
                serde_json::to_string_pretty(&Value::Object(meta)).unwrap_or_default(),
            );
        }
        let unmapped: Vec<&String> = plan
            .headers
            .iter()
            .filter(|h| *h != "timestamp_utc" && *h != "timestamp" && !plan.roles.contains_key(*h))
            .collect();
        equipment_report.push(json!({
            "equipment_id": plan.equipment_id,
            "column_count": plan.headers.len().saturating_sub(1),
            "roles": plan.roles,
            "unmapped_columns": unmapped,
            "map_source": plan.map_source,
            "equipment_type": plan.equipment_type,
        }));
    }

    if !parents_out.is_empty() {
        match serde_json::to_string_pretty(&parents_out) {
            Ok(body) => {
                if let Err(e) = std::fs::write(
                    building_root.join(crate::equipment_types::EQUIPMENT_PARENTS_FILE),
                    body,
                ) {
                    warnings.push(format!("equipment parent registry not materialized: {e}"));
                }
            }
            Err(e) => warnings.push(format!("equipment parent registry serialize: {e}")),
        }
    }

    // Files stay under `<id>.incoming` until central commits the Timescale seed.
    let equipment_written = equipment_report.len();
    json!({
        "ok": true,
        "schema_version": PACKAGE_SCHEMA,
        "building_id": building_id,
        "grid_minutes": manifest.grid_minutes,
        "poll_seconds": manifest.grid_minutes.saturating_mul(60),
        "timezone": manifest.timezone,
        "equipment": equipment_report,
        "equipment_written": equipment_written,
        "total_rows": 0,
        "total_ms": 0,
        "out_dir": Value::Null,
        "package_root": building_root.display().to_string(),
        "session_config": session_config,
        "utilities_written": utilities_written,
        "semantic_meta": semantic_meta_result,
        "warnings": warnings,
        "historian": "timescale",
        "needs_timescale_seed": true,
        "staged": true,
        "dual_write": false,
    })
}

fn extract_package_zip_bytes(content_type: &str, body: &[u8]) -> Result<Vec<u8>, String> {
    let ct = content_type.to_ascii_lowercase();
    let zip_bytes: Vec<u8> =
        if ct.contains("multipart/form-data") || ct.contains("application/json") {
            // Multipart must go through the binary-safe parser: lossy UTF-8 corrupts zips.
            let parsed = if ct.contains("multipart/form-data") {
                super::upload::parse_multipart_files(content_type, body)
            } else {
                super::upload::parse_upload(content_type, body)
            };
            let (files, _sid) = parsed?;
            let Some((_, bytes)) = files
                .into_iter()
                .find(|(name, _)| name.to_lowercase().ends_with(".zip"))
            else {
                return Err("no .zip file in upload".into());
            };
            bytes
        } else {
            body.to_vec()
        };
    if zip_bytes.is_empty() {
        return Err("empty upload".into());
    }
    Ok(zip_bytes)
}

/// Peek `manifest.json` `building_id` before package write (Wave O1 MT ACL).
///
/// Reads only package-manifest zip members (bounded) — does **not** extract the
/// full archive (#1127 P2). Full extraction happens once inside the import worker.
pub fn peek_package_building_id(content_type: &str, body: &[u8]) -> Result<String, String> {
    let zip_bytes = extract_package_zip_bytes(content_type, body)?;
    let raw = read_package_manifest_bytes(&zip_bytes)?;
    let manifest_raw: Value =
        serde_json::from_slice(&raw).map_err(|e| format!("manifest.json: {e}"))?;
    let manifest = parse_manifest(&manifest_raw)?;
    validate_id(&manifest.building_id)
}

/// Extract only `**/manifest.json` package roots from a zip (no full tree).
fn read_package_manifest_bytes(bytes: &[u8]) -> Result<Vec<u8>, String> {
    let cursor = std::io::Cursor::new(bytes);
    let mut archive =
        zip::ZipArchive::new(cursor).map_err(|e| format!("not a readable zip: {e}"))?;
    if archive.len() > max_entries() {
        return Err(format!(
            "zip has {} entries; cap is {} (OPENFDD_MAX_ENTRIES)",
            archive.len(),
            max_entries()
        ));
    }
    const MANIFEST_PEEK_CAP: u64 = 1024 * 1024; // 1 MiB manifest ceiling
    let mut candidates: Vec<(usize, PathBuf)> = Vec::new();
    for i in 0..archive.len() {
        let entry = archive
            .by_index(i)
            .map_err(|e| format!("zip entry {i}: {e}"))?;
        if entry.is_dir() {
            continue;
        }
        let entry_name = entry
            .name()
            .map_err(|e| format!("bad zip entry name: {e}"))?
            .to_string();
        if zip_entry_is_symlink(&entry) {
            return Err(format!("symlink entries are not allowed: {entry_name}"));
        }
        let path = safe_member_path(&entry_name)?;
        if path
            .file_name()
            .map(|f| f == "manifest.json")
            .unwrap_or(false)
        {
            candidates.push((i, path));
        }
    }
    if candidates.is_empty() {
        return Err("manifest.json missing".into());
    }
    // Prefer shallowest package manifest (root first, then nested).
    candidates.sort_by_key(|(_, p)| p.components().count());
    for (idx, path) in candidates {
        let mut entry = archive
            .by_index(idx)
            .map_err(|e| format!("zip entry {}: {e}", path.display()))?;
        let declared = entry.size();
        if declared > MANIFEST_PEEK_CAP {
            return Err(format!(
                "manifest.json too large for peek ({} bytes > {MANIFEST_PEEK_CAP})",
                declared
            ));
        }
        let mut buf = Vec::with_capacity(declared as usize);
        entry
            .read_to_end(&mut buf)
            .map_err(|e| format!("zip entry {:?}: {e}", path.display()))?;
        if (buf.len() as u64) > MANIFEST_PEEK_CAP {
            return Err("manifest.json expanded past peek cap".into());
        }
        if is_package_manifest(&buf) {
            return Ok(buf);
        }
    }
    Err("manifest.json missing openfdd_package_v1 marker".into())
}

/// HTTP entry: multipart / JSON base64 / raw zip body.
pub fn import_package_handler(content_type: &str, body: &[u8]) -> Value {
    let zip_bytes = match extract_package_zip_bytes(content_type, body) {
        Ok(b) => b,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    import_package_zip(&zip_bytes)
}

/// Append hourly history into an existing package. JSON:
/// `{ "confirm": true, "building_id": "...", "equipment_id": "...", "csv": "header\\n..." }`
/// or `{ "confirm": true, "building_id": "...", "files": [{ "equipment_id", "csv" }] }`.
/// ZIP body is also accepted (same layout as package import, merged not replaced).
pub fn append_package_handler(content_type: &str, body: &[u8]) -> Value {
    let ct = content_type.to_ascii_lowercase();
    if ct.contains("application/json") {
        let v: Value = match serde_json::from_slice(body) {
            Ok(v) => v,
            Err(e) => return json!({"ok": false, "error": format!("json: {e}")}),
        };
        return append_package_json(&v);
    }
    if ct.contains("multipart/form-data") || body.starts_with(b"PK") {
        let zip_bytes: Vec<u8> = if ct.contains("multipart/form-data") {
            let parsed = super::upload::parse_multipart_files(content_type, body);
            match parsed {
                Ok((files, _)) => files
                    .into_iter()
                    .find(|(n, _)| n.to_lowercase().ends_with(".zip"))
                    .map(|(_, b)| b)
                    .unwrap_or_default(),
                Err(e) => return json!({"ok": false, "error": e}),
            }
        } else {
            body.to_vec()
        };
        return append_package_zip(&zip_bytes);
    }
    json!({"ok": false, "error": "send application/json or a package zip"})
}

fn append_package_json(body: &Value) -> Value {
    if body.get("confirm").and_then(|v| v.as_bool()) != Some(true) {
        return json!({"ok": false, "error": "confirm:true required"});
    }
    let building_id = match validate_id(
        body.get("building_id")
            .and_then(|v| v.as_str())
            .unwrap_or(""),
    ) {
        Ok(id) => id,
        Err(e) => return json!({"ok": false, "error": format!("building_id: {e}")}),
    };
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let building_root = data_root.join(&building_id);
    if !building_root.is_dir() {
        return json!({
            "ok": false,
            "error": format!("building {building_id} not ingested — seed with POST /api/csv/import/package first"),
        });
    }
    let mut files: Vec<(String, String)> = Vec::new();
    if let Some(arr) = body.get("files").and_then(|v| v.as_array()) {
        for f in arr {
            let eq = f.get("equipment_id").and_then(|v| v.as_str()).unwrap_or("");
            let csv = f.get("csv").and_then(|v| v.as_str()).unwrap_or("");
            files.push((eq.to_string(), csv.to_string()));
        }
    } else {
        let eq = body
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let csv = body.get("csv").and_then(|v| v.as_str()).unwrap_or("");
        files.push((eq.to_string(), csv.to_string()));
    }
    let mut merges = Vec::new();
    let mut touched: Vec<String> = Vec::new();
    for (eq, csv) in files {
        let equipment_id = match validate_id(&eq) {
            Ok(id) => id,
            Err(e) => return json!({"ok": false, "error": format!("equipment_id: {e}")}),
        };
        if csv.trim().is_empty() {
            return json!({"ok": false, "error": "csv required"});
        }
        let eq_dir = building_root.join(&equipment_id);
        let hist = eq_dir.join("history_wide.csv");
        if !hist.is_file() {
            return json!({
                "ok": false,
                "error": format!("equipment {equipment_id} missing history_wide.csv"),
            });
        }
        // Stream-merge from path (do not pre-load full history into a String).
        match fdd_store::merge_history_wide_text(&hist, &csv, &hist, None) {
            Ok(r) => {
                merges.push(json!({
                    "equipment_id": equipment_id,
                    "rows_in": r.rows_in,
                    "rows_added": r.rows_added,
                    "rows_duped": r.rows_duped,
                    "rows_out": r.rows_out,
                    "ts_min": r.ts_min,
                    "ts_max": r.ts_max,
                    "incoming_resident_rows": r.incoming_resident_rows,
                }));
                touched.push(equipment_id);
            }
            Err(e) => return json!({"ok": false, "error": e.to_string()}),
        }
    }
    json!({
        "ok": true,
        "building_id": building_id,
        "merges": merges,
        "equipment_written": touched.len(),
        "total_rows": 0,
        "scoped_equipment": touched,
        "historian": "timescale",
        "needs_timescale_seed": true,
        "package_root": building_root.display().to_string(),
        "dual_write": false,
    })
}

fn append_package_zip(zip_bytes: &[u8]) -> Value {
    json!({
        "ok": false,
        "error": "zip append: POST application/json with confirm, building_id, equipment_id, csv (hourly chunk). Full zip re-import remains POST /api/csv/import/package",
        "hint": format!("zip_bytes={}", zip_bytes.len()),
    })
}

/// Update role assignments for one ingested package equipment and re-ingest.
/// Body: `{"building_id": "...", "equipment_id": "...", "roles": {"column": "role"}}`.
pub fn update_package_roles_handler(body: &Value) -> Value {
    let building_id = match validate_id(
        body.get("building_id")
            .and_then(|v| v.as_str())
            .unwrap_or(""),
    ) {
        Ok(id) => id,
        Err(e) => return json!({"ok": false, "error": format!("building_id: {e}")}),
    };
    let equipment_id = match validate_id(
        body.get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or(""),
    ) {
        Ok(id) => id,
        Err(e) => return json!({"ok": false, "error": format!("equipment_id: {e}")}),
    };
    let Some(roles_obj) = body.get("roles").and_then(|v| v.as_object()) else {
        return json!({"ok": false, "error": "roles object required"});
    };
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let building_root = data_root.join(&building_id);
    let eq_dir = match find_equipment_dir(&building_root, &equipment_id) {
        Some(d) => d,
        None => {
            return json!({
                "ok": false,
                "error": format!("equipment {equipment_id:?} not found under {}", building_root.display()),
            })
        }
    };
    let history = eq_dir.join("history_wide.csv");
    let headers = match std::fs::read(&history)
        .map_err(|e| format!("read {}: {e}", history.display()))
        .and_then(|b| csv_headers(&b))
    {
        Ok(h) => h,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let mut roles: BTreeMap<String, String> = BTreeMap::new();
    let mut ignored: Vec<String> = Vec::new();
    for (col, role) in roles_obj {
        let role = role.as_str().unwrap_or("").trim();
        if role.is_empty() {
            continue;
        }
        if headers.iter().any(|h| h == col) {
            roles.insert(col.clone(), fdd_core::normalize_role(role));
        } else {
            ignored.push(col.clone());
        }
    }
    if let Err(e) = write_columns_csv(&eq_dir.join("columns.csv"), &headers, &roles) {
        return json!({"ok": false, "error": e});
    }
    // Central remaps the SQL roles from columns.csv.
    json!({
        "ok": true,
        "building_id": building_id,
        "equipment_id": equipment_id,
        "roles": roles,
        "ignored_columns": ignored,
        "scoped_equipment": [equipment_id],
        "package_root": building_root.display().to_string(),
        "historian": "timescale",
        "needs_timescale_remap": true,
        "equipment_written": 0,
        "total_rows": 0,
    })
}

fn find_equipment_dir(building_root: &Path, equipment_id: &str) -> Option<PathBuf> {
    // equipment_id is already validate_id()'d — exactly one safe path component.
    let direct = building_root.join(equipment_id);
    if direct.join("history_wide.csv").is_file() {
        return Some(direct);
    }
    for e in walkdir::WalkDir::new(building_root)
        .min_depth(1)
        .max_depth(3)
        .into_iter()
        .flatten()
    {
        if e.file_type().is_dir()
            && e.file_name().to_str() == Some(equipment_id)
            && e.path().join("history_wide.csv").is_file()
        {
            return Some(e.path().to_path_buf());
        }
    }
    None
}

/// Load package stamps from csv_buildings and/or Parquet `equipment_types.json`.
fn load_stamped_types_for_building(
    building_id: &str,
    building_root: Option<&Path>,
) -> BTreeMap<String, String> {
    let mut types = BTreeMap::new();
    if let Some(root) = building_root {
        let path = root.join(crate::equipment_types::EQUIPMENT_TYPES_FILE);
        if let Ok(text) = std::fs::read_to_string(path) {
            if let Ok(m) = serde_json::from_str::<BTreeMap<String, String>>(&text) {
                types.extend(m);
            }
        }
    }
    for (k, v) in crate::equipment_types::load_type_map(&sidecar_root(), Some(building_id)) {
        types.entry(k).or_insert(v);
    }
    types
}

/// Resolve display type + provenance for mapping inventory (DM-04).
fn resolve_mapping_equipment_type(
    equipment_id: &str,
    stamped_types: &BTreeMap<String, String>,
) -> (String, Option<String>, &'static str) {
    let raw = stamped_types.get(equipment_id).cloned();
    let display =
        crate::equipment_types::api_equipment_type_for(equipment_id, raw.as_deref()).to_string();
    let source = crate::equipment_types::equipment_type_source(raw.as_deref());
    (display, raw, source)
}

/// Parent AHU from package metadata. Id tokens are not a parent.
///
/// The declared id must equal a sibling exactly (`AHU_1` does not select `AHU_10`).
fn package_parent_ahu(eq_dir: &Path, equipment_id: &str, siblings: &[String]) -> Option<String> {
    let mut declared = None;
    for name in [
        "equipment.json",
        "history_wide.json",
        "history_wide.column_map.json",
        "column_map.json",
    ] {
        let path = eq_dir.join(name);
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let Ok(map) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        if let Some(parent) =
            crate::equipment_types::declared_parent_from_map_json(&map, equipment_id)
        {
            declared = Some(parent);
            break;
        }
    }
    if declared.is_none() {
        if let Some(root) = eq_dir.parent() {
            let path = root.join(crate::equipment_types::EQUIPMENT_PARENTS_FILE);
            if let Ok(text) = std::fs::read_to_string(path) {
                if let Ok(map) = serde_json::from_str::<BTreeMap<String, String>>(&text) {
                    declared = map.get(equipment_id).cloned();
                }
            }
        }
    }
    let declared = declared?;
    siblings
        .iter()
        .find(|s| s.as_str() == declared.as_str() && s.as_str() != equipment_id)
        .cloned()
}

/// Raw columns.csv parse — empty roles stay empty (no silent inference for the editor).
fn read_columns_csv_raw(path: &Path) -> Result<(Vec<String>, BTreeMap<String, String>), String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_reader(text.as_bytes());
    let headers = rdr
        .headers()
        .map_err(|e| format!("columns.csv headers: {e}"))?
        .clone();
    let col_idx = headers
        .iter()
        .position(|h| matches!(h.trim().to_ascii_lowercase().as_str(), "column" | "col"));
    let role_idx = headers.iter().position(|h| {
        matches!(
            h.trim().to_ascii_lowercase().as_str(),
            "role" | "point_role"
        )
    });
    let Some(col_idx) = col_idx else {
        return Err(format!(
            "columns.csv missing column header: {}",
            path.display()
        ));
    };
    let mut order = Vec::new();
    let mut roles = BTreeMap::new();
    for rec in rdr.records() {
        let rec = rec.map_err(|e| format!("columns.csv row: {e}"))?;
        let column = rec.get(col_idx).unwrap_or("").trim().to_string();
        if column.is_empty() {
            continue;
        }
        order.push(column.clone());
        let role = role_idx
            .and_then(|i| rec.get(i))
            .unwrap_or("")
            .trim()
            .to_string();
        if !role.is_empty() {
            roles.insert(column, fdd_core::normalize_role(&role));
        }
    }
    Ok((order, roles))
}

fn sampling_health(history_path: &Path) -> Value {
    match std::fs::read(history_path) {
        Ok(bytes) => {
            let mut rdr = csv::ReaderBuilder::new()
                .has_headers(true)
                .from_reader(bytes.as_slice());
            let mut count = 0u64;
            let mut first: Option<String> = None;
            let mut last: Option<String> = None;
            let headers = rdr.headers().ok().cloned();
            let ts_idx = headers.as_ref().and_then(|h| {
                h.iter().position(|c| {
                    matches!(
                        c.trim().to_ascii_lowercase().as_str(),
                        "timestamp_utc" | "timestamp" | "ts" | "time"
                    )
                })
            });
            for rec in rdr.records().flatten() {
                count += 1;
                if let Some(i) = ts_idx {
                    if let Some(ts) = rec.get(i).map(str::trim).filter(|s| !s.is_empty()) {
                        if first.is_none() {
                            first = Some(ts.to_string());
                        }
                        last = Some(ts.to_string());
                    }
                }
            }
            json!({
                "row_count": count,
                "first_timestamp": first,
                "last_timestamp": last,
                "ok": count > 0,
            })
        }
        Err(e) => json!({
            "ok": false,
            "error": format!("history_wide.csv: {e}"),
            "row_count": 0,
        }),
    }
}

fn list_equipment_ids(building_root: &Path) -> Vec<String> {
    let mut ids = Vec::new();
    for e in walkdir::WalkDir::new(building_root)
        .min_depth(1)
        .max_depth(3)
        .into_iter()
        .flatten()
    {
        if e.file_type().is_dir() && e.path().join("history_wide.csv").is_file() {
            if let Some(name) = e.file_name().to_str() {
                if name != "weather" {
                    ids.push(name.to_string());
                }
            }
        }
    }
    ids.sort();
    ids.dedup();
    ids
}

/// `GET /api/csv/import/package/mapping` — inventory + validation for ingested package equipment.
///
/// Query via JSON body or caller-supplied ids: `building_id` required; `equipment_id` optional.
/// Does not invent mappings for blank roles (gap stays visible).
pub fn get_package_mapping_handler(building_id: &str, equipment_id: Option<&str>) -> Value {
    let preferred = std::env::var("OPENFDD_TENANT_ID")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    get_package_mapping_handler_scoped(building_id, equipment_id, preferred.as_deref())
}

/// Same inventory as [`get_package_mapping_handler`] with the caller's read tenant.
///
/// HTTP mapping passes the session tenant (or the control-plane owner). The
/// process `OPENFDD_TENANT_ID` is not the multi-tenant write partition.
pub fn get_package_mapping_handler_scoped(
    building_id: &str,
    equipment_id: Option<&str>,
    preferred_tenant: Option<&str>,
) -> Value {
    let building_id = match validate_id(building_id) {
        Ok(id) => id,
        Err(e) => return json!({"ok": false, "error": format!("building_id: {e}")}),
    };
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let building_root = data_root.join(&building_id);
    if !building_root.is_dir() {
        // Portal sites have no csv_buildings tree. Inventory is Timescale.
        return mapping_from_historian_equipment(&building_id, equipment_id, preferred_tenant);
    }

    let all_ids = list_equipment_ids(&building_root);
    let stamped_types = load_stamped_types_for_building(&building_id, Some(&building_root));
    let selected: Vec<String> = match equipment_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(eq) => match validate_id(eq) {
            Ok(id) => {
                if !all_ids.iter().any(|x| x == &id) {
                    // Partial CSV package trees omit historian-only equips (e.g. CS_ELEC_METER).
                    return mapping_from_historian_equipment(
                        &building_id,
                        Some(&id),
                        preferred_tenant,
                    );
                }
                vec![id]
            }
            Err(e) => return json!({"ok": false, "error": format!("equipment_id: {e}")}),
        },
        None => all_ids.clone(),
    };

    let session = crate::fdd::session_config::get_session_config_scoped(
        &crate::fdd::session_config::SessionConfigScope::new(
            preferred_tenant,
            Some(building_id.as_str()),
        ),
    );
    let unit_system = session
        .get("config")
        .and_then(|c| c.get("unit_system"))
        .cloned()
        .unwrap_or(json!("imperial"));
    let session_role_map = session
        .get("config")
        .and_then(|c| c.get("role_map"))
        .cloned()
        .unwrap_or(json!({}));

    let mut equipment = Vec::new();
    let mut blocker_count = 0usize;
    let mut warning_count = 0usize;

    for eq_id in &selected {
        let Some(eq_dir) = find_equipment_dir(&building_root, eq_id) else {
            continue;
        };
        let (eq_type, eq_type_raw, eq_type_source) =
            resolve_mapping_equipment_type(eq_id, &stamped_types);
        let parent_ahu = package_parent_ahu(&eq_dir, eq_id, &all_ids);
        let parent_ahu_source: Option<&'static str> = parent_ahu.as_ref().map(|_| "package");
        let cols_path = eq_dir.join("columns.csv");
        let history_path = eq_dir.join("history_wide.csv");
        let (columns_order, roles) = match read_columns_csv_raw(&cols_path) {
            Ok(v) => v,
            Err(e) => {
                blocker_count += 1;
                equipment.push(json!({
                    "equipment_id": eq_id,
                    "equipment_type": eq_type,
                    "equipment_type_raw": eq_type_raw,
                    "equipment_type_source": eq_type_source,
                    "parent_ahu": parent_ahu,
                    "parent_ahu_source": parent_ahu_source,
                    "ok": false,
                    "error": e,
                    "blockers": ["columns.csv unreadable"],
                    "warnings": [],
                }));
                continue;
            }
        };

        let mut role_to_cols: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for (col, role) in &roles {
            role_to_cols
                .entry(role.clone())
                .or_default()
                .push(col.clone());
        }
        let ambiguous: BTreeMap<String, Vec<String>> = role_to_cols
            .into_iter()
            .filter(|(_, cols)| cols.len() > 1)
            .collect();

        let unmapped: Vec<String> = columns_order
            .iter()
            .filter(|c| !roles.contains_key(*c))
            .cloned()
            .collect();

        let mut blockers = Vec::new();
        let mut warnings = Vec::new();
        if roles.is_empty() {
            blockers.push("no roles mapped — FDD rules will skip this equipment".to_string());
        }
        if !ambiguous.is_empty() {
            blockers.push(format!(
                "{} ambiguous role(s) assigned to multiple columns",
                ambiguous.len()
            ));
        }
        if !unmapped.is_empty() {
            warnings.push(format!("{} unmapped column(s)", unmapped.len()));
        }
        let kind = crate::equipment_types::kind_for(eq_id, eq_type_raw.as_deref());
        if kind == "vav" && parent_ahu.is_none() {
            warnings.push(
                "VAV has no package parent AHU — set parentAhu on the equipment map when the relationship is known"
                    .into(),
            );
        }

        blocker_count += blockers.len();
        warning_count += warnings.len();

        let column_rows: Vec<Value> = columns_order
            .iter()
            .map(|col| {
                let role = roles.get(col).cloned().unwrap_or_default();
                let status = if role.is_empty() {
                    "unmapped"
                } else if ambiguous.get(&role).is_some_and(|c| c.len() > 1) {
                    "ambiguous"
                } else {
                    "mapped"
                };
                json!({
                    "column": col,
                    "role": role,
                    "status": status,
                })
            })
            .collect();

        equipment.push(json!({
            "equipment_id": eq_id,
            "equipment_type": eq_type,
            "equipment_type_raw": eq_type_raw,
            "equipment_type_source": eq_type_source,
            "parent_ahu": parent_ahu,
            "parent_ahu_source": parent_ahu_source,
            "ok": blockers.is_empty(),
            "columns": column_rows,
            "roles": roles,
            "unmapped_columns": unmapped,
            "ambiguous_roles": ambiguous,
            "sampling": sampling_health(&history_path),
            "blockers": blockers,
            "warnings": warnings,
        }));
    }

    // Package trees can be a partial CSV rematerialization (for example an
    // air-handler-only fixture) while Timescale still holds the rest of the
    // site. Merge historian-only equipment so Data Model maps stay complete.
    let hist = mapping_from_historian_equipment(&building_id, equipment_id, preferred_tenant);
    if hist.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        let hist_equips = hist
            .get("equipment")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let mut known: std::collections::BTreeSet<String> = all_ids.iter().cloned().collect();
        for row in hist_equips {
            let Some(id) = row.get("equipment_id").and_then(|v| v.as_str()) else {
                continue;
            };
            if known.contains(id) {
                continue;
            }
            known.insert(id.to_string());
            equipment.push(row);
        }
        let mut ids: Vec<String> = known.into_iter().collect();
        ids.sort();
        let mut blocker_count = 0usize;
        let mut warning_count = 0usize;
        for row in &equipment {
            blocker_count += row
                .get("blockers")
                .and_then(|v| v.as_array())
                .map(|a| a.len())
                .unwrap_or(0);
            warning_count += row
                .get("warnings")
                .and_then(|v| v.as_array())
                .map(|a| a.len())
                .unwrap_or(0);
        }
        return json!({
            "ok": true,
            "building_id": building_id,
            "unit_system": unit_system,
            "equipment_ids": ids,
            "equipment": equipment,
            "session_role_map": session_role_map,
            "validation": {
                "blocker_count": blocker_count,
                "warning_count": warning_count,
                "equipment_count": equipment.len(),
            },
            "sources": ["csv_buildings", "historian"],
        });
    }

    json!({
        "ok": true,
        "building_id": building_id,
        "unit_system": unit_system,
        "equipment_ids": all_ids,
        "equipment": equipment,
        "session_role_map": session_role_map,
        "validation": {
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "equipment_count": equipment.len(),
        },
    })
}

const HISTORIAN_MAPPING_HINT: &str =
    "upload an openfdd_package_v1 zip or ingest the site through the Normal Framework portal";

const NF_TEMPLATE_SCHEMA: &str = "ofdd_portal_committed_model_v1";

const FORBIDDEN_TEMPLATE_KEYS: &[&str] = &[
    "url",
    "request_url",
    "requesturl",
    "http_method",
    "httpmethod",
    "http_verb",
    "httpverb",
    "authorization",
    "credential",
    "credentials",
    "secret",
    "password",
    "sql",
    "script",
];

/// One equipment row from the Timescale `equipment` + `role_map` tables.
///
/// `roles` is `openfdd_key` → role. Keys are exact. A role with two keys is
/// ambiguous and is not collapsed by prefix.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TimescaleInventoryEquipment {
    pub equipment_id: String,
    pub equip_type: Option<String>,
    pub roles: BTreeMap<String, String>,
}

/// Reads site inventory from Timescale. `tenant_id` is the caller's read
/// scope when the adapter partitions rows. The product table has no tenant
/// column; building id is the historian key, and NF metadata carries the owner.
pub trait TimescaleInventoryAdapter {
    fn equipment(
        &self,
        building_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<Vec<TimescaleInventoryEquipment>, String>;
}

/// NF model document the scoped consumer compiles. TTL is the ingest Turtle
/// snapshot. Template is `ofdd_portal_committed_model_v1` JSON.
pub enum NfMetadata<'a> {
    Ttl {
        turtle: &'a str,
        tenant_id: &'a str,
        provider_instance_id: &'a str,
        graph: &'a str,
    },
    Template(&'a str),
}

struct NfEquip {
    equipment_id: String,
    equip_type: String,
    roles: BTreeSet<String>,
}

struct NfModel {
    tenant_id: String,
    site_id: String,
    equipment: Vec<NfEquip>,
}

struct DatabaseTimescaleInventory;

impl TimescaleInventoryAdapter for DatabaseTimescaleInventory {
    fn equipment(
        &self,
        building_id: &str,
        _tenant_id: Option<&str>,
    ) -> Result<Vec<TimescaleInventoryEquipment>, String> {
        let url = std::env::var("OPENFDD_DATABASE_URL").unwrap_or_default();
        if url.trim().is_empty() {
            return Ok(Vec::new());
        }
        // A new thread has no Tokio context, so the query is safe from an
        // async worker and from spawn_blocking. The pool dies with the thread.
        // Connection failures stay a static message: driver errors can echo the URL.
        let building_id = building_id.to_string();
        let joined = std::thread::Builder::new()
            .name("openfdd-timescale-inventory".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .map_err(|_| "timescale inventory unavailable".to_string())?;
                rt.block_on(query_timescale_equipment(&building_id))
            })
            .map_err(|_| "timescale inventory unavailable".to_string())?;
        match joined.join() {
            Ok(result) => result,
            Err(_) => Err("timescale inventory unavailable".into()),
        }
    }
}

async fn query_timescale_equipment(
    building_id: &str,
) -> Result<Vec<TimescaleInventoryEquipment>, String> {
    let url = fdd_tsdb::database_url_from_env()
        .map_err(|_| "timescale inventory unavailable".to_string())?;
    let tsdb = fdd_tsdb::Tsdb::connect(&url)
        .await
        .map_err(|_| "timescale inventory unavailable".to_string())?;
    let rows = sqlx::query(
        r#"
        SELECT e.equipment_id,
               e.equip_type,
               r.openfdd_key,
               r.role
        FROM equipment e
        LEFT JOIN role_map r
          ON r.building_id = e.building_id
         AND r.equipment_id = e.equipment_id
        WHERE e.building_id = $1
        ORDER BY e.equipment_id, r.openfdd_key
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .map_err(|_| "timescale inventory unavailable".to_string())?;
    let mut grouped: BTreeMap<String, TimescaleInventoryEquipment> = BTreeMap::new();
    for row in rows {
        let id: String = row
            .try_get("equipment_id")
            .map_err(|_| "timescale inventory unavailable".to_string())?;
        if id.is_empty() {
            continue;
        }
        let equip_type = row
            .try_get::<Option<String>, _>("equip_type")
            .ok()
            .flatten()
            .filter(|value| !value.is_empty());
        let entry = grouped
            .entry(id.clone())
            .or_insert_with(|| TimescaleInventoryEquipment {
                equipment_id: id,
                equip_type: equip_type.clone(),
                roles: BTreeMap::new(),
            });
        if entry.equip_type.is_none() {
            entry.equip_type = equip_type;
        }
        let key = row
            .try_get::<Option<String>, _>("openfdd_key")
            .ok()
            .flatten()
            .filter(|value| !value.is_empty());
        let role = row
            .try_get::<Option<String>, _>("role")
            .ok()
            .flatten()
            .filter(|value| !value.is_empty());
        if let (Some(key), Some(role)) = (key, role) {
            entry.roles.insert(key, role);
        }
    }
    Ok(grouped.into_values().collect())
}

/// Historian inventory for Data Model export when no csv_buildings tree exists.
///
/// Equipment and roles come from Timescale. A missing database is an empty
/// inventory, not a directory scan.
fn mapping_from_historian_equipment(
    building_id: &str,
    equipment_id: Option<&str>,
    preferred_tenant: Option<&str>,
) -> Value {
    let inventory = DatabaseTimescaleInventory;
    let loaded = match inventory.equipment(building_id, preferred_tenant) {
        Ok(rows) => rows,
        Err(error) => {
            return json!({
                "ok": false,
                "error": error,
                "building_id": building_id,
            })
        }
    };
    mapping_from_timescale_rows(
        building_id,
        equipment_id,
        preferred_tenant,
        &loaded,
        None,
        "timescale",
    )
}

/// Compile NF metadata (TTL snapshot or committed-model template) and keep
/// only equipment that the Timescale adapter lists for this site.
///
/// A caller tenant that is not the document owner is denied before the
/// adapter is read. An absent caller tenant is the unscoped hub read.
pub fn nf_scoped_consumer(
    building_id: &str,
    equipment_id: Option<&str>,
    preferred_tenant: Option<&str>,
    metadata: NfMetadata<'_>,
    inventory: &dyn TimescaleInventoryAdapter,
) -> Value {
    let building_id = match validate_id(building_id) {
        Ok(id) => id,
        Err(error) => return json!({"ok": false, "error": format!("building_id: {error}")}),
    };
    let kind = match &metadata {
        NfMetadata::Ttl { .. } => "ttl",
        NfMetadata::Template(_) => "template",
    };
    let model = match metadata {
        NfMetadata::Ttl {
            turtle,
            tenant_id,
            provider_instance_id,
            graph,
        } => bindings_from_ttl(&building_id, turtle, tenant_id, provider_instance_id, graph),
        NfMetadata::Template(template) => bindings_from_template(&building_id, template),
    };
    let model = match model {
        Ok(model) => model,
        Err(error) => {
            return json!({
                "ok": false,
                "error": error,
                "building_id": building_id,
            })
        }
    };
    if model.site_id != building_id {
        return json!({
            "ok": false,
            "error": "NF metadata does not match the building",
            "building_id": building_id,
        });
    }
    if let Some(caller) = preferred_tenant.map(str::trim).filter(|s| !s.is_empty()) {
        if caller != model.tenant_id {
            return json!({
                "ok": false,
                "error": "foreign tenant cannot read this site",
                "code": "foreign_tenant",
                "building_id": building_id,
            });
        }
    }
    let tenant_filter = preferred_tenant
        .map(str::trim)
        .filter(|tenant| !tenant.is_empty());
    let loaded = match inventory.equipment(&building_id, tenant_filter) {
        Ok(rows) => rows,
        Err(error) => {
            return json!({
                "ok": false,
                "error": error,
                "building_id": building_id,
            })
        }
    };
    let scope = if tenant_filter.is_some() {
        "scoped"
    } else {
        "unscoped"
    };
    let mut body = mapping_from_timescale_rows(
        &building_id,
        equipment_id,
        preferred_tenant,
        &loaded,
        Some(&model),
        "nf_metadata",
    );
    if let Some(obj) = body.as_object_mut() {
        obj.insert("metadata".into(), json!(kind));
        obj.insert("scope".into(), json!(scope));
        obj.insert("consumer".into(), json!("nf_scoped"));
    }
    body
}

fn bindings_from_ttl(
    building_id: &str,
    turtle: &str,
    tenant_id: &str,
    provider_instance_id: &str,
    graph: &str,
) -> Result<NfModel, String> {
    validate_slug("tenant_id", tenant_id, 128)?;
    validate_slug("provider_instance_id", provider_instance_id, 128)?;
    let scope = IngestSparqlScope::new(tenant_id, building_id, graph, provider_instance_id);
    let rows = compile_bindings_from_snapshot(turtle, &scope).map_err(|error| {
        if error.contains("wrong-tenant")
            || error.contains("wrong-site")
            || error.contains("wrong-provider")
        {
            "NF metadata snapshot does not match the declared scope".to_string()
        } else {
            error
        }
    })?;
    let mut equipment: BTreeMap<String, NfEquip> = BTreeMap::new();
    for row in rows {
        if row.selection_status != "approved" || row.provisional {
            continue;
        }
        if row.site_id != building_id {
            return Err("NF metadata snapshot does not match the declared scope".into());
        }
        match equipment.get_mut(&row.equipment_id) {
            Some(equip) => {
                if equip.equip_type != row.equip_type {
                    return Err(format!("conflicting equip type on {}", row.equipment_id));
                }
                equip.roles.insert(row.canonical_role);
            }
            None => {
                equipment.insert(
                    row.equipment_id.clone(),
                    NfEquip {
                        equipment_id: row.equipment_id,
                        equip_type: row.equip_type,
                        roles: BTreeSet::from([row.canonical_role]),
                    },
                );
            }
        }
    }
    Ok(NfModel {
        tenant_id: tenant_id.to_string(),
        site_id: building_id.to_string(),
        equipment: equipment.into_values().collect(),
    })
}

fn bindings_from_template(building_id: &str, template: &str) -> Result<NfModel, String> {
    let value: Value = serde_json::from_str(template)
        .map_err(|error| format!("NF metadata template is not valid JSON: {error}"))?;
    reject_forbidden_template_keys(&value)?;
    let schema = value
        .get("schema")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if schema != NF_TEMPLATE_SCHEMA {
        return Err(format!(
            "NF metadata template schema is not {NF_TEMPLATE_SCHEMA}"
        ));
    }
    let tenant_id = required_template_slug(&value, "tenant_id")?;
    let site_id = required_template_slug(&value, "site_id")?;
    let _provider = required_template_slug(&value, "provider_instance_id")?;
    if site_id != building_id {
        return Err("NF metadata template site does not match the building".into());
    }
    let points = value
        .get("equipment")
        .and_then(Value::as_array)
        .ok_or_else(|| "NF metadata template is missing equipment".to_string())?;
    let mut equipment: BTreeMap<String, NfEquip> = BTreeMap::new();
    for item in points {
        let equipment_id = required_template_slug(item, "equipment_id")?;
        let equip_type = required_template_slug(item, "equip_type")?;
        let Some(point_rows) = item.get("points").and_then(Value::as_array) else {
            return Err(format!(
                "NF metadata template equipment {equipment_id} is missing points"
            ));
        };
        let mut roles = BTreeSet::new();
        for point in point_rows {
            if !point_is_active(point) {
                continue;
            }
            let role = required_template_slug(point, "canonical_role")?;
            roles.insert(role);
        }
        match equipment.get_mut(&equipment_id) {
            Some(equip) => {
                if equip.equip_type != equip_type {
                    return Err(format!("conflicting equip type on {equipment_id}"));
                }
                equip.roles.extend(roles);
            }
            None => {
                equipment.insert(
                    equipment_id.clone(),
                    NfEquip {
                        equipment_id,
                        equip_type,
                        roles,
                    },
                );
            }
        }
    }
    Ok(NfModel {
        tenant_id,
        site_id,
        equipment: equipment.into_values().collect(),
    })
}

fn point_is_active(point: &Value) -> bool {
    let approved = point
        .get("selection_status")
        .and_then(Value::as_str)
        .is_some_and(|status| status == "approved");
    let ready = point
        .get("fdd_ready")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let provisional = point
        .get("provisional")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    approved && ready && !provisional
}

fn required_template_slug(value: &Value, field: &str) -> Result<String, String> {
    let raw = value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .ok_or_else(|| format!("NF metadata template is missing {field}"))?;
    validate_slug(field, raw, 128)?;
    Ok(raw.to_string())
}

fn reject_forbidden_template_keys(value: &Value) -> Result<(), String> {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                let lower = key.to_ascii_lowercase();
                if FORBIDDEN_TEMPLATE_KEYS.iter().any(|name| *name == lower) {
                    return Err("NF metadata template contains a forbidden field".into());
                }
                reject_forbidden_template_keys(child)?;
            }
            Ok(())
        }
        Value::Array(items) => {
            for item in items {
                reject_forbidden_template_keys(item)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn mapping_from_timescale_rows(
    building_id: &str,
    equipment_id: Option<&str>,
    preferred_tenant: Option<&str>,
    loaded: &[TimescaleInventoryEquipment],
    model: Option<&NfModel>,
    type_source: &str,
) -> Value {
    let mut selected: Vec<&TimescaleInventoryEquipment> = loaded.iter().collect();
    if let Some(eq) = equipment_id.map(str::trim).filter(|s| !s.is_empty()) {
        match validate_id(eq) {
            Ok(id) => {
                selected.retain(|row| row.equipment_id == id);
                if selected.is_empty() {
                    return json!({
                        "ok": false,
                        "error": format!("equipment {id:?} not found under historian building {building_id}"),
                        "building_id": building_id,
                    });
                }
            }
            Err(error) => return json!({"ok": false, "error": format!("equipment_id: {error}")}),
        }
    }
    if let Some(model) = model {
        selected.retain(|row| {
            model
                .equipment
                .iter()
                .any(|equip| equip.equipment_id == row.equipment_id)
        });
    }
    if selected.is_empty() {
        return json!({
            "ok": false,
            "error": format!(
                "building {building_id:?} not found under csv_buildings and no historian equipment"
            ),
            "hint": HISTORIAN_MAPPING_HINT,
            "building_id": building_id,
        });
    }
    let session = crate::fdd::session_config::get_session_config_scoped(
        &crate::fdd::session_config::SessionConfigScope::new(preferred_tenant, Some(building_id)),
    );
    let unit_system = session
        .get("config")
        .and_then(|c| c.get("unit_system"))
        .cloned()
        .unwrap_or(json!("imperial"));
    let session_role_map = session
        .get("config")
        .and_then(|c| c.get("role_map"))
        .cloned()
        .unwrap_or(json!({}));
    let equipment: Vec<Value> = selected
        .iter()
        .map(|row| timescale_equipment_json(row, model, type_source))
        .collect();
    let equipment_ids: Vec<String> = equipment
        .iter()
        .filter_map(|row| {
            row.get("equipment_id")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .collect();
    let n = equipment.len();
    let warning_count: usize = equipment
        .iter()
        .map(|row| {
            row.get("warnings")
                .and_then(Value::as_array)
                .map(|items| items.len())
                .unwrap_or(0)
        })
        .sum();
    json!({
        "ok": true,
        "building_id": building_id,
        "source": "timescale",
        "unit_system": unit_system,
        "equipment_ids": equipment_ids,
        "equipment": equipment,
        "session_role_map": session_role_map,
        "warnings": ["historian-backed mapping (no csv_buildings package tree)"],
        "validation": {
            "blocker_count": 0,
            "warning_count": warning_count,
            "equipment_count": n,
        },
    })
}

fn timescale_equipment_json(
    row: &TimescaleInventoryEquipment,
    model: Option<&NfModel>,
    type_source: &str,
) -> Value {
    let model_equip = model.and_then(|model| {
        model
            .equipment
            .iter()
            .find(|equip| equip.equipment_id == row.equipment_id)
    });
    let stamp = model_equip
        .map(|equip| equip.equip_type.as_str())
        .or(row.equip_type.as_deref());
    let display = crate::equipment_types::api_equipment_type_for("", stamp);
    let mut roles = Map::new();
    let mut role_to_cols: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (key, role) in &row.roles {
        if let Some(equip) = model_equip {
            if !equip.roles.contains(role) {
                continue;
            }
        }
        roles.insert(key.clone(), json!(role));
        role_to_cols
            .entry(role.clone())
            .or_default()
            .push(key.clone());
    }
    let ambiguous: BTreeMap<String, Vec<String>> = role_to_cols
        .iter()
        .filter(|(_, cols)| cols.len() > 1)
        .map(|(role, cols)| (role.clone(), cols.clone()))
        .collect();
    let columns: Vec<Value> = role_to_cols
        .iter()
        .flat_map(|(role, cols)| {
            let status = if cols.len() > 1 {
                "ambiguous"
            } else {
                "mapped"
            };
            cols.iter()
                .map(|column| {
                    json!({
                        "column": column,
                        "role": role,
                        "status": status,
                    })
                })
                .collect::<Vec<_>>()
        })
        .collect();
    json!({
        "equipment_id": row.equipment_id,
        "equipment_type": display,
        "equipment_type_raw": stamp,
        "equipment_type_source": type_source,
        "parent_ahu": Value::Null,
        "ok": ambiguous.is_empty(),
        "columns": columns,
        "roles": roles,
        "unmapped_columns": [],
        "ambiguous_roles": ambiguous,
        "blockers": [],
        "warnings": [
            "historian data model — no package columns.csv; roles come from the Timescale inventory"
        ],
        "sampling": Value::Null,
    })
}

/// `GET /api/csv/import/package/buildings` — list ingested package building ids
/// plus historian sites under the parquet root (canonical MQTT `history/building_id=`
/// and legacy `building=`), so the sidebar/Overview picker matches Sites (3.3.33).
///
/// `packages` is the exportable subset (dirs under `csv_buildings` with
/// `manifest.json`). Gate 19 / engineering export must use `packages`, not the
/// historian-union `buildings` list (#1149 / Soft-OPEN tip sha-93f8ec2).
pub fn list_package_buildings_handler() -> Value {
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let mut buildings = Vec::new();
    let mut packages = Vec::new();
    if data_root.is_dir() {
        if let Ok(rd) = std::fs::read_dir(&data_root) {
            for e in rd.flatten() {
                let path = e.path();
                if path.is_dir() {
                    if let Some(name) = e.file_name().to_str() {
                        if !name.starts_with('.') && path.join("manifest.json").is_file() {
                            buildings.push(name.to_string());
                            packages.push(name.to_string());
                        }
                    }
                }
            }
        }
    }
    // Union live / package historian partitions so MQTT sites appear like CSV.
    // Wave U V7: also scan tenants/{tid}/building=* and tenants/{tid}/history/…
    let pq = crate::fdd::registry_api::parquet_root();
    for bid in fdd_store::list_building_ids(&pq) {
        buildings.push(bid);
    }
    buildings.sort();
    buildings.dedup();
    packages.sort();
    packages.dedup();
    json!({
        "ok": true,
        "buildings": buildings,
        "packages": packages,
        "path": data_root.display().to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn assert_no_columnar_files(root: &std::path::Path) {
        let columnar: Vec<_> = walkdir::WalkDir::new(root)
            .into_iter()
            .flatten()
            .filter(|e| {
                e.path()
                    .extension()
                    .and_then(|x| x.to_str())
                    .is_some_and(|x| matches!(x, "parquet" | "arrow" | "feather"))
            })
            .map(|e| e.path().to_path_buf())
            .collect();
        assert!(columnar.is_empty(), "columnar files written: {columnar:?}");
    }

    fn build_zip(files: &[(&str, &str)]) -> Vec<u8> {
        let mut cursor = std::io::Cursor::new(Vec::new());
        {
            let mut zw = zip::ZipWriter::new(&mut cursor);
            let opts = zip::write::SimpleFileOptions::default();
            for (name, content) in files {
                zw.start_file(*name, opts).unwrap();
                zw.write_all(content.as_bytes()).unwrap();
            }
            zw.finish().unwrap();
        }
        cursor.into_inner()
    }

    fn history_csv() -> String {
        let mut s = String::from("timestamp_utc,SF_SPD,DA_P,DA_P_SP\n");
        for i in 0..6 {
            s.push_str(&format!("2024-01-01T00:{:02}:00Z,0.95,0.4,1.4\n", i * 5));
        }
        s
    }

    #[test]
    fn haystack_points_translate_to_sql_roles() {
        assert_eq!(
            haystack_point_to_role("vav-pressure-request-sum"),
            "static_reset_request"
        );
        assert_eq!(
            haystack_point_to_role("cooling-coil-entering-temp"),
            "cooling_coil_entering_temp"
        );
        assert_eq!(haystack_point_to_role("chiller-status"), "chiller_status");
        assert_eq!(haystack_point_to_role("fan-cmd"), "fan_cmd");
        assert_eq!(
            haystack_point_to_role("duct-static-pressure"),
            "duct_static"
        );
        assert_eq!(haystack_point_to_role("discharge-air-temp-sp"), "sat_sp");
        assert_eq!(haystack_point_to_role("zone_air_temp"), "zone_t");
        assert_eq!(
            haystack_point_to_role("web-outside-air-wetbulb"),
            "web_wb_t"
        );
        // Snake-case cookbook roles pass through the normalize fallback.
        assert_eq!(haystack_point_to_role("chw_supply_t"), "chw_supply_t");
    }

    #[test]
    fn string_equip_metadata_still_reads_points() {
        // Haystack single-equip sidecars often set "equip": "AHU_1" (string).
        // Only dict equip/equipment/devices is a package map.
        let map = serde_json::json!({
            "equipType": "ahu",
            "equipment_type": "ahu",
            "device": "AHU_1",
            "equip": "AHU_1",
            "points": {
                "fan-cmd": "SF_SPD",
                "discharge-air-temp": "SAT"
            }
        });
        let roles = points_from_map_json(&map, "AHU_1").expect("roles");
        assert_eq!(roles.get("fan-cmd").map(String::as_str), Some("SF_SPD"));
        assert_eq!(
            roles.get("discharge-air-temp").map(String::as_str),
            Some("SAT")
        );
    }

    #[test]
    fn rejects_wrong_schema_and_traversal() {
        let zip = build_zip(&[(
            "manifest.json",
            r#"{"schema_version":"other","building_id":"B","grid_minutes":5}"#,
        )]);
        let out = import_package_zip(&zip);
        assert_eq!(out["ok"], json!(false));
        assert!(out["error"].as_str().unwrap().contains("schema_version"));

        let zip = build_zip(&[("../evil.txt", "x")]);
        let out = import_package_zip(&zip);
        assert_eq!(out["ok"], json!(false));
        assert!(out["error"]
            .as_str()
            .unwrap()
            .contains("path traversal rejected"));
    }

    #[test]
    fn peek_package_building_id_reads_manifest() {
        let zip = build_zip(&[(
            "manifest.json",
            r#"{"schema_version":"openfdd_package_v1","building_id":"ACME","grid_minutes":5}"#,
        )]);
        let bid = peek_package_building_id("application/zip", &zip).expect("peek");
        assert_eq!(bid, "ACME");
    }

    #[test]
    fn hostile_zip_cases_from_fixture_catalog() {
        // Mirrors tests/react_parity/fixtures/hostile_zip/cases.json — archives built at test time.
        let slip = build_zip(&[("../../etc/passwd", "x")]);
        let out = import_package_zip(&slip);
        assert_eq!(out["ok"], json!(false));
        assert!(out["error"]
            .as_str()
            .unwrap()
            .contains("path traversal rejected"));

        let absolute = build_zip(&[("/etc/passwd", "x")]);
        let out = import_package_zip(&absolute);
        assert_eq!(out["ok"], json!(false));
        assert!(out["error"]
            .as_str()
            .unwrap()
            .contains("absolute path in zip rejected"));

        // Symlink entry (zip-slip variant). zip 3's unix_permissions() masks to 0o777,
        // so use ZipWriter::add_symlink which sets S_IFLNK correctly.
        let mut cursor = std::io::Cursor::new(Vec::new());
        {
            let mut zw = zip::ZipWriter::new(&mut cursor);
            zw.add_symlink(
                "link_to_outside",
                "../../etc/passwd",
                zip::write::SimpleFileOptions::default(),
            )
            .unwrap();
            zw.finish().unwrap();
        }
        let symlink_zip = cursor.into_inner();
        let out = import_package_zip(&symlink_zip);
        assert_eq!(out["ok"], json!(false), "symlink zip response: {out}");
        assert!(
            out["error"]
                .as_str()
                .unwrap_or("")
                .contains("symlink entries are not allowed"),
            "symlink zip response: {out}"
        );

        // Extension spoof is allowed at zip layer; ingest fails later on missing manifest/maps.
        let spoof = build_zip(&[("evil.csv.exe", "not-a-package")]);
        let out = import_package_zip(&spoof);
        assert_eq!(out["ok"], json!(false));
        assert!(out["error"].as_str().unwrap().contains("manifest.json"));

        // Nested zip entries are ignored with a warning once a valid package is ingested elsewhere;
        // a zip-only archive still fails closed on missing manifest.
        let nested = build_zip(&[("payload.zip", "PK\x03\x04")]);
        let out = import_package_zip(&nested);
        assert_eq!(out["ok"], json!(false));

        // Case-colliding paths.
        let dup = build_zip(&[("MANIFEST.JSON", "x"), ("manifest.json", "y")]);
        let out = import_package_zip(&dup);
        assert_eq!(out["ok"], json!(false));
        assert!(out["error"]
            .as_str()
            .unwrap()
            .contains("duplicate / case-colliding path"));
    }

    #[test]
    fn rejects_absolute_and_nested_zip_entries() {
        let zip = build_zip(&[("/etc/passwd", "x")]);
        let out = import_package_zip(&zip);
        assert_eq!(out["ok"], json!(false), "{out}");
        assert!(
            out["error"]
                .as_str()
                .unwrap_or("")
                .contains("absolute path in zip rejected"),
            "{out}"
        );

        // Nested .zip members are ignored (not expanded) during ingest.
        let outer = build_zip(&[
            (
                "manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"B_NEST","grid_minutes":5}"#,
            ),
            ("nested.zip", "PK\x03\x04not-a-real-nested"),
        ]);
        let out = import_package_zip(&outer);
        // Missing equipment maps → ok=false, but must not crash on nested zip bytes.
        assert_eq!(out["ok"], json!(false), "{out}");
        assert!(
            out["error"].as_str().is_some() || out["missing_maps"].is_array(),
            "{out}"
        );
    }

    #[test]
    fn accepts_creekside_nested_package_and_utilities() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_creekside_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let set_ws = |tmp: &std::path::Path| {
            std::env::remove_var("OPENFDD_STORAGE_URL");
            std::env::set_var("OPENFDD_WORKSPACE", tmp);
            std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.join(".cache/parquet"));
        };
        set_ws(&tmp);

        let map = r#"{"equipType":"ahu","points":{
            "fan-cmd":"SF_SPD",
            "duct-static-pressure":"DA_P",
            "duct-static-pressure-sp":"DA_P_SP"
        }}"#;
        let bills = "account,billing_period,kwh,demand_kw\nACCT1,2024-01,1000,50\n";
        let zip = build_zip(&[
            (
                "OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"LAKESIDE_ES","grid_minutes":5,"timezone":"UTC"}"#,
            ),
            (
                "OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/AHU_1/history_wide.csv",
                &history_csv(),
            ),
            (
                "OpenFdd_Creekside/LAKESIDE_ES_openfdd_package_v1/LAKESIDE_ES/AHU_1/history_wide.json",
                map,
            ),
            ("OpenFdd_Creekside/utility_bills_monthly.csv", bills),
        ]);
        set_ws(&tmp);
        let out = import_package_zip(&zip);
        assert_eq!(out["ok"], json!(true), "{out}");
        assert_eq!(out["building_id"], json!("LAKESIDE_ES"));
        assert!(
            out["utilities_written"].as_array().map(|a| !a.is_empty()) == Some(true),
            "{out}"
        );
    }

    #[test]
    fn rejects_missing_equipment_map() {
        let zip = build_zip(&[
            (
                "manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"B_MAPLESS","grid_minutes":5}"#,
            ),
            ("AHU_1/history_wide.csv", &history_csv()),
        ]);
        let out = import_package_zip(&zip);
        assert_eq!(out["ok"], json!(false), "{out}");
        assert!(
            out["missing_maps"].as_array().map(|a| !a.is_empty()) == Some(true),
            "{out}"
        );
    }

    #[test]
    fn loads_package_maps_roles_and_ingests() {
        // Serialize against other env-mutating unit tests; unique dir per run.
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_pkg_test_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        // Re-assert env immediately before each call that reads workspace_dir(),
        // because other tests still mutate OPENFDD_WORKSPACE without the lock.
        let set_ws = |tmp: &std::path::Path| {
            std::env::remove_var("OPENFDD_STORAGE_URL");
            std::env::set_var("OPENFDD_WORKSPACE", tmp);
            std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.join(".cache/parquet"));
        };
        set_ws(&tmp);

        let map = r#"{"equipType":"ahu","points":{
            "fan-cmd":"SF_SPD",
            "duct-static-pressure":"DA_P",
            "duct-static-pressure-sp":"DA_P_SP"
        }}"#;
        let zip = build_zip(&[
            (
                "BUILDING_9/manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"BUILDING_9","grid_minutes":5,"timezone":"UTC"}"#,
            ),
            (
                "BUILDING_9/session_config.json",
                r#"{"schema_version":"openfdd_session_v1","unit_system":"imperial"}"#,
            ),
            ("BUILDING_9/AHU_1/history_wide.csv", &history_csv()),
            ("BUILDING_9/AHU_1/history_wide.json", map),
        ]);
        set_ws(&tmp);
        let out = import_package_zip(&zip);
        assert_eq!(out["ok"], json!(true), "{out}");
        assert_eq!(out["building_id"], json!("BUILDING_9"));
        assert_eq!(out["grid_minutes"], json!(5));
        assert_eq!(out["equipment"][0]["roles"]["SF_SPD"], json!("fan_cmd"));
        assert_eq!(out["equipment"][0]["roles"]["DA_P"], json!("duct_static"));
        assert_eq!(
            out["session_config"]["unit_system"],
            json!("imperial"),
            "{out}"
        );
        assert_eq!(out["needs_timescale_seed"], json!(true), "{out}");
        assert_eq!(out["staged"], json!(true), "{out}");
        // Central publishes the staged tree after its Timescale seed commits.
        let staged_root = out["package_root"]
            .as_str()
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| tmp.join("data/csv_buildings/BUILDING_9.incoming"));
        let pkg_root = commit_staged_package(&staged_root, 0, 1).unwrap();
        let cols_path = pkg_root.join("AHU_1/columns.csv");
        let cols = std::fs::read_to_string(&cols_path).unwrap_or_else(|e| {
            panic!(
                "missing {}: {e}; import out={out}; tmp entries={:?}",
                cols_path.display(),
                std::fs::read_dir(&tmp)
                    .map(|d| d
                        .filter_map(|e| e.ok().map(|e| e.path()))
                        .collect::<Vec<_>>())
                    .unwrap_or_default()
            )
        });
        assert!(cols.contains("SF_SPD,fan_cmd"), "{cols}");
        assert_no_columnar_files(&tmp);

        // Role update rewrites columns.csv and re-ingests.
        // Bind workspace to the import's package_root parents — parallel tests that
        // mutate OPENFDD_WORKSPACE without the lock can desync `tmp` from where
        // import actually wrote (package_root remains authoritative).
        let ws_from_pkg = pkg_root
            .parent() // …/csv_buildings
            .and_then(|p| p.parent()) // …/data
            .and_then(|p| p.parent()) // workspace root
            .unwrap_or(tmp.as_path());
        set_ws(ws_from_pkg);
        assert!(
            pkg_root.join("AHU_1/history_wide.csv").is_file(),
            "history_wide missing under package_root={}; out={out}",
            pkg_root.display()
        );
        let upd = update_package_roles_handler(&json!({
            "building_id": "BUILDING_9",
            "equipment_id": "AHU_1",
            "roles": {"SF_SPD": "fan_status", "DA_P": "duct_static", "DA_P_SP": "duct_static_sp", "GHOST": "oa_t"}
        }));
        assert_eq!(upd["ok"], json!(true), "{upd}");
        assert_eq!(upd["ignored_columns"], json!(["GHOST"]), "{upd}");
        let cols = std::fs::read_to_string(&cols_path).unwrap();
        assert!(cols.contains("SF_SPD,fan_status"), "{cols}");

        set_ws(ws_from_pkg);
        let inv = get_package_mapping_handler("BUILDING_9", Some("AHU_1"));
        assert_eq!(inv["ok"], json!(true), "{inv}");
        assert_eq!(inv["building_id"], json!("BUILDING_9"));
        assert_eq!(inv["validation"]["equipment_count"], json!(1));
        let eq0 = &inv["equipment"][0];
        assert_eq!(eq0["equipment_id"], json!("AHU_1"));
        assert_eq!(eq0["equipment_type"], json!("AHU"));
        assert_eq!(eq0["roles"]["SF_SPD"], json!("fan_status"));
        assert!(eq0["sampling"]["row_count"].as_u64().unwrap_or(0) >= 1);

        set_ws(ws_from_pkg);
        let buildings = list_package_buildings_handler();
        assert_eq!(buildings["ok"], json!(true), "{buildings}");
        assert!(
            buildings["buildings"]
                .as_array()
                .unwrap()
                .iter()
                .any(|b| b == "BUILDING_9"),
            "{buildings}"
        );
        assert!(
            buildings["packages"]
                .as_array()
                .unwrap()
                .iter()
                .any(|b| b == "BUILDING_9"),
            "exportable packages must include BUILDING_9 with manifest: {buildings}"
        );

        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn parent_ahu_uses_package_metadata_not_id_text() {
        let tmp = tempfile::TempDir::new().unwrap();
        let siblings = vec![
            "AC_1".into(),
            "box_12".into(),
            "AHU_10".into(),
            "VAV_2_AHU_1".into(),
        ];
        let vav = tmp.path().join("VAV_2_AHU_1");
        std::fs::create_dir_all(&vav).unwrap();
        std::fs::write(vav.join("history_wide.json"), r#"{"equipType":"vav"}"#).unwrap();
        assert_eq!(
            package_parent_ahu(&vav, "VAV_2_AHU_1", &siblings),
            None,
            "an AHU token in the id is not a parent"
        );
        let lone = tmp.path().join("VAV_9");
        std::fs::create_dir_all(&lone).unwrap();
        assert_eq!(
            package_parent_ahu(&lone, "VAV_9", &siblings),
            None,
            "a single air handler sibling is not a parent"
        );
        let box_dir = tmp.path().join("box_12");
        std::fs::create_dir_all(&box_dir).unwrap();
        std::fs::write(
            box_dir.join("history_wide.json"),
            r#"{"equipType":"vav","parentAhu":"AC_1"}"#,
        )
        .unwrap();
        assert_eq!(
            package_parent_ahu(&box_dir, "box_12", &siblings).as_deref(),
            Some("AC_1")
        );
        std::fs::write(
            box_dir.join("history_wide.json"),
            r#"{"equipType":"vav","parentAhu":"AHU_1"}"#,
        )
        .unwrap();
        assert_eq!(
            package_parent_ahu(&box_dir, "box_12", &siblings),
            None,
            "AHU_1 must not select the sibling AHU_10"
        );
    }

    #[test]
    fn dm04_stamped_opaque_id_beats_id_heuristic() {
        // AC_1 has no AHU token; stamp must win (DM-04).
        let (display, raw, source) = resolve_mapping_equipment_type(
            "AC_1",
            &BTreeMap::from([("AC_1".into(), "ahu".into())]),
        );
        assert_eq!(display, "AHU");
        assert_eq!(raw.as_deref(), Some("ahu"));
        assert_eq!(source, "package");
        let (display2, _, source2) = resolve_mapping_equipment_type("AC_1", &BTreeMap::new());
        assert_eq!(display2, "GENERAL");
        assert_eq!(source2, "unclassified");
    }

    #[test]
    fn dm04_mapping_inventory_honors_equipment_types_json() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_dm04_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::remove_var("OPENFDD_STORAGE_URL");
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.join(".cache/parquet"));

        let bid = "DM04_STAMP_BLDG";
        let broot = tmp.join("data/csv_buildings").join(bid);
        let eq_dir = broot.join("AC_1");
        std::fs::create_dir_all(&eq_dir).unwrap();
        std::fs::write(
            eq_dir.join("history_wide.csv"),
            "timestamp_utc,SF_SPD\n2024-01-01T00:00:00Z,1.0\n",
        )
        .unwrap();
        std::fs::write(eq_dir.join("columns.csv"), "column,role\nSF_SPD,fan_cmd\n").unwrap();
        std::fs::write(
            broot.join(crate::equipment_types::EQUIPMENT_TYPES_FILE),
            r#"{"AC_1":"ahu"}"#,
        )
        .unwrap();

        let inv = get_package_mapping_handler(bid, Some("AC_1"));
        assert_eq!(inv["ok"], json!(true), "{inv}");
        let eq0 = &inv["equipment"][0];
        assert_eq!(eq0["equipment_id"], json!("AC_1"));
        assert_eq!(eq0["equipment_type"], json!("AHU"), "{eq0}");
        assert_eq!(eq0["equipment_type_raw"], json!("ahu"));
        assert_eq!(eq0["equipment_type_source"], json!("package"));
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn append_json_requires_confirm_and_merges() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!("openfdd_pkg_append_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::remove_var("OPENFDD_STORAGE_URL");
        std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.join(".cache/parquet"));

        let map = r#"{"equipType":"ahu","points":{"fan-cmd":"SF_SPD","duct-static-pressure":"DA_P","duct-static-pressure-sp":"DA_P_SP"}}"#;
        let zip = build_zip(&[
            (
                "manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"B_APPEND","grid_minutes":15}"#,
            ),
            ("AHU_1/history_wide.csv", &history_csv()),
            ("AHU_1/history_wide.json", map),
        ]);
        let seed = import_package_zip(&zip);
        assert_eq!(seed["ok"], json!(true), "{seed}");
        let staged = std::path::PathBuf::from(seed["package_root"].as_str().unwrap());
        commit_staged_package(&staged, 0, 1).unwrap();

        let deny = append_package_json(&json!({
            "building_id": "B_APPEND",
            "equipment_id": "AHU_1",
            "csv": "timestamp_utc,SF_SPD,DA_P,DA_P_SP\n2024-01-01T01:00:00Z,80,1.1,1.0\n"
        }));
        assert_eq!(deny["ok"], json!(false), "{deny}");

        let hour = append_package_json(&json!({
            "confirm": true,
            "building_id": "B_APPEND",
            "equipment_id": "AHU_1",
            "csv": "timestamp_utc,SF_SPD,DA_P,DA_P_SP\n2024-01-01T01:00:00Z,80,1.1,1.0\n"
        }));
        assert_eq!(hour["ok"], json!(true), "{hour}");
        assert_eq!(hour["merges"][0]["rows_added"], json!(1), "{hour}");

        let replay = append_package_json(&json!({
            "confirm": true,
            "building_id": "B_APPEND",
            "equipment_id": "AHU_1",
            "csv": "timestamp_utc,SF_SPD,DA_P,DA_P_SP\n2024-01-01T01:00:00Z,80,1.1,1.0\n"
        }));
        assert_eq!(replay["ok"], json!(true), "{replay}");
        assert_eq!(replay["merges"][0]["rows_added"], json!(0), "{replay}");
        assert_eq!(replay["merges"][0]["rows_duped"], json!(1), "{replay}");
        assert_eq!(replay["needs_timescale_seed"], json!(true), "{replay}");
        assert_no_columnar_files(&tmp);

        let _ = std::fs::remove_dir_all(&tmp);
    }

    struct FixtureInventory;

    impl TimescaleInventoryAdapter for FixtureInventory {
        fn equipment(
            &self,
            building_id: &str,
            tenant_id: Option<&str>,
        ) -> Result<Vec<TimescaleInventoryEquipment>, String> {
            let body: Value =
                serde_json::from_str(include_str!("fixtures/w2d_timescale_inventory.json"))
                    .expect("timescale fixture");
            if body.get("building_id").and_then(Value::as_str) != Some(building_id) {
                return Ok(Vec::new());
            }
            let owner = body
                .get("tenant_id")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if let Some(tenant) = tenant_id {
                if tenant != owner {
                    return Ok(Vec::new());
                }
            }
            let mut rows = Vec::new();
            for item in body
                .get("equipment")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let Some(equipment_id) = item.get("equipment_id").and_then(Value::as_str) else {
                    continue;
                };
                let mut roles = BTreeMap::new();
                if let Some(map) = item.get("roles").and_then(Value::as_object) {
                    for (key, role) in map {
                        if let Some(role) = role.as_str() {
                            roles.insert(key.clone(), role.to_string());
                        }
                    }
                }
                rows.push(TimescaleInventoryEquipment {
                    equipment_id: equipment_id.to_string(),
                    equip_type: item
                        .get("equip_type")
                        .and_then(Value::as_str)
                        .map(str::to_string),
                    roles,
                });
            }
            Ok(rows)
        }
    }

    struct DenyProbe;

    impl TimescaleInventoryAdapter for DenyProbe {
        fn equipment(
            &self,
            _building_id: &str,
            _tenant_id: Option<&str>,
        ) -> Result<Vec<TimescaleInventoryEquipment>, String> {
            panic!("foreign tenant read the timescale inventory");
        }
    }

    fn assert_no_mqtt(value: &Value) {
        let text = value.to_string().to_ascii_lowercase();
        assert!(!text.contains("mqtt"), "{value}");
    }

    fn w2d_metadata(kind: &str) -> NfMetadata<'static> {
        match kind {
            "ttl" => NfMetadata::Ttl {
                turtle: include_str!("fixtures/w2d_nf_scoped.ttl"),
                tenant_id: "tenant-w2d",
                provider_instance_id: "nf-w2d",
                graph: "urn:openfdd:ingest:v1:graph/tenant-w2d/site-w2d",
            },
            "template" => {
                NfMetadata::Template(include_str!("fixtures/w2d_nf_scoped.template.json"))
            }
            _ => panic!("unknown metadata kind {kind}"),
        }
    }

    #[test]
    fn nf_scoped_consumer_covers_ttl_and_template_scopes() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_w2d_nf_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        let inventory = FixtureInventory;

        for kind in ["ttl", "template"] {
            for scoped in [true, false] {
                let preferred = if scoped { Some("tenant-w2d") } else { None };
                let out = nf_scoped_consumer(
                    "site-w2d",
                    Some("EQ_7"),
                    preferred,
                    w2d_metadata(kind),
                    &inventory,
                );
                assert_eq!(out["ok"], json!(true), "{kind} scoped={scoped}: {out}");
                assert_eq!(out["metadata"], json!(kind), "{out}");
                assert_eq!(
                    out["scope"],
                    json!(if scoped { "scoped" } else { "unscoped" }),
                    "{out}"
                );
                assert_eq!(out["source"], json!("timescale"), "{out}");
                assert_eq!(out["equipment_ids"], json!(["EQ_7"]), "{out}");
                let roles = &out["equipment"][0]["roles"];
                assert_eq!(roles["series-sat"], json!("sat"), "{out}");
                assert_eq!(roles["series-fan"], json!("fan_status"), "{out}");
                assert!(roles.get("series-duct").is_none(), "{out}");
                assert!(roles.get("oa_t").is_none(), "{out}");
                assert_eq!(out["equipment"][0]["equipment_type"], json!("AHU"), "{out}");
                assert_no_mqtt(&out);
            }
        }

        let listed = nf_scoped_consumer(
            "site-w2d",
            None,
            Some("tenant-w2d"),
            w2d_metadata("ttl"),
            &inventory,
        );
        assert_eq!(listed["ok"], json!(true), "{listed}");
        let ids = listed["equipment_ids"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        assert!(ids.iter().any(|id| id.as_str() == Some("EQ_7")), "{listed}");
        assert!(
            ids.iter().any(|id| id.as_str() == Some("EQ_70")),
            "{listed}"
        );
        assert_no_mqtt(&listed);

        match prev_ws {
            Some(value) => std::env::set_var("OPENFDD_WORKSPACE", value),
            None => std::env::remove_var("OPENFDD_WORKSPACE"),
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn nf_scoped_consumer_denies_foreign_tenant() {
        let _env = crate::test_support::workspace_env_lock();
        for kind in ["ttl", "template"] {
            let out = nf_scoped_consumer(
                "site-w2d",
                None,
                Some("tenant-other"),
                w2d_metadata(kind),
                &DenyProbe,
            );
            assert_eq!(out["ok"], json!(false), "{kind}: {out}");
            assert_eq!(out["code"], json!("foreign_tenant"), "{out}");
            assert!(out.get("equipment").is_none(), "{out}");
            assert!(!out.to_string().contains("EQ_7"), "{out}");
            assert!(!out.to_string().contains("EQ_70"), "{out}");
            assert_no_mqtt(&out);
        }
    }

    #[test]
    fn historian_mapping_hint_does_not_mention_mqtt() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_w2d_hint_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        let prev_db = std::env::var("OPENFDD_DATABASE_URL").ok();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::remove_var("OPENFDD_DATABASE_URL");

        let missing = get_package_mapping_handler_scoped("site-w2d", None, None);
        assert_eq!(missing["ok"], json!(false), "{missing}");
        assert_eq!(
            missing["hint"],
            json!(
                "upload an openfdd_package_v1 zip or ingest the site through the Normal Framework portal"
            ),
            "{missing}"
        );
        assert_no_mqtt(&missing);

        match prev_ws {
            Some(value) => std::env::set_var("OPENFDD_WORKSPACE", value),
            None => std::env::remove_var("OPENFDD_WORKSPACE"),
        }
        match prev_db {
            Some(value) => std::env::set_var("OPENFDD_DATABASE_URL", value),
            None => std::env::remove_var("OPENFDD_DATABASE_URL"),
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn rejects_unmapped_weather_before_any_package_write() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_w5g_preflight_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let prev_db = std::env::var("OPENFDD_DATABASE_URL").ok();
        let prev_hist = std::env::var("OPENFDD_HISTORIAN").ok();
        let prev_ws = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::remove_var("OPENFDD_DATABASE_URL");
        std::env::remove_var("OPENFDD_HISTORIAN");
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);

        let history = "timestamp_utc,SF_SPD\n2026-06-01T00:00:00Z,1\n";
        let weather = "timestamp_utc,OAT\n2026-06-01T00:00:00Z,55\n";
        let missing = build_zip(&[
            (
                "manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"w5g-edge-badwx","grid_minutes":5}"#,
            ),
            ("AHU_1/history_wide.csv", history),
            (
                "AHU_1/column_map.json",
                r#"{"equipType":"ahu","points":{"fan-cmd":"SF_SPD"}}"#,
            ),
            ("weather/history_wide.csv", weather),
            ("weather/columns.csv", "column,point_role\nOAT,oa_t\n"),
        ]);
        let out = import_package_zip(&missing);
        let root = tmp.join("data").join("csv_buildings");
        assert_eq!(out["ok"], json!(false), "{out}");
        assert!(
            out["missing_maps"]
                .as_array()
                .is_some_and(|rows| !rows.is_empty()),
            "{out}"
        );
        assert!(!root.join("w5g-edge-badwx").exists(), "{out}");
        assert!(!root.join("w5g-edge-badwx.incoming").exists(), "{out}");

        let bad_ref = build_zip(&[
            (
                "manifest.json",
                r#"{"schema_version":"openfdd_package_v1","building_id":"w5g-edge-badref","grid_minutes":5}"#,
            ),
            ("AHU_1/history_wide.csv", history),
            (
                "AHU_1/column_map.json",
                r#"{"equipType":"ahu","points":{"fan-cmd":"SF_SPD"}}"#,
            ),
            ("weather/history_wide.csv", weather),
            (
                "weather/column_map.json",
                r#"{"equipType":"weather","points":{"outside-air-temp":"NOT_A_COLUMN"}}"#,
            ),
        ]);
        let out = import_package_zip(&bad_ref);
        assert_eq!(out["ok"], json!(false), "{out}");
        assert!(
            out["bad_references"]
                .as_array()
                .is_some_and(|rows| !rows.is_empty()),
            "{out}"
        );
        assert!(!root.join("w5g-edge-badref").exists(), "{out}");
        assert!(!root.join("w5g-edge-badref.incoming").exists(), "{out}");

        match prev_db {
            Some(value) => std::env::set_var("OPENFDD_DATABASE_URL", value),
            None => std::env::remove_var("OPENFDD_DATABASE_URL"),
        }
        match prev_hist {
            Some(value) => std::env::set_var("OPENFDD_HISTORIAN", value),
            None => std::env::remove_var("OPENFDD_HISTORIAN"),
        }
        match prev_ws {
            Some(value) => std::env::set_var("OPENFDD_WORKSPACE", value),
            None => std::env::remove_var("OPENFDD_WORKSPACE"),
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
