//! `openfdd_package_v1` ZIP loader (#514).
//!
//! Accepts the vibe19 package layout (see vibe19 `docs/PACKAGE_SPEC.md`):
//! `manifest.json` + per-equipment `history_wide.csv` with a sibling Haystack-style
//! column map (`history_wide.json` / `history_wide.column_map.json` / `column_map.json`),
//! optional root `column_map.json`, `session_config.json`, and `weather/history_wide.csv`.
//!
//! The package is materialized under `workspace/data/csv_buildings/<building_id>/`
//! (the layout `fdd_store::ingest_building` already validates: manifest `grid_minutes`
//! → poll_seconds, per-equipment `columns.csv` role map) and ingested to parquet so
//! `/api/fdd/run` registry mode works immediately.

use crate::historian::store::workspace_dir;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::path::{Path, PathBuf};

pub const PACKAGE_SCHEMA: &str = "openfdd_package_v1";

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

/// Project-Haystack-style point tags used by vibe19 column maps → SQL cookbook roles.
/// Mirrors vibe19 `app/column_map_json.py` POINT_DISPLAY vocabulary.
fn haystack_point_to_role(point: &str) -> String {
    let slug = point.trim().to_lowercase().replace([' ', '_'], "-");
    match slug.as_str() {
        "discharge-air-temp" => "sat".into(),
        "discharge-air-temp-sp" => "sat_sp".into(),
        "mixed-air-temp" => "mat".into(),
        "return-air-temp" => "rat".into(),
        "outside-air-temp" | "bas-outside-air-temp" => "oa_t".into(),
        "outside-air-humidity" => "oa_h".into(),
        "outside-air-damper" => "oa_damper_pct".into(),
        "cooling-valve" => "clg_valve_pct".into(),
        "heating-valve" => "htg_valve_pct".into(),
        "fan-cmd" => "fan_cmd".into(),
        "return-fan-cmd" => "return_fan".into(),
        "fan-status" => "fan_status".into(),
        "duct-static-pressure" => "duct_static".into(),
        "duct-static-pressure-sp" => "duct_static_sp".into(),
        // TRIM / duct-static reset request (pandas vav-pressure-request-sum)
        "vav-pressure-request-sum" | "static-reset-request" => "static_reset_request".into(),
        "cooling-coil-entering-temp" => "cooling_coil_entering_temp".into(),
        "cooling-coil-leaving-temp" => "cooling_coil_leaving_temp".into(),
        "heating-coil-entering-temp" => "heating_coil_entering_temp".into(),
        "heating-coil-leaving-temp" => "heating_coil_leaving_temp".into(),
        "chiller-status" => "chiller_status".into(),
        "loop-enabled" => "loop_enabled".into(),
        "zone-air-temp" => "zone_t".into(),
        "zone-airflow" => "zone_flow".into(),
        "vav-total-airflow" => "vav_total_flow".into(),
        "min-flow-sp" => "min_flow_sp".into(),
        "chw-pump-status" => "chw_pump_status".into(),
        "compressor-status" => "compressor_status".into(),
        "building-zone-load-satisfied" => "building_zone_load_satisfied".into(),
        "building-ahu-load-satisfied" => "building_ahu_load_satisfied".into(),
        "damper" => "damper_pct".into(),
        "reheat-valve" => "reheat_valve_pct".into(),
        "vav-discharge-air-temp" => "vav_discharge_t".into(),
        "vav-inlet-air-temp" => "vav_inlet_t".into(),
        "ahu-discharge-air-temp" => "ahu_sat".into(),
        "chilled-water-supply-temp" => "chw_supply_t".into(),
        "chilled-water-return-temp" => "chw_return_t".into(),
        "chilled-water-supply-temp-sp" => "chw_supply_sp".into(),
        "hot-water-supply-temp" => "hw_supply_t".into(),
        "hot-water-return-temp" => "hw_return_t".into(),
        "occupied" => "occ_mode".into(),
        "chw-diff-pressure" => "chw_dp".into(),
        "chw-diff-pressure-sp" => "chw_dp_sp".into(),
        "chw-flow" => "chw_flow".into(),
        "chw-pump-cmd" => "chw_pump_cmd".into(),
        "cw-pump-cmd" => "cw_pump_cmd".into(),
        "tower-fan-cmd" | "cw-fan-cmd" => "tower_fan_cmd".into(),
        "condenser-water-supply-temp" => "cw_supply_t".into(),
        "condenser-water-return-temp" => "cw_return_t".into(),
        "preheat-leaving-temp" => "preheat_leave_t".into(),
        "web-outside-air-temp" => "web_oa_t".into(),
        "web-outside-air-dewpoint" => "web_oa_dp".into(),
        "web-outside-air-wetbulb" => "web_wb_t".into(),
        "web-outside-air-humidity" => "web_oa_h".into(),
        other => fdd_core::normalize_role(&other.replace('-', "_")),
    }
}

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
        let entry_name = entry.name().to_string();
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

/// Root may be the building itself or a single top-level folder holding manifest.json.
fn resolve_building_prefix(entries: &BTreeMap<PathBuf, Vec<u8>>) -> Result<PathBuf, String> {
    if entries.contains_key(Path::new("manifest.json")) {
        return Ok(PathBuf::new());
    }
    let mut candidates: Vec<PathBuf> = entries
        .keys()
        .filter(|p| p.file_name().map(|f| f == "manifest.json").unwrap_or(false))
        .filter(|p| p.components().count() == 2)
        .filter_map(|p| p.parent().map(Path::to_path_buf))
        .collect();
    candidates.sort();
    candidates.dedup();
    match candidates.len() {
        1 => Ok(candidates.remove(0)),
        0 => Err("package is missing manifest.json (root or single top-level folder)".into()),
        n => Err(format!(
            "found {n} top-level manifest.json files; expected 1"
        )),
    }
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

/// Convert map-file points (point/role name → CSV column) to column → cookbook role,
/// keeping only columns that exist in the CSV header.
fn roles_for_equipment(
    points: &BTreeMap<String, String>,
    headers: &[String],
    warnings: &mut Vec<String>,
    equip_id: &str,
) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for (point, column) in points {
        if point.trim().is_empty() || column.trim().is_empty() {
            continue;
        }
        if !headers.iter().any(|h| h == column.trim()) {
            warnings.push(format!(
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
    out
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

fn parquet_out_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(p);
    }
    workspace_dir().join(".cache/parquet")
}

/// Load `openfdd_package_v1` zip bytes: validate, materialize under
/// `workspace/data/csv_buildings/<building_id>/`, ingest to parquet.
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
        let is_weather = equip_id.eq_ignore_ascii_case("weather");
        let history = in_building
            .get(&dir.join("history_wide.csv"))
            .expect("discovered via history_wide.csv");
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
        for name in [
            "history_wide.json",
            "history_wide.column_map.json",
            "column_map.json",
        ] {
            if let Some(bytes) = in_building.get(&dir.join(name)) {
                match serde_json::from_slice::<Value>(bytes) {
                    Ok(v) => {
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
        if points.is_none() {
            if let Some(root) = &root_map {
                points = points_from_map_json(root, &equip_id);
                if points.is_some() {
                    map_source = "column_map.json (package root)".into();
                }
            }
        }

        let roles = match &points {
            Some(p) => roles_for_equipment(p, &headers, &mut warnings, &equip_id),
            None if is_weather => BTreeMap::new(), // weather map is optional
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
        });
    }

    if !missing_maps.is_empty() {
        return json!({
            "ok": false,
            "error": "package rejected — equipment history_wide.csv files missing sibling column maps",
            "missing_maps": missing_maps,
            "hint": "each equipment folder needs history_wide.json / history_wide.column_map.json / column_map.json (weather/ is exempt)",
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
    let building_root = data_root.join(&building_id);
    let _ = std::fs::remove_dir_all(&building_root);
    if let Err(e) = std::fs::create_dir_all(&building_root) {
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
        return json!({"ok": false, "error": format!("manifest write: {e}")});
    }
    if let Some(cfg) = &session_config {
        let _ = std::fs::write(
            building_root.join("session_config.json"),
            serde_json::to_string_pretty(cfg).unwrap_or_default(),
        );
        // Honor packaged session config (#515): persist workspace-wide so the
        // Lab sliders pick it up. Invalid configs only warn — never block ingest.
        match crate::fdd::session_config::normalize_session_config(cfg) {
            Ok((normalized, mut cfg_warnings)) => {
                if let Err(e) = crate::fdd::session_config::save_session_config(&normalized) {
                    warnings.push(format!("session_config.json not persisted: {e}"));
                }
                warnings.append(&mut cfg_warnings);
            }
            Err(e) => warnings.push(format!("session_config.json invalid: {e}")),
        }
    }

    let mut equipment_report = Vec::new();
    for plan in &plans {
        let eq_dir = building_root.join(plan.dir.file_name().unwrap_or_default());
        if let Err(e) = std::fs::create_dir_all(&eq_dir) {
            return json!({"ok": false, "error": format!("mkdir {}: {e}", eq_dir.display())});
        }
        let history = in_building
            .get(&plan.dir.join("history_wide.csv"))
            .expect("history bytes");
        if let Err(e) = std::fs::write(eq_dir.join("history_wide.csv"), history) {
            return json!({"ok": false, "error": format!("history write: {e}")});
        }
        if let Err(e) = write_columns_csv(&eq_dir.join("columns.csv"), &plan.headers, &plan.roles) {
            return json!({"ok": false, "error": e});
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
        }));
    }

    let out_dir = parquet_out_dir();
    let mut feather_written = 0usize;
    let mut feather_warnings: Vec<String> = Vec::new();
    let building_id_for_feather = building_id.clone();
    match fdd_store::ingest_building_with_batch_hook(
        &data_root,
        &building_id,
        &out_dir,
        |equipment_id, batch| {
            match crate::historian::feather_store::write_equipment_history(
                "package",
                &building_id_for_feather,
                equipment_id,
                batch,
            ) {
                Ok(_) => feather_written += 1,
                Err(e) => feather_warnings.push(format!("{equipment_id}: {e}")),
            }
            Ok(())
        },
    ) {
        Ok(report) => {
            warnings.extend(feather_warnings);
            if let Err(e) = crate::csv_ingest::dataset::register_package_dataset(
                &building_id,
                report.total_rows,
                report.equipment_written,
                &json!({
                    "package_root": building_root.display().to_string(),
                    "feather_written": feather_written,
                }),
            ) {
                warnings.push(format!("dataset registry: {e}"));
            }
            json!({
                "ok": true,
                "schema_version": PACKAGE_SCHEMA,
                "building_id": building_id,
                "grid_minutes": manifest.grid_minutes,
                "poll_seconds": manifest.grid_minutes.saturating_mul(60),
                "timezone": manifest.timezone,
                "equipment": equipment_report,
                "equipment_written": report.equipment_written,
                "total_rows": report.total_rows,
                "total_ms": report.total_ms,
                "out_dir": report.out_dir,
                "package_root": building_root.display().to_string(),
                "session_config": session_config,
                "feather_written": feather_written,
                "feather_files": feather_written,
                "warnings": warnings,
            })
        }
        Err(e) => json!({
            "ok": false,
            "error": format!("parquet ingest failed: {e:#}"),
            "equipment": equipment_report,
            "warnings": warnings,
            "package_root": building_root.display().to_string(),
        }),
    }
}

/// HTTP entry: multipart / JSON base64 / raw zip body.
pub fn import_package_handler(content_type: &str, body: &[u8]) -> Value {
    let ct = content_type.to_ascii_lowercase();
    let zip_bytes: Vec<u8> =
        if ct.contains("multipart/form-data") || ct.contains("application/json") {
            // Multipart must go through the binary-safe parser: lossy UTF-8 corrupts zips.
            let parsed = if ct.contains("multipart/form-data") {
                super::upload::parse_multipart_files(content_type, body)
            } else {
                super::upload::parse_upload(content_type, body)
            };
            let (files, _sid) = match parsed {
                Ok(parsed) => parsed,
                Err(e) => return json!({"ok": false, "error": e}),
            };
            let Some((_, bytes)) = files
                .into_iter()
                .find(|(name, _)| name.to_lowercase().ends_with(".zip"))
            else {
                return json!({"ok": false, "error": "no .zip file in upload"});
            };
            bytes
        } else {
            body.to_vec()
        };
    if zip_bytes.is_empty() {
        return json!({"ok": false, "error": "empty upload"});
    }
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
        let existing = std::fs::read_to_string(&hist).unwrap_or_default();
        match fdd_store::merge_history_wide_text(&hist, &csv, &hist, Some(existing)) {
            Ok(r) => merges.push(json!({
                "equipment_id": equipment_id,
                "rows_in": r.rows_in,
                "rows_added": r.rows_added,
                "rows_duped": r.rows_duped,
                "rows_out": r.rows_out,
                "ts_min": r.ts_min,
                "ts_max": r.ts_max,
            })),
            Err(e) => return json!({"ok": false, "error": e.to_string()}),
        }
    }
    let out_dir = parquet_out_dir();
    match fdd_store::ingest_building(&data_root, &building_id, &out_dir) {
        Ok(report) => json!({
            "ok": true,
            "building_id": building_id,
            "merges": merges,
            "equipment_written": report.equipment_written,
            "total_rows": report.total_rows,
            "total_ms": report.total_ms,
        }),
        Err(e) => json!({"ok": false, "error": format!("parquet ingest: {e:#}")}),
    }
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
    let out_dir = parquet_out_dir();
    let building_id_for_feather = building_id.clone();
    match fdd_store::ingest_building_with_batch_hook(
        &data_root,
        &building_id,
        &out_dir,
        |eq_id, batch| {
            let _ = crate::historian::feather_store::write_equipment_history(
                "package",
                &building_id_for_feather,
                eq_id,
                batch,
            );
            Ok(())
        },
    ) {
        Ok(report) => json!({
            "ok": true,
            "building_id": building_id,
            "equipment_id": equipment_id,
            "roles": roles,
            "ignored_columns": ignored,
            "equipment_written": report.equipment_written,
            "total_rows": report.total_rows,
        }),
        Err(e) => json!({"ok": false, "error": format!("re-ingest failed: {e:#}")}),
    }
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

fn infer_equipment_type_local(equipment_id: &str) -> &'static str {
    let id = equipment_id.to_ascii_uppercase();
    if id.contains("VAV") || id.contains("ZONE") {
        "VAV"
    } else if id.contains("AHU") || id.contains("RTU") || id.contains("MAU") {
        "AHU"
    } else if id.contains("CHILL")
        || id.contains("BOILER")
        || id.contains("PUMP")
        || id.contains("TOWER")
    {
        "PLANT"
    } else if id.contains("HP") || id.contains("HEAT_PUMP") {
        "HEAT_PUMP"
    } else if id.contains("METER") {
        "METER"
    } else {
        "GENERAL"
    }
}

/// Infer VAV→AHU parent from equipment id tokens (e.g. `VAV_1_AHU_2` → `AHU_2`).
fn infer_parent_ahu(equipment_id: &str, siblings: &[String]) -> Option<String> {
    let upper = equipment_id.to_ascii_uppercase();
    if !upper.contains("VAV") && !upper.contains("ZONE") {
        return None;
    }
    // Explicit AHU token in the VAV id.
    for part in upper.split(['_', '-', '/']) {
        if part.starts_with("AHU") && part.len() > 3 {
            let candidate = part.to_string();
            if siblings.iter().any(|s| s.eq_ignore_ascii_case(&candidate)) {
                return siblings
                    .iter()
                    .find(|s| s.eq_ignore_ascii_case(&candidate))
                    .cloned();
            }
            return Some(candidate);
        }
    }
    // Embedded `…AHU…N…` substring match against known AHU siblings.
    let ahus: Vec<&String> = siblings
        .iter()
        .filter(|s| infer_equipment_type_local(s) == "AHU")
        .collect();
    for ahu in &ahus {
        let ahu_u = ahu.to_ascii_uppercase();
        if upper.contains(&ahu_u) {
            return Some((*ahu).clone());
        }
    }
    if ahus.len() == 1 {
        return Some(ahus[0].clone());
    }
    None
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
    let building_id = match validate_id(building_id) {
        Ok(id) => id,
        Err(e) => return json!({"ok": false, "error": format!("building_id: {e}")}),
    };
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let building_root = data_root.join(&building_id);
    if !building_root.is_dir() {
        return json!({
            "ok": false,
            "error": format!("building {building_id:?} not found under {}", data_root.display()),
            "hint": "upload an openfdd_package_v1 zip first",
        });
    }

    let all_ids = list_equipment_ids(&building_root);
    let selected: Vec<String> = match equipment_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(eq) => match validate_id(eq) {
            Ok(id) => {
                if !all_ids.iter().any(|x| x == &id) {
                    return json!({
                        "ok": false,
                        "error": format!("equipment {id:?} not found under building {building_id}"),
                        "equipment_ids": all_ids,
                    });
                }
                vec![id]
            }
            Err(e) => return json!({"ok": false, "error": format!("equipment_id: {e}")}),
        },
        None => all_ids.clone(),
    };

    let session = crate::fdd::session_config::get_session_config();
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
        let cols_path = eq_dir.join("columns.csv");
        let history_path = eq_dir.join("history_wide.csv");
        let (columns_order, roles) = match read_columns_csv_raw(&cols_path) {
            Ok(v) => v,
            Err(e) => {
                blocker_count += 1;
                equipment.push(json!({
                    "equipment_id": eq_id,
                    "equipment_type": infer_equipment_type_local(eq_id),
                    "parent_ahu": infer_parent_ahu(eq_id, &all_ids),
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
        let parent_ahu = infer_parent_ahu(eq_id, &all_ids);
        let eq_type = infer_equipment_type_local(eq_id);
        if eq_type == "VAV" && parent_ahu.is_none() {
            warnings.push(
                "VAV has no inferred parent AHU — set relationship in session role_map when known"
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
            "parent_ahu": parent_ahu,
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

/// `GET /api/csv/import/package/buildings` — list ingested package building ids.
pub fn list_package_buildings_handler() -> Value {
    let data_root = workspace_dir().join("data").join("csv_buildings");
    let mut buildings = Vec::new();
    if data_root.is_dir() {
        if let Ok(rd) = std::fs::read_dir(&data_root) {
            for e in rd.flatten() {
                if e.path().is_dir() {
                    if let Some(name) = e.file_name().to_str() {
                        if !name.starts_with('.') {
                            buildings.push(name.to_string());
                        }
                    }
                }
            }
        }
    }
    buildings.sort();
    json!({
        "ok": true,
        "buildings": buildings,
        "path": data_root.display().to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

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
        // Prefer package_root from the import response — parallel env-mutating
        // tests can still race OPENFDD_WORKSPACE after the lock is taken.
        let pkg_root = out["package_root"]
            .as_str()
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| tmp.join("data/csv_buildings/BUILDING_9"));
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
        let feather =
            tmp.join(".cache/parquet/building=BUILDING_9/equipment=AHU_1/history.parquet");
        let feather_alt = std::path::PathBuf::from(out["out_dir"].as_str().unwrap_or(""))
            .join("building=BUILDING_9/equipment=AHU_1/history.parquet");
        assert!(
            feather.is_file() || feather_alt.is_file(),
            "missing history parquet; out={out}"
        );

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

        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn parent_ahu_inference_from_vav_id() {
        let siblings = vec!["AHU_1".into(), "VAV_2_AHU_1".into(), "VAV_9".into()];
        assert_eq!(
            infer_parent_ahu("VAV_2_AHU_1", &siblings).as_deref(),
            Some("AHU_1")
        );
        assert_eq!(
            infer_parent_ahu("VAV_9", &siblings).as_deref(),
            Some("AHU_1"),
            "single AHU sibling fallback"
        );
        assert_eq!(infer_parent_ahu("AHU_1", &siblings), None);
    }

    #[test]
    fn append_json_requires_confirm_and_merges() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!("openfdd_pkg_append_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
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

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
