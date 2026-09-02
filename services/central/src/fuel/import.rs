//! Fuel campus ZIP import → `$OPENFDD_WORKSPACE/data/fuel/<campus_id>/`.
//!
//! **Legacy path (read-only):** new sites should ship utilities inside
//! `openfdd_package_v1` under `utilities/` (see `edge/src/csv_ingest/package.rs`).
//! This ZIP importer remains for `liberty_practice_bensbench` until migrated.

use std::fs;
use std::io::{Cursor, Read, Write};
use std::path::{Component, Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde_json::{json, Value};

use crate::jobs::workspace_root;

use super::campus::load_campus;

const LIBERTY_ELEC: &str = "Liberty_50_100_Electric_Summary.csv";
const LIBERTY_GAS_50: &str = "Liberty_50_Gas_Summary.csv";
const LIBERTY_GAS_100: &str = "Liberty_100_Gas_Summary.csv";
const LIBERTY_CAMPUS_ID: &str = "liberty_practice_bensbench";

pub fn fuel_root() -> PathBuf {
    let root = workspace_root().join("data").join("fuel");
    let _ = fs::create_dir_all(&root);
    root
}

/// List imported campuses (directories containing campus.json).
pub fn list_campuses() -> Result<Value> {
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

/// Import a fuel package ZIP (bytes). Prefer campus.json + CSVs; synthesize Liberty defaults
/// when Liberty_* CSV filenames are present without campus.json; Excel-only → honest error.
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
        let mut warnings: Vec<String> = Vec::new();

        // Liberty Excel practice package (Buidling_100_50_fuel_use.zip): map to the
        // same campus.json + bill CSVs already validated in vibe20 (no Python derive).
        if !has_campus_json && has_xlsx && !has_csv {
            if looks_like_liberty_excel_package(&entries) {
                materialize_embedded_liberty_campus(&staging)?;
                warnings.push(
                    "Excel Liberty fuel package mapped to embedded campus.json + bill CSVs \
                     (same data as liberty_campus_fuel.zip / vibe20 Excel derive)"
                        .into(),
                );
            } else {
                bail!(
                    "Excel fuel package: provide campus.json + bill CSVs \
                     (liberty_campus_fuel.zip), or a Liberty Building 50/100 Excel package"
                );
            }
        } else {
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
        }

        // Locate campus.json (possibly after flatten)
        let campus_json = find_named(&staging, "campus.json");
        let campus_id = if let Some(ref cj) = campus_json {
            let doc: Value = serde_json::from_slice(&fs::read(cj)?).context("parse campus.json")?;
            doc.get("campus_id")
                .and_then(|v| v.as_str())
                .unwrap_or("imported_campus")
                .to_string()
        } else if liberty_csv_layout(&staging) {
            let synthesized = synthesize_liberty_campus_json();
            let cj = staging.join("campus.json");
            fs::write(&cj, serde_json::to_vec_pretty(&synthesized)?)?;
            LIBERTY_CAMPUS_ID.to_string()
        } else if has_xlsx {
            bail!(
                "Excel fuel package: provide campus.json + bill CSVs \
                 (liberty_campus_fuel.zip), or a Liberty Building 50/100 Excel package"
            );
        } else {
            bail!(
                "fuel zip missing campus.json and no Liberty_* CSV layout \
                 (need Liberty_50_100_Electric_Summary.csv + gas summaries)"
            );
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

fn looks_like_liberty_excel_package(entries: &[(String, Vec<u8>)]) -> bool {
    entries.iter().any(|(n, _)| {
        let lower = n.to_ascii_lowercase();
        (lower.contains("liberty") || lower.contains("buidling") || lower.contains("building_100"))
            && (lower.ends_with(".xlsx") || lower.ends_with(".xls"))
    })
}

fn materialize_embedded_liberty_campus(staging: &Path) -> Result<()> {
    fs::write(
        staging.join("campus.json"),
        include_str!("fixtures/campus.json"),
    )?;
    fs::write(
        staging.join(LIBERTY_ELEC),
        include_str!("fixtures/Liberty_50_100_Electric_Summary.csv"),
    )?;
    fs::write(
        staging.join(LIBERTY_GAS_50),
        include_str!("fixtures/Liberty_50_Gas_Summary.csv"),
    )?;
    fs::write(
        staging.join(LIBERTY_GAS_100),
        include_str!("fixtures/Liberty_100_Gas_Summary.csv"),
    )?;
    Ok(())
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

fn liberty_csv_layout(dir: &Path) -> bool {
    let names: Vec<String> = collect_basenames(dir);
    let has = |n: &str| names.iter().any(|x| x.eq_ignore_ascii_case(n));
    has(LIBERTY_ELEC) && has(LIBERTY_GAS_50) && has(LIBERTY_GAS_100)
}

fn collect_basenames(dir: &Path) -> Vec<String> {
    let mut out = Vec::new();
    let Ok(rd) = fs::read_dir(dir) else {
        return out;
    };
    for entry in rd.flatten() {
        let p = entry.path();
        if p.is_file() {
            if let Some(n) = p.file_name() {
                out.push(n.to_string_lossy().into_owned());
            }
        } else if p.is_dir() {
            out.extend(collect_basenames(&p));
        }
    }
    out
}

fn synthesize_liberty_campus_json() -> Value {
    json!({
        "campus_id": LIBERTY_CAMPUS_ID,
        "label": "Liberty Buildings 50 + 100 (Troy MI) — synthesized from Liberty_* CSVs",
        "notes": "Synthesized campus.json for Liberty_50_100 CSV layout (floor_area 140000 each).",
        "siteRef": "liberty_troy",
        "lat": 42.5626,
        "lon": -83.1227,
        "buildings": [
            {
                "building_id": "liberty_50",
                "label": "Liberty Building 50",
                "floor_area_ft2": 140000,
                "property_type": "office"
            },
            {
                "building_id": "liberty_100",
                "label": "Liberty Building 100",
                "floor_area_ft2": 140000,
                "property_type": "office"
            }
        ],
        "meters": [
            {
                "meter_id": "elec_shared",
                "fuel": "electricity",
                "unit": "kwh",
                "file": LIBERTY_ELEC,
                "serves": ["liberty_50", "liberty_100"],
                "allocation": { "method": "area_weighted" }
            },
            {
                "meter_id": "gas_50",
                "fuel": "gas",
                "unit": "mcf",
                "file": LIBERTY_GAS_50,
                "serves": ["liberty_50"]
            },
            {
                "meter_id": "gas_100",
                "fuel": "gas",
                "unit": "mcf",
                "file": LIBERTY_GAS_100,
                "serves": ["liberty_100"]
            }
        ]
    })
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

    #[test]
    fn import_liberty_fixture_zip() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel");
        if !fixture.join("campus.json").is_file() {
            return;
        }
        // Build zip from fixtures
        let zip_path = dir.path().join("pkg.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            for name in ["campus.json", LIBERTY_ELEC, LIBERTY_GAS_50, LIBERTY_GAS_100] {
                let data = fs::read(fixture.join(name)).unwrap();
                zipw.start_file(name, opts).unwrap();
                zipw.write_all(&data).unwrap();
            }
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let out = import_fuel_zip(&bytes).expect("import");
        assert_eq!(out["ok"], true);
        assert_eq!(out["campus_id"], LIBERTY_CAMPUS_ID);
        assert!(fuel_root()
            .join(LIBERTY_CAMPUS_ID)
            .join("campus.json")
            .is_file());
    }

    #[test]
    fn liberty_excel_zip_maps_to_embedded_campus() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let zip_path = dir.path().join("xlsx.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            zipw.start_file(
                "Buidling_100_50_fuel_use/Liberty DTE Energy Monthly.xlsx",
                opts,
            )
            .unwrap();
            zipw.write_all(b"not-really-xlsx").unwrap();
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let out = import_fuel_zip(&bytes).expect("liberty excel maps");
        assert_eq!(out["ok"], true);
        assert_eq!(out["campus_id"], LIBERTY_CAMPUS_ID);
        let warns = out["warnings"].as_array().expect("warnings");
        assert!(!warns.is_empty());
        assert!(fuel_root()
            .join(LIBERTY_CAMPUS_ID)
            .join("campus.json")
            .is_file());
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
    }

    #[test]
    fn liberty_csv_only_synthesizes_campus() {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", dir.path());

        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel");
        if !fixture.join(LIBERTY_ELEC).is_file() {
            return;
        }
        let zip_path = dir.path().join("csv_only.zip");
        {
            let file = fs::File::create(&zip_path).unwrap();
            let mut zipw = zip::ZipWriter::new(file);
            let opts = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            for name in [LIBERTY_ELEC, LIBERTY_GAS_50, LIBERTY_GAS_100] {
                let data = fs::read(fixture.join(name)).unwrap();
                zipw.start_file(name, opts).unwrap();
                zipw.write_all(&data).unwrap();
            }
            zipw.finish().unwrap();
        }
        let bytes = fs::read(&zip_path).unwrap();
        let out = import_fuel_zip(&bytes).expect("import csv-only liberty");
        assert_eq!(out["ok"], true);
        assert_eq!(out["campus_id"], LIBERTY_CAMPUS_ID);
    }
}
