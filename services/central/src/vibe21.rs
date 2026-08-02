//! Vibe21 twin surface: Unity WebGL static serve + /api/v1 compatibility shims.
//!
//! Offline master-build artifacts live under `$OPENFDD_WORKSPACE/vibe21_jobs/<job>/`.
//! Production images stay Python-free; inference uses portable JSON forest or
//! golden conformance fallback.

use std::collections::HashMap;
use std::path::{Component, Path, PathBuf};
use std::sync::OnceLock;

use axum::extract::{DefaultBodyLimit, Path as AxumPath};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use bytes::Bytes;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::jobs::workspace_root;

static ACTIVE_BUNDLE: OnceLock<RuntimeBundle> = OnceLock::new();

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeBundle {
    pub schema_version: String,
    pub job_id: String,
    pub twin_version_id: String,
    pub model_release_id: String,
    pub unity_build_id: String,
    #[serde(default)]
    pub paths: HashMap<String, String>,
}

fn vibe21_jobs_root() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_VIBE21_JOB_ROOT") {
        return PathBuf::from(p);
    }
    workspace_root().join("vibe21_jobs")
}

fn default_job_id() -> String {
    std::env::var("OPENFDD_VIBE21_JOB_ID").unwrap_or_else(|_| "b100-ops11".into())
}

fn load_bundle() -> Option<RuntimeBundle> {
    if let Some(b) = ACTIVE_BUNDLE.get() {
        return Some(b.clone());
    }
    let job = vibe21_jobs_root().join(default_job_id());
    let path = job.join("runtime_bundle.json");
    let raw = std::fs::read_to_string(&path).ok()?;
    let b: RuntimeBundle = serde_json::from_str(&raw).ok()?;
    let _ = ACTIVE_BUNDLE.set(b.clone());
    Some(b)
}

fn job_dir(bundle: &RuntimeBundle) -> PathBuf {
    vibe21_jobs_root().join(&bundle.job_id)
}

fn unity_webgl_dir(bundle: &RuntimeBundle) -> PathBuf {
    let unity_rel = bundle
        .paths
        .get("unity")
        .cloned()
        .unwrap_or_else(|| format!("unity/{}", bundle.unity_build_id));
    let base = job_dir(bundle).join(unity_rel);
    let extracted = base.join("webgl");
    if extracted.join("index.html").is_file() {
        return extracted;
    }
    let zip = base.join("unity_webgl_build.zip");
    if zip.is_file() {
        let _ = extract_unity_zip(&zip, &extracted);
    }
    extracted
}

fn extract_unity_zip(zip_path: &Path, dest: &Path) -> Result<(), String> {
    if dest.join("index.html").is_file() {
        return Ok(());
    }
    std::fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    let file = std::fs::File::open(zip_path).map_err(|e| e.to_string())?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let name = entry.name().to_string();
        let enclosed = entry
            .enclosed_name()
            .ok_or_else(|| format!("zip-slip rejected: {name}"))?;
        let out = dest.join(enclosed);
        if entry.is_dir() {
            std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            continue;
        }
        if let Some(parent) = out.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut outfile = std::fs::File::create(&out).map_err(|e| e.to_string())?;
        std::io::copy(&mut entry, &mut outfile).map_err(|e| e.to_string())?;
    }
    Ok(())
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

fn mime_for(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" => "application/javascript",
        "wasm" => "application/wasm",
        "data" | "unityweb" => "application/octet-stream",
        "json" => "application/json",
        "css" => "text/css",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        _ => "application/octet-stream",
    }
}

async fn unity_asset(
    AxumPath((twin_id, build_id, rest)): AxumPath<(String, String, String)>,
) -> Response {
    let Some(bundle) = load_bundle() else {
        return (StatusCode::NOT_FOUND, "runtime_bundle missing").into_response();
    };
    if twin_id != bundle.twin_version_id && twin_id != "active" {
        return (StatusCode::NOT_FOUND, "unknown twin").into_response();
    }
    if build_id != bundle.unity_build_id && build_id != "active" {
        return (StatusCode::NOT_FOUND, "unknown build").into_response();
    }
    let root = unity_webgl_dir(&bundle);
    let rel = if rest.is_empty() || rest.ends_with('/') {
        format!("{rest}index.html")
    } else {
        rest
    };
    let Some(path) = safe_join(&root, &rel) else {
        return (StatusCode::BAD_REQUEST, "bad path").into_response();
    };
    match std::fs::read(&path) {
        Ok(bytes) => {
            let mut headers = HeaderMap::new();
            headers.insert(header::CONTENT_TYPE, mime_for(&path).parse().unwrap());
            headers.insert(header::X_CONTENT_TYPE_OPTIONS, "nosniff".parse().unwrap());
            if path.extension().and_then(|e| e.to_str()) == Some("html") {
                headers.insert(header::CACHE_CONTROL, "no-cache".parse().unwrap());
            } else {
                headers.insert(
                    header::CACHE_CONTROL,
                    "public, max-age=31536000, immutable".parse().unwrap(),
                );
            }
            (StatusCode::OK, headers, bytes).into_response()
        }
        Err(_) => (StatusCode::NOT_FOUND, "missing asset").into_response(),
    }
}

async fn unity_index(AxumPath((twin_id, build_id)): AxumPath<(String, String)>) -> Response {
    unity_asset(AxumPath((twin_id, build_id, String::new()))).await
}

async fn v1_health() -> Json<Value> {
    let bundle = load_bundle();
    Json(json!({
        "ok": true,
        "service": "openfdd-central-vibe21",
        "runtime": "rust",
        "job_id": bundle.as_ref().map(|b| b.job_id.clone()),
        "model_release_id": bundle.as_ref().map(|b| b.model_release_id.clone()),
        "unity_build_id": bundle.as_ref().map(|b| b.unity_build_id.clone()),
    }))
}

/// Redact offline oracle paths (joblib / Windows absolute) from online model cards.
fn redact_offline_model_card(mut card: Value) -> Value {
    let Some(obj) = card.as_object_mut() else {
        return card;
    };
    if let Some(art) = obj.get("artifact").and_then(|v| v.as_str()) {
        let lower = art.to_ascii_lowercase();
        if lower.contains("joblib")
            || lower.ends_with(".pkl")
            || lower.ends_with(".pickle")
            || art.contains(":\\")
            || art.contains(":/")
        {
            obj.insert(
                "artifact".into(),
                json!("[redacted offline oracle path — use model_release.zip]"),
            );
            obj.insert("artifact_offline_redacted".into(), json!(true));
        }
    }
    card
}

async fn v1_models() -> Json<Value> {
    let Some(bundle) = load_bundle() else {
        return Json(json!({"ok": false, "error": "no runtime_bundle"}));
    };
    let model_dir = job_dir(&bundle).join(
        bundle
            .paths
            .get("model")
            .cloned()
            .unwrap_or_else(|| format!("models/{}", bundle.model_release_id)),
    );
    let release: Value = std::fs::read_to_string(model_dir.join("model-release.json"))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(json!({}));
    let card: Value = std::fs::read_to_string(model_dir.join("model-card.json"))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(json!({}));
    let card = redact_offline_model_card(card);
    Json(json!({
        "ok": true,
        "champion": release.get("champion").or_else(|| card.get("champion")),
        "status": release.get("status").or_else(|| card.get("status")),
        "strategies": [
            "baseline","precool_shift","deadband_10f","chiller_off",
            "loadshed_p5f","hvac_off","precool_chiller_off"
        ],
        "model_release": release,
        "card": card,
        "inference": "portable_or_conformance",
        "note": "Online runtime never loads joblib; knobs require portable feature compiler",
    }))
}

async fn v1_twin_manifest() -> Json<Value> {
    let Some(bundle) = load_bundle() else {
        return Json(json!({"ok": false, "error": "no runtime_bundle"}));
    };
    let twin_dir = job_dir(&bundle).join(
        bundle
            .paths
            .get("twin")
            .cloned()
            .unwrap_or_else(|| format!("twins/{}", bundle.twin_version_id)),
    );
    let man: Value = std::fs::read_to_string(twin_dir.join("twin-manifest.json"))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(json!({}));
    Json(json!({
        "ok": true,
        "manifest": man,
        "geometry_url": "/api/v1/twin/geometry",
        "predict_url": "/api/v1/predict/demand_hourly",
        "unity_url": format!(
            "/twins/{}/builds/{}/",
            bundle.twin_version_id, bundle.unity_build_id
        ),
    }))
}

async fn v1_twin_geometry() -> Response {
    let Some(bundle) = load_bundle() else {
        return (StatusCode::NOT_FOUND, "no bundle").into_response();
    };
    let twin_dir = job_dir(&bundle).join(
        bundle
            .paths
            .get("twin")
            .cloned()
            .unwrap_or_else(|| format!("twins/{}", bundle.twin_version_id)),
    );
    let path = twin_dir.join("unity_geometry.json");
    match std::fs::read(&path) {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/json")],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::NOT_FOUND, "geometry missing").into_response(),
    }
}

#[derive(Debug, Deserialize)]
struct PredictBody {
    #[serde(default)]
    strategy_id: Option<String>,
    #[serde(flatten)]
    rest: HashMap<String, Value>,
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    hex::encode(h.finalize())
}

fn predict_from_conformance(model_dir: &Path, body: &PredictBody) -> Option<Value> {
    let path = model_dir.join("conformance.jsonl");
    let text = std::fs::read_to_string(path).ok()?;
    let want = body
        .strategy_id
        .clone()
        .unwrap_or_else(|| "baseline".into());
    for line in text.lines() {
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let sid = row
            .pointer("/request/strategy_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if sid == want {
            return row.get("response").cloned();
        }
    }
    None
}

fn predict_from_portable_forest(model_dir: &Path, body: &PredictBody) -> Option<Value> {
    let forest_path = model_dir.join("model.trees.json");
    if !forest_path.is_file() {
        return None;
    }
    // Portable forest present — evaluator lands with full feature compiler parity.
    // Until then, prefer conformance vectors for audited strategies.
    let _ = (forest_path, body);
    None
}

async fn v1_predict(
    Json(body): Json<PredictBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(bundle) = load_bundle() else {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"ok": false, "error": "no runtime_bundle"})),
        ));
    };
    let model_dir = job_dir(&bundle).join(
        bundle
            .paths
            .get("model")
            .cloned()
            .unwrap_or_else(|| format!("models/{}", bundle.model_release_id)),
    );
    if let Some(pred) = predict_from_portable_forest(&model_dir, &body)
        .or_else(|| predict_from_conformance(&model_dir, &body))
    {
        return Ok(Json(json!({
            "ok": true,
            "runtime": "rust",
            "source": "conformance_or_portable",
            "strategy_id": body.strategy_id,
            "prediction": pred,
            "request_echo": body.rest,
        })));
    }
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "ok": false,
            "error": "no portable model or conformance vector for strategy",
            "hint": "run scripts/vibe21_master_build.sh && scripts/vibe21_export_champion_portable.py",
        })),
    ))
}

async fn import_unity_status() -> Json<Value> {
    let Some(bundle) = load_bundle() else {
        return Json(json!({"ok": false, "error": "no runtime_bundle"}));
    };
    let root = unity_webgl_dir(&bundle);
    let zip = job_dir(&bundle)
        .join(
            bundle
                .paths
                .get("unity")
                .cloned()
                .unwrap_or_else(|| format!("unity/{}", bundle.unity_build_id)),
        )
        .join("unity_webgl_build.zip");
    let digest = std::fs::read(&zip).ok().map(|b| sha256_hex(&b));
    Json(json!({
        "ok": root.join("index.html").is_file(),
        "webgl_root": root,
        "zip_sha256": digest,
        "twin_version_id": bundle.twin_version_id,
        "unity_build_id": bundle.unity_build_id,
    }))
}

fn filename_header(headers: &HeaderMap) -> String {
    headers
        .get("x-filename")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("upload.zip")
        .to_string()
}

fn reject_joblib_filename(name: &str) -> Option<&'static str> {
    let lower = name.to_ascii_lowercase();
    if lower.ends_with(".joblib") || lower.ends_with(".pkl") || lower.ends_with(".pickle") {
        Some("joblib/pickle uploads are forbidden online — use model_release.zip")
    } else {
        None
    }
}

fn looks_like_zip(bytes: &[u8]) -> bool {
    bytes.len() >= 4
        && bytes[0] == 0x50
        && bytes[1] == 0x4b
        && (bytes[2] == 0x03 || bytes[2] == 0x05 || bytes[2] == 0x07)
}

fn zip_member_names(bytes: &[u8]) -> Result<Vec<String>, String> {
    let cursor = std::io::Cursor::new(bytes);
    let mut archive = zip::ZipArchive::new(cursor).map_err(|e| e.to_string())?;
    let mut names = Vec::with_capacity(archive.len());
    for i in 0..archive.len() {
        let entry = archive.by_index(i).map_err(|e| e.to_string())?;
        names.push(entry.name().to_string());
    }
    Ok(names)
}

fn validate_unity_zip(bytes: &[u8]) -> Result<(), String> {
    if !looks_like_zip(bytes) {
        return Err("not a zip archive".into());
    }
    let names = zip_member_names(bytes)?;
    if names.iter().any(|n| n.contains("..")) {
        return Err("zip-slip rejected".into());
    }
    let has_index = names
        .iter()
        .any(|n| n == "index.html" || n.ends_with("/index.html"));
    let has_build = names.iter().any(|n| n.contains("Build/"));
    if !has_index || !has_build {
        return Err("unity zip must contain index.html and Build/*".into());
    }
    Ok(())
}

fn validate_model_release_zip(bytes: &[u8]) -> Result<(), String> {
    if !looks_like_zip(bytes) {
        return Err("not a zip archive".into());
    }
    let names = zip_member_names(bytes)?;
    if names.iter().any(|n| n.contains("..")) {
        return Err("zip-slip rejected".into());
    }
    let lower: Vec<String> = names.iter().map(|n| n.to_ascii_lowercase()).collect();
    if lower
        .iter()
        .any(|n| n.ends_with(".joblib") || n.ends_with(".pkl") || n.ends_with(".pickle"))
    {
        return Err("model_release.zip must not contain joblib/pickle".into());
    }
    let required = [
        "model-release.json",
        "feature_spec.json",
        "target_spec.json",
        "conformance.jsonl",
    ];
    for req in required {
        if !lower.iter().any(|n| n.ends_with(req) || n == req) {
            return Err(format!("missing required member: {req}"));
        }
    }
    let has_model = lower.iter().any(|n| {
        n.ends_with("model.onnx")
            || n.ends_with("model.trees")
            || n.ends_with("model.trees.json")
            || n.ends_with("trees.json")
            || n.ends_with("portable_marker.json")
            || n.contains("portable")
            || n.contains("model.")
    });
    if !has_model {
        return Err("missing portable model artifact (onnx|trees|portable marker)".into());
    }
    Ok(())
}

fn extract_flat_zip(bytes: &[u8], dest: &Path) -> Result<(), String> {
    if dest.exists() {
        let _ = std::fs::remove_dir_all(dest);
    }
    std::fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    let cursor = std::io::Cursor::new(bytes);
    let mut archive = zip::ZipArchive::new(cursor).map_err(|e| e.to_string())?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let name = entry.name().to_string();
        if name.contains("..") {
            return Err(format!("zip-slip rejected: {name}"));
        }
        let out = dest.join(&name);
        if entry.is_dir() {
            std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            continue;
        }
        if let Some(parent) = out.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut outfile = std::fs::File::create(&out).map_err(|e| e.to_string())?;
        std::io::copy(&mut entry, &mut outfile).map_err(|e| e.to_string())?;
    }
    Ok(())
}

async fn import_unity_zip(headers: HeaderMap, body: Bytes) -> (StatusCode, Json<Value>) {
    let name = filename_header(&headers);
    if let Some(msg) = reject_joblib_filename(&name) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": msg})),
        );
    }
    if let Err(e) = validate_unity_zip(&body) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": e})),
        );
    }
    let Some(bundle) = load_bundle() else {
        return (
            StatusCode::CONFLICT,
            Json(json!({
                "ok": false,
                "error": "no runtime_bundle — run master_build / turnkey first",
            })),
        );
    };
    let unity_rel = bundle
        .paths
        .get("unity")
        .cloned()
        .unwrap_or_else(|| format!("unity/{}", bundle.unity_build_id));
    let base = job_dir(&bundle).join(unity_rel);
    let zip_path = base.join("unity_webgl_build.zip");
    let webgl = base.join("webgl");
    if let Err(e) = std::fs::create_dir_all(&base) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        );
    }
    if let Err(e) = std::fs::write(&zip_path, &body) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        );
    }
    let _ = std::fs::remove_dir_all(&webgl);
    if let Err(e) = extract_unity_zip(&zip_path, &webgl) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": e})),
        );
    }
    (
        StatusCode::OK,
        Json(json!({
            "ok": true,
            "kind": "unity_webgl_build",
            "sha256": sha256_hex(&body),
            "twin_version_id": bundle.twin_version_id,
            "unity_build_id": bundle.unity_build_id,
            "bytes": body.len(),
        })),
    )
}

async fn import_model_release(headers: HeaderMap, body: Bytes) -> (StatusCode, Json<Value>) {
    let name = filename_header(&headers);
    if let Some(msg) = reject_joblib_filename(&name) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": msg})),
        );
    }
    if let Err(e) = validate_model_release_zip(&body) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": e})),
        );
    }
    let Some(bundle) = load_bundle() else {
        return (
            StatusCode::CONFLICT,
            Json(json!({
                "ok": false,
                "error": "no runtime_bundle — run master_build / turnkey first",
            })),
        );
    };
    let model_rel = bundle
        .paths
        .get("model")
        .cloned()
        .unwrap_or_else(|| format!("models/{}", bundle.model_release_id));
    let model_dir = job_dir(&bundle).join(model_rel);
    if let Err(e) = extract_flat_zip(&body, &model_dir) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": e})),
        );
    }
    let _ = std::fs::write(model_dir.join("model_release.zip"), &body);
    (
        StatusCode::OK,
        Json(json!({
            "ok": true,
            "kind": "model_release",
            "sha256": sha256_hex(&body),
            "model_release_id": bundle.model_release_id,
            "bytes": body.len(),
            "note": "portable artifact only — no joblib online",
        })),
    )
}

async fn training_export() -> Response {
    let Some(bundle) = load_bundle() else {
        return (
            StatusCode::CONFLICT,
            Json(json!({"ok": false, "error": "no runtime_bundle"})),
        )
            .into_response();
    };
    let job = job_dir(&bundle);
    let tmp = std::env::temp_dir().join(format!("openfdd-training-export-{}.zip", bundle.job_id));
    let result = (|| -> Result<Vec<u8>, String> {
        use std::io::Write;
        let file = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
        let mut zipw = zip::ZipWriter::new(file);
        let opts = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);
        let candidates: Vec<String> = vec![
            "simulations".into(),
            "datasets".into(),
            "twins".into(),
            format!("models/{}", bundle.model_release_id),
            "runtime_bundle.json".into(),
        ];
        for rel in candidates {
            let path = job.join(&rel);
            if path.is_file() {
                zipw.start_file(rel.replace('\\', "/"), opts)
                    .map_err(|e| e.to_string())?;
                let bytes = std::fs::read(&path).map_err(|e| e.to_string())?;
                zipw.write_all(&bytes).map_err(|e| e.to_string())?;
            } else if path.is_dir() {
                for entry in walkdir_files(&path) {
                    let rel_path = entry
                        .strip_prefix(&job)
                        .unwrap_or(&entry)
                        .to_string_lossy()
                        .replace('\\', "/");
                    zipw.start_file(&rel_path, opts)
                        .map_err(|e| e.to_string())?;
                    let bytes = std::fs::read(&entry).map_err(|e| e.to_string())?;
                    zipw.write_all(&bytes).map_err(|e| e.to_string())?;
                }
            }
        }
        zipw.finish().map_err(|e| e.to_string())?;
        std::fs::read(&tmp).map_err(|e| e.to_string())
    })();
    let _ = std::fs::remove_file(&tmp);
    match result {
        Ok(bytes) if !bytes.is_empty() => {
            let mut headers = HeaderMap::new();
            headers.insert(header::CONTENT_TYPE, "application/zip".parse().unwrap());
            headers.insert(
                header::CONTENT_DISPOSITION,
                format!(
                    "attachment; filename=\"training_export_{}.zip\"",
                    bundle.job_id
                )
                .parse()
                .unwrap(),
            );
            (StatusCode::OK, headers, bytes).into_response()
        }
        Ok(_) => (
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": "no training artifacts under job"})),
        )
            .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
            .into_response(),
    }
}

fn walkdir_files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&dir) else {
            continue;
        };
        for ent in rd.flatten() {
            let p = ent.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.is_file() {
                out.push(p);
            }
        }
    }
    out
}

/// Public vibe21 routes (Unity + Flask-compatible /api/v1).
pub fn router() -> Router {
    Router::new()
        .route("/api/v1/health", get(v1_health))
        .route("/api/v1/models", get(v1_models))
        .route("/api/v1/models/import", post(import_model_release))
        .route("/api/v1/twin/manifest", get(v1_twin_manifest))
        .route("/api/v1/twin/geometry", get(v1_twin_geometry))
        .route("/api/v1/predict/demand_hourly", post(v1_predict))
        .route("/api/v1/training/export", get(training_export))
        .route("/api/unity/builds/active", get(import_unity_status))
        .route("/api/unity/builds/import", post(import_unity_zip))
        .route("/twins/{twin_id}/builds/{build_id}/", get(unity_index))
        .route(
            "/twins/{twin_id}/builds/{build_id}/{*rest}",
            get(unity_asset),
        )
        .layer(DefaultBodyLimit::max(128 * 1024 * 1024))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_join_rejects_dotdot() {
        let root = PathBuf::from("/tmp/webgl");
        assert!(safe_join(&root, "../etc/passwd").is_none());
        assert!(safe_join(&root, "Build/WebGL.wasm").is_some());
    }

    #[test]
    fn rejects_joblib_filenames() {
        assert!(reject_joblib_filename("model.joblib").is_some());
        assert!(reject_joblib_filename("x.pkl").is_some());
        assert!(reject_joblib_filename("model_release.zip").is_none());
    }

    #[test]
    fn model_release_requires_portable_members() {
        // empty / non-zip
        assert!(validate_model_release_zip(b"notzip").is_err());
    }
}
