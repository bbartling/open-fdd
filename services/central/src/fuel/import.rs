//! Fuel campus ZIP import → `$OPENFDD_WORKSPACE/data/fuel/<campus_id>/`.
//!
//! **Legacy path (read-only):** new sites should ship utilities inside
//! `openfdd_package_v1` under `utilities/` (see `edge/src/csv_ingest/package.rs`).
//! `campus_id` always comes from `campus.json` in the zip. The importer does not
//! invent a campus id or substitute a built-in dataset.

use std::fs;
use std::io::{Cursor, Read, Write};
use std::path::{Component, Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::jobs::workspace_root;

use super::campus::load_campus;

pub fn fuel_root() -> PathBuf {
    let root = workspace_root().join("data").join("fuel");
    let _ = fs::create_dir_all(&root);
    root
}

/// List imported campuses (directories containing campus.json).
///
/// Also materializes campuses from package `utilities_v1` under
/// `data/csv_buildings/<building_id>/utilities/` so Metering sees package
/// utilities without a separate fuel ZIP import.
pub fn list_campuses() -> Result<Value> {
    let _ = sync_campuses_from_package_utilities();
    let root = fuel_root();
    let mut campuses = Vec::new();
    if root.is_dir() {
        for entry in fs::read_dir(&root).with_context(|| format!("read {}", root.display()))? {
            let entry = entry?;
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            let json_path = path.join("campus.json");
            if !json_path.is_file() {
                continue;
            }
            match load_campus(&path) {
                Ok(c) => campuses.push(c.meta_json()),
                Err(e) => campuses.push(json!({
                    "campus_id": entry.file_name().to_string_lossy(),
                    "error": e.to_string(),
                })),
            }
        }
    }
    campuses.sort_by(|a, b| {
        let aid = a.get("campus_id").and_then(|v| v.as_str()).unwrap_or("");
        let bid = b.get("campus_id").and_then(|v| v.as_str()).unwrap_or("");
        aid.cmp(bid)
    });
    let active = campuses.first().cloned();
    Ok(json!({
        "ok": true,
        "fuel_root": root.display().to_string(),
        "count": campuses.len(),
        "campuses": campuses,
        "active": active,
    }))
}

/// Mirror `openfdd_package_v1` utilities into `$OPENFDD_WORKSPACE/data/fuel/<building_id>/`.
///
/// Idempotent: refreshes campus.json + electric monthly bill CSV when package utilities exist.
/// Does not invent meters — only promotes files already written by package ingest.
pub fn sync_campuses_from_package_utilities() -> Result<Vec<String>> {
    let csv_root = workspace_root().join("data").join("csv_buildings");
    if !csv_root.is_dir() {
        return Ok(Vec::new());
    }
    let mut synced = Vec::new();
    for entry in fs::read_dir(&csv_root).with_context(|| format!("read {}", csv_root.display()))? {
        let entry = entry?;
        let building_root = entry.path();
        if !building_root.is_dir() {
            continue;
        }
        let building_id = entry.file_name().to_string_lossy().to_string();
        if building_id.contains('/') || building_id.contains("..") {
            continue;
        }
        let bills = building_root
            .join("utilities")
            .join("electric")
            .join("monthly_bills.csv");
        if !bills.is_file() {
            continue;
        }
        match materialize_fuel_campus_from_utilities(&building_id, &bills) {
            Ok(()) => synced.push(building_id),
            Err(e) => tracing::warn!(
                building_id = %building_id,
                error = %e,
                "package utilities → fuel campus sync skipped"
            ),
        }
    }
    Ok(synced)
}

fn materialize_fuel_campus_from_utilities(building_id: &str, bills_src: &Path) -> Result<()> {
    let dest_dir = fuel_root().join(building_id);
    fs::create_dir_all(&dest_dir).with_context(|| format!("mkdir {}", dest_dir.display()))?;
    let bills_name = "electric_monthly_bills.csv";
    let dest_bills = dest_dir.join(bills_name);
    fs::copy(bills_src, &dest_bills)
        .with_context(|| format!("copy {} → {}", bills_src.display(), dest_bills.display()))?;
    let campus = json!({
        "campus_id": building_id,
        "label": building_id,
        "notes": "Materialized from openfdd_package_v1 utilities_v1 (electric monthly bills)",
        "siteRef": building_id,
        "buildings": [{
            "building_id": building_id,
            "label": building_id,
            "floor_area_ft2": 1.0,
            "property_type": "unknown"
        }],
        "meters": [{
            "meter_id": format!("{building_id}_electric"),
            "fuel": "electricity",
            "unit": "kwh",
            "file": bills_name,
            "serves": [building_id]
        }]
    });
    let campus_path = dest_dir.join("campus.json");
    fs::write(
        &campus_path,
        serde_json::to_string_pretty(&campus).context("serialize campus.json")?,
    )
    .with_context(|| format!("write {}", campus_path.display()))?;
    // Prove bills load before advertising the campus.
    let _ = load_campus(&dest_dir)?;
    Ok(())
}

pub fn get_campus_meta(campus_id: Option<&str>) -> Result<Value> {
    let root = fuel_root();
    if let Some(id) = campus_id {
        let dir = root.join(id);
        if !dir.join("campus.json").is_file() {
            bail!("campus not found: {id}");
        }
        let c = load_campus(&dir)?;
        return Ok(json!({
            "ok": true,
            "campus": c.meta_json(),
        }));
    }
    list_campuses()
}

/// Import a fuel package ZIP (bytes). `campus_id` comes from `campus.json`.
/// Excel-only workbooks and CSV layouts without `campus.json` are rejected.
pub fn import_fuel_zip(bytes: &[u8]) -> Result<Value> {
    let mut archive = zip::ZipArchive::new(Cursor::new(bytes))
        .context("invalid zip (not a fuel package archive)")?;

    let mut entries: Vec<(String, Vec<u8>)> = Vec::new();
    for i in 0..archive.len() {
        let mut file = archive.by_index(i).context("zip entry")?;
        let name = file.name().to_string();
        if name.ends_with('/') || file.is_dir() {
            continue;
        }
        // Zip-slip guard via enclosed_name
        let enclosed = file
            .enclosed_name()
            .ok_or_else(|| anyhow::anyhow!("zip-slip rejected: {name}"))?;
        let rel = enclosed.to_string_lossy().replace('\\', "/");
        let mut buf = Vec::new();
        file.read_to_end(&mut buf)
            .with_context(|| format!("read zip entry {rel}"))?;
        entries.push((rel, buf));
    }

    if entries.is_empty() {
        bail!("fuel zip is empty");
    }

    let has_xlsx = entries.iter().any(|(n, _)| {
        let lower = n.to_ascii_lowercase();
        lower.ends_with(".xlsx") || lower.ends_with(".xls")
    });
    let has_campus_json = entries
        .iter()
        .any(|(n, _)| file_name(n).eq_ignore_ascii_case("campus.json"));
    let has_csv = entries
        .iter()
        .any(|(n, _)| n.to_ascii_lowercase().ends_with(".csv"));

    // Extract to a temp staging dir under fuel_root/.staging
    let staging = fuel_root()
        .join(".staging")
        .join(uuid::Uuid::new_v4().to_string());
    fs::create_dir_all(&staging).context("create staging")?;

    let result = (|| -> Result<Value> {
        let warnings: Vec<String> = Vec::new();

        if !has_campus_json && has_xlsx && !has_csv {
            bail!(
                "Excel fuel package: provide campus.json with campus_id plus bill CSVs. \
                 Workbook names do not select a campus."
            );
        }

        // Flatten: write files using basename when under a single package folder,
        // otherwise preserve relative path (still zip-slip safe via Component::Normal).
        let strip_prefix = detect_common_prefix(&entries);

        for (rel, data) in &entries {
            let trimmed = if let Some(pref) = &strip_prefix {
                rel.strip_prefix(pref)
                    .map(|s| s.trim_start_matches('/'))
                    .unwrap_or(rel.as_str())
            } else {
                rel.as_str()
            };
            let out = safe_join(&staging, trimmed)
                .ok_or_else(|| anyhow::anyhow!("unsafe path in zip: {rel}"))?;
            if let Some(parent) = out.parent() {
                fs::create_dir_all(parent)?;
            }
            let mut f =
                fs::File::create(&out).with_context(|| format!("create {}", out.display()))?;
            f.write_all(data)?;
        }

        // Flatten bill CSVs / campus.json to staging root so meter file paths resolve.
        flatten_fuel_files_to_root(&staging)?;

        // Locate campus.json (possibly after flatten)
        let campus_json = find_named(&staging, "campus.json");
        let campus_id = if let Some(ref cj) = campus_json {
            let doc: Value = serde_json::from_slice(&fs::read(cj)?).context("parse campus.json")?;
            let id = doc
                .get("campus_id")
                .and_then(|v| v.as_str())
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .ok_or_else(|| anyhow::anyhow!("campus.json is missing campus_id"))?;
            if id.contains('/') || id.contains("..") {
                bail!("campus_id is not a single path segment");
            }
            id.to_string()
        } else if has_xlsx {
            bail!(
                "Excel fuel package: provide campus.json with campus_id plus bill CSVs. \
                 Workbook names do not select a campus."
            );
        } else {
            bail!("fuel zip missing campus.json; campus_id must be declared in the package");
        };

        // Validate load before promoting
        let _ = load_campus(&staging).context("campus failed validation after extract")?;

        let dest = fuel_root().join(&campus_id);
        if dest.exists() {
            fs::remove_dir_all(&dest).with_context(|| format!("replace {}", dest.display()))?;
        }
        fs::rename(&staging, &dest)
            .or_else(|_| -> Result<()> {
                // Cross-device fallback: copy then remove staging
                copy_dir_recursive(&staging, &dest)?;
                let _ = fs::remove_dir_all(&staging);
                Ok(())
            })
            .with_context(|| format!("promote staging → {}", dest.display()))?;

        let campus = load_campus(&dest)?;
        Ok(json!({
            "ok": true,
            "campus_id": campus_id,
            "path": dest.display().to_string(),
            "campus": campus.meta_json(),
            "warnings": warnings,
        }))
    })();

    if staging.exists() {
        let _ = fs::remove_dir_all(&staging);
    }
    result
}

fn file_name(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn detect_common_prefix(entries: &[(String, Vec<u8>)]) -> Option<String> {
    // If every path starts with the same first component and no file is at root, strip it.
    let mut firsts = std::collections::BTreeSet::new();
    let mut has_root_file = false;
    for (rel, _) in entries {
        let mut comps = Path::new(rel).components();
        match comps.next() {
            Some(Component::Normal(c)) => {
                let s = c.to_string_lossy().into_owned();
                if comps.next().is_none() {
                    // file at "root" of zip (single component)
                    has_root_file = true;
                }
                firsts.insert(s);
            }
            _ => return None,
        }
    }
    if has_root_file || firsts.len() != 1 {
        return None;
    }
    firsts.into_iter().next()
}

fn safe_join(root: &Path, rel: &str) -> Option<PathBuf> {
    let mut out = root.to_path_buf();
    for c in Path::new(rel).components() {
        match c {
            Component::Normal(s) => out.push(s),
            Component::CurDir => {}
            _ => return None,
        }
    }
    if out.starts_with(root) {
        Some(out)
    } else {
        None
    }
}

fn find_named(dir: &Path, name: &str) -> Option<PathBuf> {
    let direct = dir.join(name);
    if direct.is_file() {
        return Some(direct);
    }
    // shallow walk
    let Ok(rd) = fs::read_dir(dir) else {
        return None;
    };
    for entry in rd.flatten() {
        let p = entry.path();
        if p.is_file() && entry.file_name().eq_ignore_ascii_case(name) {
            return Some(p);
        }
        if p.is_dir() {
            let nested = p.join(name);
            if nested.is_file() {
                return Some(nested);
            }
        }
    }
    None
}

/// Move campus.json + *.csv from nested dirs up to `dir` so meter `file` paths resolve.
fn flatten_fuel_files_to_root(dir: &Path) -> Result<()> {
    let mut found: Vec<PathBuf> = Vec::new();
    fn walk(cur: &Path, acc: &mut Vec<PathBuf>) {
        let Ok(rd) = fs::read_dir(cur) else {
            return;
        };
        for entry in rd.flatten() {
            let p = entry.path();
            if p.is_dir() {
                walk(&p, acc);
            } else if p.is_file() {
                let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
                let lower = name.to_ascii_lowercase();
                if lower == "campus.json" || lower.ends_with(".csv") {
                    acc.push(p);
                }
            }
        }
    }
    walk(dir, &mut found);
    for src in found {
        let name = src.file_name().unwrap().to_owned();
        let dest = dir.join(&name);
        if src == dest {
            continue;
        }
        if dest.exists() {
            // Prefer root file already present.
            continue;
        }
        fs::rename(&src, &dest).or_else(|_| {
            fs::copy(&src, &dest)?;
            fs::remove_file(&src)?;
            Ok::<(), std::io::Error>(())
        })?;
    }
    Ok(())
}

fn copy_dir_recursive(src: &Path, dst: &Path) -> Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if from.is_dir() {
            copy_dir_recursive(&from, &to)?;
        } else {
            fs::copy(&from, &to)?;
        }
    }
    Ok(())
}

/// Handler response for HTTP import (bytes + optional content-type hint).
pub fn import_fuel_handler(content_type: &str, body: &[u8]) -> Value {
    let bytes = if content_type.contains("multipart") {
        // Best-effort: find zip magic in body (same spirit as raw uploads).
        if let Some(idx) = find_zip_magic(body) {
            &body[idx..]
        } else {
            body
        }
    } else if content_type.contains("json") {
        // { "zip_base64": "..." }
        match serde_json::from_slice::<Value>(body) {
            Ok(v) => {
                if let Some(b64) = v.get("zip_base64").and_then(|x| x.as_str()) {
                    match base64_decode(b64) {
                        Ok(decoded) => {
                            return match import_fuel_zip(&decoded) {
                                Ok(v) => v,
                                Err(e) => json!({"ok": false, "error": e.to_string()}),
                            };
                        }
                        Err(e) => return json!({"ok": false, "error": format!("base64: {e}")}),
                    }
                }
                body
            }
            Err(_) => body,
        }
    } else {
        body
    };

    match import_fuel_zip(bytes) {
        Ok(v) => v,
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

fn find_zip_magic(body: &[u8]) -> Option<usize> {
    body.windows(4)
        .position(|w| w == [0x50, 0x4B, 0x03, 0x04] || w == [0x50, 0x4B, 0x05, 0x06])
}

fn base64_decode(s: &str) -> Result<Vec<u8>> {
    // Minimal base64 without extra dep in lib path — use std via hex? Prefer
    // optional: central already has base64 in dev-deps only. Decode manually with
    // a tiny impl or use the engine from elsewhere.
    // Use a simple approach via the `base64` crate only in tests — for runtime,
    // accept raw zip primarily. For JSON path, use a local decoder.
    decode_base64_std(s)
}

fn decode_base64_std(input: &str) -> Result<Vec<u8>> {
    const TABLE: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let clean: Vec<u8> = input.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    let mut out = Vec::with_capacity(clean.len() * 3 / 4);
    let mut buf = [0u8; 4];
    let mut n = 0;
    for &b in &clean {
        if b == b'=' {
            break;
        }
        let val = TABLE
            .iter()
            .position(|&c| c == b)
            .ok_or_else(|| anyhow::anyhow!("invalid base64"))? as u8;
        buf[n] = val;
        n += 1;
        if n == 4 {
            out.push((buf[0] << 2) | (buf[1] >> 4));
            out.push((buf[1] << 4) | (buf[2] >> 2));
            out.push((buf[2] << 6) | buf[3]);
            n = 0;
        }
    }
    if n == 3 {
        out.push((buf[0] << 2) | (buf[1] >> 4));
        out.push((buf[1] << 4) | (buf[2] >> 2));
    } else if n == 2 {
        out.push((buf[0] << 2) | (buf[1] >> 4));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::jobs::WORKSPACE_ENV_TEST_LOCK;

    const FIXTURE_ELEC: &str = "Liberty_50_100_Electric_Summary.csv";
    const FIXTURE_GAS_A: &str = "Liberty_50_Gas_Summary.csv";
    const FIXTURE_GAS_B: &str = "Liberty_100_Gas_Summary.csv";
    const FIXTURE_CAMPUS_ID: &str = "demo_site";

    fn assert_no_lab_campus_dir() {
        assert!(!fuel_root().join("liberty_practice_bensbench").exists());
        assert!(!fuel_root().join("ACME").exists());
        assert!(!fuel_root().join("BUILDING_100").exists());
    }

    #[test]
    fn import_fixture_zip_uses_campus_json_id() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel");
        if !fixture.join("campus.json").is_file() {
            return;
        }
        let zip_path = dir.path().join("pkg.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            for name in ["campus.json", FIXTURE_ELEC, FIXTURE_GAS_A, FIXTURE_GAS_B] {
                let data = fs::read(fixture.join(name)).unwrap();
                zipw.start_file(name, opts).unwrap();
                zipw.write_all(&data).unwrap();
            }
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let out = import_fuel_zip(&bytes).expect("import");
        assert_eq!(out["ok"], true);
        assert_eq!(out["campus_id"], FIXTURE_CAMPUS_ID);
        assert!(fuel_root()
            .join(FIXTURE_CAMPUS_ID)
            .join("campus.json")
            .is_file());
        assert_no_lab_campus_dir();
    }

    #[test]
    fn named_excel_zip_does_not_infer_campus() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let zip_path = dir.path().join("xlsx.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            zipw.start_file("site_pack/monthly_bills.xlsx", opts)
                .unwrap();
            zipw.write_all(b"not-really-xlsx").unwrap();
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let err = import_fuel_zip(&bytes).unwrap_err().to_string();
        assert!(err.contains("campus.json"), "{err}");
        assert_no_lab_campus_dir();
    }

    #[test]
    fn unknown_excel_zip_errors_honestly() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let zip_path = dir.path().join("xlsx.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            zipw.start_file("random_site_bills.xlsx", opts).unwrap();
            zipw.write_all(b"not-really-xlsx").unwrap();
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let err = import_fuel_zip(&bytes).unwrap_err().to_string();
        assert!(err.contains("Excel fuel package"), "{err}");
        assert!(err.contains("campus.json"), "{err}");
    }

    #[test]
    fn csv_without_campus_json_does_not_invent_id() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel");
        if !fixture.join(FIXTURE_ELEC).is_file() {
            return;
        }
        let zip_path = dir.path().join("csv_only.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            for name in [FIXTURE_ELEC, FIXTURE_GAS_A, FIXTURE_GAS_B] {
                let data = fs::read(fixture.join(name)).unwrap();
                zipw.start_file(name, opts).unwrap();
                zipw.write_all(&data).unwrap();
            }
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let err = import_fuel_zip(&bytes).unwrap_err().to_string();
        assert!(err.contains("campus.json"), "{err}");
        assert_no_lab_campus_dir();
    }
}
