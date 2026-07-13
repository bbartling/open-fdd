//! Safe ZIP package inspect/extract for CSV workbench (Phase 1 / #481).
//!
//! Mirrors Vibe19 `package_io` security gates: traversal, absolute paths,
//! symlinks, entry-count / size / compression-ratio bombs, duplicate paths.
//! Extraction is bounded under `{workspace}/data/csv_workbench/packages/`.

use crate::csv_ingest::parse::{parse_csv_bytes, sanitize_filename};
use crate::csv_ingest::session::{create_session, load_session, save_session, stage_file};
use chrono::Utc;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::{Cursor, Read, Write};
use std::path::{Component, Path, PathBuf};
use zip::read::ZipArchive;

pub const SCHEMA_VERSION: &str = "openfdd_package_v1";
pub const MAX_PATH_DEPTH: usize = 8;
pub const DEFAULT_MAX_ZIP_BYTES: u64 = 500 * 1024 * 1024;
pub const DEFAULT_MAX_UNCOMPRESSED_BYTES: u64 = 500 * 1024 * 1024;
pub const DEFAULT_MAX_ENTRIES: usize = 2000;
pub const DEFAULT_MAX_RATIO: f64 = 100.0;
pub const DEFAULT_MAX_SINGLE_ENTRY_BYTES: u64 = 250 * 1024 * 1024;

const ALLOWED_EXTENSIONS: &[&str] = &["csv", "json", "txt", "md"];

#[derive(Debug, Clone)]
pub struct PackageCaps {
    pub max_zip_bytes: u64,
    pub max_uncompressed_bytes: u64,
    pub max_entries: usize,
    pub max_ratio: f64,
    pub max_single_entry_bytes: u64,
}

impl Default for PackageCaps {
    fn default() -> Self {
        Self {
            max_zip_bytes: env_u64("OPENFDD_MAX_ZIP_MB", DEFAULT_MAX_ZIP_BYTES / (1024 * 1024))
                * 1024
                * 1024,
            max_uncompressed_bytes: env_u64(
                "OPENFDD_MAX_UNCOMPRESSED_MB",
                DEFAULT_MAX_UNCOMPRESSED_BYTES / (1024 * 1024),
            ) * 1024
                * 1024,
            max_entries: env_usize("OPENFDD_MAX_ENTRIES", DEFAULT_MAX_ENTRIES),
            max_ratio: DEFAULT_MAX_RATIO,
            max_single_entry_bytes: DEFAULT_MAX_SINGLE_ENTRY_BYTES,
        }
    }
}

fn env_u64(name: &str, default: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|v| *v >= 1)
        .unwrap_or(default)
}

fn env_usize(name: &str, default: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|v| *v >= 1)
        .unwrap_or(default)
}

pub fn packages_root() -> PathBuf {
    crate::historian::store::workspace_dir().join("data/csv_workbench/packages")
}

fn package_dir(package_id: &str) -> PathBuf {
    packages_root().join(sanitize_package_id(package_id))
}

fn sanitize_package_id(id: &str) -> String {
    let s: String = id
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect();
    if s.is_empty() {
        "pkg".into()
    } else {
        s
    }
}

fn new_package_id() -> String {
    // Prefer uniqueness under parallel tests (millis alone can collide).
    let nanos = Utc::now()
        .timestamp_nanos_opt()
        .unwrap_or_else(|| Utc::now().timestamp_millis().saturating_mul(1_000_000));
    format!("pkg-{nanos}")
}

/// Reject zip-slip / absolute / drive-letter paths. Return normalized relative path.
pub fn safe_member_path(name: &str) -> Result<PathBuf, String> {
    let raw = name.replace('\\', "/");
    let parts_src = raw.trim_end_matches('/');
    if parts_src.starts_with('/')
        || (parts_src.len() > 1 && parts_src.as_bytes().get(1) == Some(&b':'))
    {
        return Err(format!("absolute path in zip rejected: {name}"));
    }
    let parts: Vec<&str> = parts_src
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect();
    if parts.contains(&"..") {
        return Err(format!("path traversal rejected: {name}"));
    }
    if parts.len() > MAX_PATH_DEPTH {
        return Err(format!("path too deep (>{MAX_PATH_DEPTH}): {name}"));
    }
    if parts.is_empty() {
        return Ok(PathBuf::new());
    }
    Ok(parts.iter().collect())
}

fn extension_of(path: &Path) -> Option<String> {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|s| s.to_ascii_lowercase())
}

fn is_allowed_file(path: &Path) -> bool {
    match extension_of(path) {
        Some(ext) => ALLOWED_EXTENSIONS.contains(&ext.as_str()),
        None => false,
    }
}

fn flatten_rel_path(rel: &Path) -> String {
    rel.components()
        .filter_map(|c| match c {
            Component::Normal(s) => Some(s.to_string_lossy().replace(['/', '\\'], "_")),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("__")
}

#[derive(Debug, Clone)]
pub struct ZipEntryMeta {
    pub name: String,
    pub rel_path: PathBuf,
    pub compressed_size: u64,
    pub uncompressed_size: u64,
    pub is_dir: bool,
}

/// Inspect ZIP central directory without writing files.
pub fn inspect_zip_bytes(data: &[u8], caps: &PackageCaps) -> Result<Vec<ZipEntryMeta>, String> {
    if data.len() as u64 > caps.max_zip_bytes {
        return Err(format!(
            "zip exceeds {} MB compressed limit",
            caps.max_zip_bytes / (1024 * 1024)
        ));
    }
    let cursor = Cursor::new(data);
    let mut archive =
        ZipArchive::new(cursor).map_err(|e| format!("corrupted or invalid zip: {e}"))?;
    if archive.len() > caps.max_entries {
        return Err(format!(
            "zip has too many entries ({} > max {})",
            archive.len(),
            caps.max_entries
        ));
    }

    let mut total_uncompressed: u64 = 0;
    let mut names_lower: HashSet<String> = HashSet::new();
    let mut out = Vec::new();

    for i in 0..archive.len() {
        let entry = archive
            .by_index(i)
            .map_err(|e| format!("corrupted zip entry {i}: {e}"))?;
        let name = entry.name().to_string();
        let is_dir = entry.is_dir() || name.ends_with('/');
        if is_symlink_from_mode(entry.unix_mode()) {
            return Err(format!("symlink entries are not allowed: {name}"));
        }

        let compressed = entry.compressed_size();
        let uncompressed = entry.size();
        if uncompressed > caps.max_single_entry_bytes {
            return Err(format!(
                "entry exceeds single-file limit: {name} ({uncompressed} bytes)"
            ));
        }
        if compressed > 0 {
            let ratio = uncompressed as f64 / compressed.max(1) as f64;
            if ratio > caps.max_ratio {
                return Err(format!("suspicious compression ratio: {name}"));
            }
        }
        if !is_dir {
            total_uncompressed = total_uncompressed.saturating_add(uncompressed);
            if total_uncompressed > caps.max_uncompressed_bytes {
                return Err(format!(
                    "uncompressed size exceeds {} MB limit",
                    caps.max_uncompressed_bytes / (1024 * 1024)
                ));
            }
        }

        let rel = safe_member_path(&name)?;
        if !is_dir {
            if !is_allowed_file(&rel) {
                return Err(format!(
                    "unsupported file type in package: {}",
                    rel.display()
                ));
            }
            let key = rel.to_string_lossy().to_ascii_lowercase();
            if !key.is_empty() && !names_lower.insert(key) {
                return Err(format!("duplicate / case-colliding path: {name}"));
            }
        }

        out.push(ZipEntryMeta {
            name,
            rel_path: rel,
            compressed_size: compressed,
            uncompressed_size: uncompressed,
            is_dir,
        });
    }
    Ok(out)
}

fn is_symlink_from_mode(mode: Option<u32>) -> bool {
    mode.map(|m| (m & 0o170000) == 0o120000).unwrap_or(false)
}

/// Extract validated ZIP into `dest`, streaming with a hard uncompressed cap.
pub fn extract_zip_bytes(
    data: &[u8],
    dest: &Path,
    caps: &PackageCaps,
) -> Result<Vec<ZipEntryMeta>, String> {
    let metas = inspect_zip_bytes(data, caps)?;
    fs::create_dir_all(dest).map_err(|e| e.to_string())?;

    let cursor = Cursor::new(data);
    let mut archive =
        ZipArchive::new(cursor).map_err(|e| format!("corrupted or invalid zip: {e}"))?;
    let mut written: u64 = 0;

    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| format!("corrupted zip entry {i}: {e}"))?;
        let name = entry.name().to_string();
        if entry.is_dir() || name.ends_with('/') {
            let rel = safe_member_path(&name)?;
            if rel.as_os_str().is_empty() {
                continue;
            }
            let target = dest.join(&rel);
            ensure_within(dest, &target)?;
            fs::create_dir_all(&target).map_err(|e| e.to_string())?;
            continue;
        }
        let rel = safe_member_path(&name)?;
        if rel.as_os_str().is_empty() {
            continue;
        }
        let target = dest.join(&rel);
        ensure_within(dest, &target)?;
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut out = fs::File::create(&target).map_err(|e| e.to_string())?;
        let mut buf = [0u8; 256 * 1024];
        loop {
            let n = entry.read(&mut buf).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            written = written.saturating_add(n as u64);
            if written > caps.max_uncompressed_bytes {
                let _ = fs::remove_dir_all(dest);
                return Err(format!(
                    "uncompressed size limit exceeded during extract ({} MB)",
                    caps.max_uncompressed_bytes / (1024 * 1024)
                ));
            }
            out.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        }
    }
    Ok(metas)
}

fn ensure_within(root: &Path, candidate: &Path) -> Result<(), String> {
    // `candidate` is always constructed as `root.join(safe_rel)`; still verify.
    if candidate.starts_with(root) {
        Ok(())
    } else {
        Err(format!(
            "path escapes package workspace: {}",
            candidate.display()
        ))
    }
}

fn build_manifest_from_extract(
    package_id: &str,
    extract_root: &Path,
    entries: &[ZipEntryMeta],
    zip_bytes: usize,
) -> Value {
    let mut csv_files = Vec::new();
    let mut json_files = Vec::new();
    let mut other_files = Vec::new();
    let mut weather_csvs = Vec::new();
    let mut equipment_dirs: BTreeMap<String, Vec<String>> = BTreeMap::new();

    for e in entries.iter().filter(|e| !e.is_dir) {
        let rel = e.rel_path.to_string_lossy().replace('\\', "/");
        let lower = rel.to_ascii_lowercase();
        match extension_of(&e.rel_path).as_deref() {
            Some("csv") => {
                csv_files.push(rel.clone());
                if lower.contains("weather") {
                    weather_csvs.push(rel.clone());
                }
                if let Some(Component::Normal(first)) = e.rel_path.components().next() {
                    let folder = first.to_string_lossy().to_string();
                    if !folder.eq_ignore_ascii_case("weather")
                        && e.rel_path.components().count() > 1
                    {
                        equipment_dirs.entry(folder).or_default().push(rel.clone());
                    }
                }
            }
            Some("json") => json_files.push(rel.clone()),
            _ => other_files.push(rel.clone()),
        }
    }
    csv_files.sort();
    json_files.sort();
    other_files.sort();
    weather_csvs.sort();

    let package_manifest = read_json_if_present(extract_root, "manifest.json");
    let column_map = find_column_map(extract_root);
    let session_config = read_json_if_present(extract_root, "session_config.json");
    let mapping_status = match &column_map {
        Some(doc) => match crate::model::csv_workbench::validate_column_map_document(doc) {
            Ok(()) => json!({"present": true, "valid": true, "errors": []}),
            Err(e) => json!({"present": true, "valid": false, "errors": [e]}),
        },
        None => {
            // Vibe19-style equipment maps are not the Phase-1 versioned doc — note presence only.
            let vibe_map = read_json_if_present(extract_root, "column_map.json");
            if vibe_map.is_some() {
                json!({
                    "present": true,
                    "valid": false,
                    "errors": ["column_map.json is not a versioned Phase-1 mapping document (missing required meta fields); open Mapping to assign roles"],
                    "raw_present": true
                })
            } else {
                json!({"present": false, "valid": false, "errors": ["mapping missing"]})
            }
        }
    };

    json!({
        "ok": true,
        "package_id": package_id,
        "schema_hint": package_manifest.as_ref()
            .and_then(|m| m.get("schema_version"))
            .cloned()
            .unwrap_or(json!(SCHEMA_VERSION)),
        "zip_bytes": zip_bytes,
        "entry_count": entries.len(),
        "file_count": entries.iter().filter(|e| !e.is_dir).count(),
        "csv_files": csv_files,
        "json_files": json_files,
        "other_files": other_files,
        "weather_csvs": weather_csvs,
        "equipment": equipment_dirs,
        "package_manifest": package_manifest,
        "column_map": column_map,
        "mapping_status": mapping_status,
        "session_config": session_config,
        "extract_path": extract_root.to_string_lossy(),
    })
}

fn read_json_if_present(root: &Path, name: &str) -> Option<Value> {
    // Prefer root; also accept single top-level folder wrapping contents.
    let direct = root.join(name);
    if direct.is_file() {
        return fs::read_to_string(&direct)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok());
    }
    if let Ok(rd) = fs::read_dir(root) {
        let mut dirs = Vec::new();
        for e in rd.flatten() {
            if e.path().is_dir() {
                dirs.push(e.path());
            }
        }
        if dirs.len() == 1 {
            let nested = dirs[0].join(name);
            if nested.is_file() {
                return fs::read_to_string(&nested)
                    .ok()
                    .and_then(|t| serde_json::from_str(&t).ok());
            }
        }
    }
    None
}

/// Prefer a Phase-1 versioned mapping document when present.
fn find_column_map(root: &Path) -> Option<Value> {
    let candidates = [
        root.join("column_map.json"),
        root.join("column_mappings.json"),
    ];
    for path in candidates {
        if let Ok(text) = fs::read_to_string(&path) {
            if let Ok(v) = serde_json::from_str::<Value>(&text) {
                if crate::model::csv_workbench::validate_column_map_document(&v).is_ok() {
                    return Some(v);
                }
                // Also accept if it looks like versioned scaffold with column_map object.
                if v.get("column_map").and_then(|c| c.as_object()).is_some()
                    && v.get("version").is_some()
                    && v.get("dataset_id").is_some()
                {
                    return Some(v);
                }
            }
        }
    }
    // Single nested building folder
    if let Ok(rd) = fs::read_dir(root) {
        let dirs: Vec<_> = rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        if dirs.len() == 1 {
            return find_column_map(&dirs[0]);
        }
    }
    None
}

fn resolve_building_root(extract_root: &Path) -> PathBuf {
    let has_manifest = extract_root.join("manifest.json").is_file()
        || extract_root.join("column_map.json").is_file();
    if has_manifest {
        return extract_root.to_path_buf();
    }
    if let Ok(rd) = fs::read_dir(extract_root) {
        let dirs: Vec<_> = rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        if dirs.len() == 1 {
            return dirs[0].clone();
        }
    }
    extract_root.to_path_buf()
}

fn collect_csv_files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    fn walk(dir: &Path, acc: &mut Vec<PathBuf>) {
        let Ok(rd) = fs::read_dir(dir) else {
            return;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, acc);
            } else if extension_of(&p).as_deref() == Some("csv") {
                acc.push(p);
            }
        }
    }
    walk(root, &mut out);
    out.sort();
    out
}

// --- HTTP handlers ---

fn decode_zip_from_body(body: &Value) -> Result<(String, Vec<u8>), String> {
    let filename = body
        .get("filename")
        .and_then(|v| v.as_str())
        .unwrap_or("package.zip")
        .to_string();
    let b64 = body
        .get("content_base64")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "content_base64 required".to_string())?;
    use base64::Engine;
    let raw = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .map_err(|e| format!("invalid base64: {e}"))?;
    Ok((filename, raw))
}

fn decode_zip_upload(content_type: &str, body: &[u8]) -> Result<(String, Vec<u8>), String> {
    let ct = content_type.to_ascii_lowercase();
    if ct.contains("application/json") {
        let v: Value = serde_json::from_slice(body).map_err(|e| format!("invalid json: {e}"))?;
        return decode_zip_from_body(&v);
    }
    if ct.contains("multipart/form-data") {
        let (files, _) = crate::csv_ingest::upload::parse_upload(content_type, body)?;
        if files.is_empty() {
            return Err("no files in upload".into());
        }
        let (name, raw) = files
            .into_iter()
            .find(|(n, _)| n.to_ascii_lowercase().ends_with(".zip"))
            .ok_or_else(|| "zip file required".to_string())?;
        return Ok((name, raw));
    }
    if ct.contains("application/zip")
        || ct.contains("application/x-zip-compressed")
        || ct.contains("application/octet-stream")
    {
        return Ok(("package.zip".into(), body.to_vec()));
    }
    Err("expected application/json, multipart/form-data, or application/zip".into())
}

/// Store raw ZIP under packages/{id}/upload.zip without extracting.
pub fn upload_handler(content_type: &str, body: &[u8]) -> Value {
    let caps = PackageCaps::default();
    let (filename, raw) = match decode_zip_upload(content_type, body) {
        Ok(v) => v,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if raw.len() as u64 > caps.max_zip_bytes {
        return json!({
            "ok": false,
            "error": format!("zip exceeds {} MB compressed limit", caps.max_zip_bytes / (1024 * 1024))
        });
    }
    // Quick structural check
    if let Err(e) = inspect_zip_bytes(&raw, &caps) {
        return json!({"ok": false, "error": e});
    }
    let package_id = new_package_id();
    let dir = package_dir(&package_id);
    if let Err(e) = fs::create_dir_all(&dir) {
        return json!({"ok": false, "error": e.to_string()});
    }
    let zip_path = dir.join("upload.zip");
    if let Err(e) = fs::write(&zip_path, &raw) {
        return json!({"ok": false, "error": e.to_string()});
    }
    let meta = json!({
        "package_id": package_id,
        "filename": filename,
        "zip_bytes": raw.len(),
        "status": "uploaded",
        "created_at": Utc::now().to_rfc3339(),
    });
    let _ = fs::write(
        dir.join("meta.json"),
        serde_json::to_string_pretty(&meta).unwrap_or_default(),
    );
    json!({
        "ok": true,
        "package_id": package_id,
        "filename": filename,
        "zip_bytes": raw.len(),
        "status": "uploaded",
    })
}

pub fn upload_json_handler(body: &Value) -> Value {
    match decode_zip_from_body(body) {
        Ok((filename, raw)) => {
            // Reuse multipart-less path via synthetic content-type
            let mut wrapped = json!({
                "filename": filename,
                "content_base64": null,
            });
            use base64::Engine;
            wrapped["content_base64"] =
                json!(base64::engine::general_purpose::STANDARD.encode(&raw));
            // Call through bytes path
            let bytes = serde_json::to_vec(&wrapped).unwrap_or_default();
            upload_handler("application/json", &bytes)
        }
        Err(e) => json!({"ok": false, "error": e}),
    }
}

/// Inspect (and extract) a package. Accepts `package_id` or inline ZIP bytes.
pub fn inspect_handler(content_type: &str, body: &[u8]) -> Value {
    let caps = PackageCaps::default();
    let ct = content_type.to_ascii_lowercase();
    if ct.contains("application/json") || body.starts_with(b"{") {
        let v: Value = match serde_json::from_slice(body) {
            Ok(v) => v,
            Err(e) => return json!({"ok": false, "error": format!("invalid json: {e}")}),
        };
        return inspect_json_handler(&v, &caps);
    }
    match decode_zip_upload(content_type, body) {
        Ok((filename, raw)) => inspect_and_extract_new(&filename, &raw, &caps),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn inspect_json_handler(body: &Value, caps: &PackageCaps) -> Value {
    if let Some(pid) = body.get("package_id").and_then(|v| v.as_str()) {
        return inspect_existing_package(pid, caps);
    }
    match decode_zip_from_body(body) {
        Ok((filename, raw)) => inspect_and_extract_new(&filename, &raw, caps),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

fn inspect_existing_package(package_id: &str, caps: &PackageCaps) -> Value {
    let dir = package_dir(package_id);
    let zip_path = dir.join("upload.zip");
    let raw = match fs::read(&zip_path) {
        Ok(b) => b,
        Err(_) => return json!({"ok": false, "error": "package not found"}),
    };
    let extract_root = dir.join("extract");
    let _ = fs::remove_dir_all(&extract_root);
    match extract_zip_bytes(&raw, &extract_root, caps) {
        Ok(entries) => {
            let mut manifest =
                build_manifest_from_extract(package_id, &extract_root, &entries, raw.len());
            manifest["status"] = json!("inspected");
            let _ = fs::write(
                dir.join("manifest.json"),
                serde_json::to_string_pretty(&manifest).unwrap_or_default(),
            );
            let mut meta = json!({"package_id": package_id, "status": "inspected"});
            if let Ok(t) = fs::read_to_string(dir.join("meta.json")) {
                if let Ok(m) = serde_json::from_str::<Value>(&t) {
                    meta = m;
                    meta["status"] = json!("inspected");
                }
            }
            let _ = fs::write(
                dir.join("meta.json"),
                serde_json::to_string_pretty(&meta).unwrap_or_default(),
            );
            manifest
        }
        Err(e) => {
            let _ = fs::remove_dir_all(&extract_root);
            json!({"ok": false, "error": e})
        }
    }
}

fn inspect_and_extract_new(filename: &str, raw: &[u8], caps: &PackageCaps) -> Value {
    if let Err(e) = inspect_zip_bytes(raw, caps) {
        return json!({"ok": false, "error": e});
    }
    let package_id = new_package_id();
    let dir = package_dir(&package_id);
    if let Err(e) = fs::create_dir_all(&dir) {
        return json!({"ok": false, "error": e.to_string()});
    }
    if let Err(e) = fs::write(dir.join("upload.zip"), raw) {
        return json!({"ok": false, "error": e.to_string()});
    }
    let extract_root = dir.join("extract");
    match extract_zip_bytes(raw, &extract_root, caps) {
        Ok(entries) => {
            let mut manifest =
                build_manifest_from_extract(&package_id, &extract_root, &entries, raw.len());
            manifest["filename"] = json!(filename);
            manifest["status"] = json!("inspected");
            let _ = fs::write(
                dir.join("manifest.json"),
                serde_json::to_string_pretty(&manifest).unwrap_or_default(),
            );
            let meta = json!({
                "package_id": package_id,
                "filename": filename,
                "zip_bytes": raw.len(),
                "status": "inspected",
                "created_at": Utc::now().to_rfc3339(),
            });
            let _ = fs::write(
                dir.join("meta.json"),
                serde_json::to_string_pretty(&meta).unwrap_or_default(),
            );
            manifest
        }
        Err(e) => {
            let _ = fs::remove_dir_all(&dir);
            json!({"ok": false, "error": e})
        }
    }
}

/// Stage CSVs from an inspected package into a CSV import session and draft a plan.
pub fn plan_handler(body: &Value) -> Value {
    let package_id = body
        .get("package_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if package_id.is_empty() {
        return json!({"ok": false, "error": "package_id required"});
    }
    let dir = package_dir(package_id);
    let extract_root = dir.join("extract");
    if !extract_root.is_dir() {
        // Auto-inspect if only uploaded
        let caps = PackageCaps::default();
        let inspected = inspect_existing_package(package_id, &caps);
        if inspected.get("ok") != Some(&json!(true)) {
            return inspected;
        }
    }
    if !extract_root.is_dir() {
        return json!({"ok": false, "error": "package not extracted — POST /api/csv/import/zip/inspect first"});
    }

    let building_root = resolve_building_root(&extract_root);
    let csvs = collect_csv_files(&building_root);
    if csvs.is_empty() {
        return json!({"ok": false, "error": "no CSV files found in package"});
    }

    let session = create_session();
    let session_id = session
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if session_id.is_empty() {
        return json!({"ok": false, "error": "failed to create import session"});
    }

    let mut staged = Vec::new();
    let mut errors = Vec::new();
    for path in &csvs {
        let rel = path.strip_prefix(&building_root).unwrap_or(path.as_path());
        let flat = flatten_rel_path(rel);
        let safe_name = match sanitize_filename(&flat) {
            Ok(s) => s,
            Err(e) => {
                errors.push(json!({"file": rel.to_string_lossy(), "error": e}));
                continue;
            }
        };
        let raw = match fs::read(path) {
            Ok(b) => b,
            Err(e) => {
                errors.push(json!({"file": safe_name, "error": e.to_string()}));
                continue;
            }
        };
        // Validate parseable before stage
        if let Err(e) = parse_csv_bytes(&raw, None) {
            errors.push(json!({"file": safe_name, "error": e}));
            continue;
        }
        match stage_file(&session_id, &safe_name, &raw) {
            Ok(meta) => {
                let mut m = meta;
                m["package_path"] = json!(rel.to_string_lossy());
                staged.push(m);
            }
            Err(e) => errors.push(json!({"file": safe_name, "error": e})),
        }
    }

    if staged.is_empty() {
        return json!({
            "ok": false,
            "error": "no CSV files could be staged",
            "errors": errors,
            "package_id": package_id,
        });
    }

    let mut session = load_session(&session_id).unwrap_or(session);
    session["files"] = json!(staged);
    session["status"] = json!("previewed");
    session["package_id"] = json!(package_id);

    let column_map = find_column_map(&building_root);
    let mut mapping_applied = false;
    let mut mapping_errors: Vec<String> = Vec::new();
    if let Some(ref doc) = column_map {
        match crate::model::csv_workbench::validate_column_map_document(doc) {
            Ok(()) => {
                let mut to_save = doc.clone();
                if let Some(obj) = to_save.as_object_mut() {
                    obj.insert("dataset_id".into(), json!(&session_id));
                }
                let saved = crate::model::csv_workbench::save_versioned_mapping(&json!({
                    "mapping": to_save
                }));
                mapping_applied = saved.get("ok") == Some(&json!(true));
                if !mapping_applied {
                    if let Some(e) = saved.get("error").and_then(|v| v.as_str()) {
                        mapping_errors.push(e.to_string());
                    }
                }
                session["column_map"] = to_save;
            }
            Err(e) => mapping_errors.push(e),
        }
    } else {
        mapping_errors.push("mapping missing".into());
    }

    // Draft UT3 plan from staged files
    let plan = crate::csv_ingest::plan::infer_ut3_plan_from_session(&session);
    session["plan"] = serde_json::to_value(&plan).unwrap_or(json!({}));
    session["status"] = json!("planned");
    let _ = save_session(&session_id, &session);

    // Persist package → session link
    let _ = fs::write(
        package_dir(package_id).join("plan.json"),
        serde_json::to_string_pretty(&json!({
            "package_id": package_id,
            "session_id": session_id,
            "staged_files": staged.len(),
            "mapping_applied": mapping_applied,
        }))
        .unwrap_or_default(),
    );

    json!({
        "ok": errors.is_empty(),
        "package_id": package_id,
        "session_id": session_id,
        "files": staged,
        "errors": errors,
        "plan": plan,
        "mapping_applied": mapping_applied,
        "mapping_errors": mapping_errors,
        "column_map": column_map,
        "hint": "Proceed to mapping (/api/fdd/mapping) then preflight/execute as with CSV upload",
    })
}

/// Unit-test helper: inspect without workspace side effects beyond extract dest.
pub fn inspect_zip_for_tests(data: &[u8], caps: &PackageCaps) -> Result<Vec<ZipEntryMeta>, String> {
    inspect_zip_bytes(data, caps)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::with_temp_workspace;
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::CompressionMethod;

    fn tight_caps() -> PackageCaps {
        PackageCaps {
            max_zip_bytes: 2 * 1024 * 1024,
            max_uncompressed_bytes: 2 * 1024 * 1024,
            max_entries: 50,
            max_ratio: 100.0,
            max_single_entry_bytes: 1024 * 1024,
        }
    }

    fn write_zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
        let mut cursor = Cursor::new(Vec::new());
        {
            let mut zip = zip::ZipWriter::new(&mut cursor);
            let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
            for (name, data) in entries {
                if name.ends_with('/') {
                    zip.add_directory(*name, opts).unwrap();
                } else {
                    zip.start_file(*name, opts).unwrap();
                    zip.write_all(data).unwrap();
                }
            }
            zip.finish().unwrap();
        }
        cursor.into_inner()
    }

    #[test]
    fn safe_member_rejects_traversal_and_absolute() {
        assert!(safe_member_path("../etc/passwd").is_err());
        assert!(safe_member_path("/etc/passwd").is_err());
        assert!(safe_member_path("C:/windows/system32").is_err());
        assert_eq!(
            safe_member_path("AHU_1/history_wide.csv").unwrap(),
            PathBuf::from("AHU_1/history_wide.csv")
        );
    }

    #[test]
    fn valid_simple_zip_inspects() {
        let data = write_zip(&[
            (
                "manifest.json",
                br#"{"schema_version":"openfdd_package_v1","building_id":"TINY","grid_minutes":5,"timezone":"UTC"}"#,
            ),
            ("AHU_1/history_wide.csv", b"timestamp,oa_t\n2024-01-01T00:00:00Z,55\n"),
        ]);
        let metas = inspect_zip_bytes(&data, &tight_caps()).unwrap();
        assert!(metas
            .iter()
            .any(|m| m.rel_path.ends_with("history_wide.csv")));
    }

    #[test]
    fn nested_folders_and_mapping_extract() {
        with_temp_workspace(|_| {
            let mapping = br#"{
              "version": 1,
              "dataset_id": "tiny",
              "timezone": "UTC",
              "timestamp_column": "timestamp",
              "equipment": "equip:ahu-1",
              "column_map": {"oa_t": "oa_t"}
            }"#;
            let data = write_zip(&[
                ("TINY/manifest.json", br#"{"schema_version":"openfdd_package_v1","building_id":"TINY","grid_minutes":5,"timezone":"UTC"}"#),
                ("TINY/column_map.json", mapping),
                ("TINY/AHU_1/history_wide.csv", b"timestamp,oa_t\n2024-01-01T00:00:00Z,55\n"),
                ("TINY/weather/history_wide.csv", b"timestamp,temp_f\n2024-01-01T00:00:00Z,33\n"),
            ]);
            let out = inspect_and_extract_new("tiny.zip", &data, &tight_caps());
            assert_eq!(out["ok"], json!(true), "{out}");
            assert!(out["csv_files"].as_array().unwrap().len() >= 2);
            assert_eq!(out["mapping_status"]["valid"], json!(true));
            let pid = out["package_id"].as_str().unwrap();
            let planned = plan_handler(&json!({"package_id": pid}));
            assert_eq!(planned["ok"], json!(true), "{planned}");
            assert!(planned["session_id"].as_str().unwrap().starts_with("csv-"));
            assert_eq!(planned["mapping_applied"], json!(true));
        });
    }

    #[test]
    fn traversal_attack_rejected() {
        let data = write_zip(&[("../escape.csv", b"a,b\n1,2\n")]);
        let err = inspect_zip_bytes(&data, &tight_caps()).unwrap_err();
        assert!(
            err.contains("traversal") || err.contains("absolute"),
            "{err}"
        );
    }

    #[test]
    fn oversized_entry_rejected() {
        let caps = PackageCaps {
            max_single_entry_bytes: 32,
            ..tight_caps()
        };
        let big = vec![b'x'; 64];
        let data = write_zip(&[("big.csv", &big)]);
        let err = inspect_zip_bytes(&data, &caps).unwrap_err();
        assert!(
            err.contains("single-file") || err.contains("exceeds"),
            "{err}"
        );
    }

    #[test]
    fn corrupted_zip_rejected() {
        let err = inspect_zip_bytes(b"not a zip file at all", &tight_caps()).unwrap_err();
        assert!(
            err.contains("corrupted") || err.contains("invalid"),
            "{err}"
        );
    }

    #[test]
    fn unsupported_type_rejected() {
        let data = write_zip(&[("malware.exe", b"MZ")]);
        let err = inspect_zip_bytes(&data, &tight_caps()).unwrap_err();
        assert!(err.contains("unsupported"), "{err}");
    }

    #[test]
    fn too_many_entries_rejected() {
        let caps = PackageCaps {
            max_entries: 2,
            ..tight_caps()
        };
        let data = write_zip(&[
            ("a.csv", b"a\n1\n"),
            ("b.csv", b"b\n1\n"),
            ("c.csv", b"c\n1\n"),
        ]);
        let err = inspect_zip_bytes(&data, &caps).unwrap_err();
        assert!(err.contains("too many"), "{err}");
    }
}
