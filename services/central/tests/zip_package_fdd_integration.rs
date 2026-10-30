#![cfg(test)]
//! Central HTTP integration: openfdd_package_v1 zip upload → Timescale seed → FC1 registry run.
//!
//! Timescale is the only historian. With `OPENFDD_TEST_DATABASE_URL` the
//! server seeds `sample` and runs FC1. Without it, package import fails
//! closed with 503 and leaves nothing under `data/csv_buildings/`.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};

fn test_database_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn pick_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("bind ephemeral port")
        .local_addr()
        .expect("port")
        .port()
}

struct Server {
    child: Child,
    port: u16,
    workspace: PathBuf,
}

impl Server {
    fn start() -> Self {
        let port = pick_port();
        let workspace =
            std::env::temp_dir().join(format!("openfdd-central-zip-it-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let repo_root = manifest_dir.join("../..");
        let sql_rules = repo_root.join("sql_rules");
        assert!(
            sql_rules.join("registry.yaml").is_file(),
            "sql_rules missing"
        );

        let bin = env!("CARGO_BIN_EXE_openfdd-central");
        let mut command = Command::new(bin);
        command
            .env("OPENFDD_CENTRAL_HOST", "127.0.0.1")
            .env("OPENFDD_CENTRAL_PORT", port.to_string())
            .env("OPENFDD_MQTT_ENABLED", "0")
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("OPENFDD_SQL_RULES_DIR", &sql_rules)
            .env_remove("OPENFDD_DATABASE_URL")
            .env_remove("OPENFDD_HISTORIAN");
        if let Some(url) = test_database_url() {
            command
                .env("OPENFDD_DATABASE_URL", url)
                .env("OPENFDD_HISTORIAN", "timescale");
        }
        let mut child = command.spawn().expect("start openfdd-central");

        for _ in 0..80 {
            let (status, body) = http_raw("GET", port, "/api/health", None, "application/json");
            if status == 200 && body.contains("\"openfdd-central\"") {
                return Self {
                    child,
                    port,
                    workspace,
                };
            }
            thread::sleep(Duration::from_millis(250));
        }
        let _ = child.kill();
        let _ = child.wait();
        panic!("central did not become ready on port {port}");
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.workspace);
    }
}

/// Minimal HTTP/1.1 client supporting binary bodies (zip upload).
fn http_raw(
    method: &str,
    port: u16,
    path: &str,
    body: Option<&[u8]>,
    content_type: &str,
) -> (u16, String) {
    let host_port = format!("127.0.0.1:{port}");
    let mut stream = match TcpStream::connect(&host_port) {
        Ok(s) => s,
        Err(_) => return (0, String::new()),
    };
    stream.set_read_timeout(Some(Duration::from_secs(120))).ok();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n")
        .into_bytes();
    if let Some(b) = body {
        req.extend_from_slice(format!("Content-Type: {content_type}\r\n").as_bytes());
        req.extend_from_slice(format!("Content-Length: {}\r\n\r\n", b.len()).as_bytes());
        req.extend_from_slice(b);
    } else {
        req.extend_from_slice(b"\r\n");
    }
    stream.write_all(&req).unwrap();
    let mut buf = Vec::new();
    let mut chunk = [0u8; 8192];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(50));
                continue;
            }
            Err(e) => panic!("HTTP read failed: {e}"),
        }
    }
    let resp = String::from_utf8_lossy(&buf);
    let status = resp
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let body_start = resp.find("\r\n\r\n").map(|i| i + 4).unwrap_or(0);
    (status, resp[body_start..].to_string())
}

fn post_bytes(port: u16, path: &str, body: &[u8], content_type: &str) -> (u16, Value) {
    let (status, text) = http_raw("POST", port, path, Some(body), content_type);
    assert_ne!(status, 0, "HTTP connect failed for POST {path}");
    let json: Value = serde_json::from_str(&text).unwrap_or(json!({"raw": text}));
    (status, json)
}

/// FC1 fault data: duct static pinned below setpoint while the fan runs hard.
fn fc1_history_csv() -> String {
    let mut s = String::from("timestamp_utc,SF_SPD,DA_P,DA_P_SP\n");
    for i in 0..30 {
        s.push_str(&format!("2024-01-01T00:{:02}:00Z,0.95,0.10,1.40\n", i));
    }
    s
}

fn build_package_zip() -> Vec<u8> {
    let manifest = json!({
        "schema_version": "openfdd_package_v1",
        "building_id": "ZIP_BUILDING_1",
        "grid_minutes": 1,
        "timezone": "UTC"
    })
    .to_string();
    let column_map = json!({
        "equipType": "ahu",
        "points": {
            "fan-cmd": "SF_SPD",
            "duct-static-pressure": "DA_P",
            "duct-static-pressure-sp": "DA_P_SP"
        }
    })
    .to_string();
    let session_config = json!({
        "schema_version": "openfdd_session_v1",
        "display_units": "imperial"
    })
    .to_string();

    let mut cursor = std::io::Cursor::new(Vec::new());
    {
        let mut zw = zip::ZipWriter::new(&mut cursor);
        let opts = zip::write::SimpleFileOptions::default();
        for (name, content) in [
            ("ZIP_BUILDING_1/manifest.json", manifest.as_str()),
            (
                "ZIP_BUILDING_1/session_config.json",
                session_config.as_str(),
            ),
            ("ZIP_BUILDING_1/AHU_1/history_wide.csv", &fc1_history_csv()),
            (
                "ZIP_BUILDING_1/AHU_1/history_wide.json",
                column_map.as_str(),
            ),
        ] {
            zw.start_file(name, opts).unwrap();
            zw.write_all(content.as_bytes()).unwrap();
        }
        zw.finish().unwrap();
    }
    cursor.into_inner()
}

#[test]
fn zip_package_upload_then_fc1_registry_run() {
    let srv = Server::start();
    let zip_bytes = build_package_zip();

    let (status, pkg) = post_bytes(
        srv.port,
        "/api/csv/import/package",
        &zip_bytes,
        "application/zip",
    );
    if test_database_url().is_none() {
        assert_eq!(status, 503, "package without Timescale: {pkg}");
        assert_eq!(pkg.get("ok"), Some(&json!(false)), "package: {pkg}");
        let buildings = srv.workspace.join("data/csv_buildings");
        assert!(
            !buildings.join("ZIP_BUILDING_1").exists()
                && !buildings.join("ZIP_BUILDING_1.incoming").exists(),
            "import without Timescale left a package on disk"
        );
        return;
    }
    assert_eq!(status, 200, "package status: {pkg}");
    assert_eq!(pkg.get("ok"), Some(&json!(true)), "package: {pkg}");
    assert_eq!(pkg["historian"], json!("timescale"), "{pkg}");
    assert_eq!(pkg["building_id"], json!("ZIP_BUILDING_1"), "{pkg}");
    assert_eq!(pkg["grid_minutes"], json!(1), "{pkg}");
    assert_eq!(pkg["poll_seconds"], json!(60), "{pkg}");
    assert_eq!(
        pkg["equipment"][0]["roles"]["SF_SPD"],
        json!("fan_cmd"),
        "{pkg}"
    );
    assert_eq!(
        pkg["equipment"][0]["roles"]["DA_P"],
        json!("duct_static"),
        "{pkg}"
    );
    assert_eq!(
        pkg["session_config"]["display_units"],
        json!("imperial"),
        "session_config should surface for #515: {pkg}"
    );

    // Role mapping edit endpoint: re-map and re-ingest.
    let roles_body = json!({
        "building_id": "ZIP_BUILDING_1",
        "equipment_id": "AHU_1",
        "roles": {"SF_SPD": "fan_cmd", "DA_P": "duct_static", "DA_P_SP": "duct_static_sp"},
        "confirm": true
    })
    .to_string();
    let (status, upd) = post_bytes(
        srv.port,
        "/api/csv/import/package/roles",
        roles_body.as_bytes(),
        "application/json",
    );
    assert_eq!(status, 200, "roles: {upd}");
    assert_eq!(upd.get("ok"), Some(&json!(true)), "roles: {upd}");

    // #515: packaged session_config.json persists workspace-wide.
    let (status, sess) = {
        let (status, text) = http_raw(
            "GET",
            srv.port,
            "/api/fdd/session-config",
            None,
            "application/json",
        );
        (
            status,
            serde_json::from_str::<Value>(&text).unwrap_or(json!({"raw": text})),
        )
    };
    assert_eq!(status, 200, "session-config: {sess}");
    assert_eq!(sess["persisted"], json!(true), "{sess}");
    assert_eq!(sess["config"]["display_units"], json!("imperial"), "{sess}");

    // #515: PUT session config with rule params + role_map applied to the building.
    let put_body = json!({
        "building_id": "ZIP_BUILDING_1",
        "config": {
            "schema_version": "openfdd_session_v1",
            "display_units": "metric",
            "params": {"FC1": {"eps_dsp": 0.2}},
            "role_map": {"AHU_1": {"fan_cmd": "SF_SPD", "duct_static": "DA_P", "duct_static_sp": "DA_P_SP"}}
        }
    })
    .to_string();
    let (status, put) = {
        let (status, text) = http_raw(
            "PUT",
            srv.port,
            "/api/fdd/session-config",
            Some(put_body.as_bytes()),
            "application/json",
        );
        (
            status,
            serde_json::from_str::<Value>(&text).unwrap_or(json!({"raw": text})),
        )
    };
    assert_eq!(status, 200, "session-config put: {put}");
    assert_eq!(put.get("ok"), Some(&json!(true)), "put: {put}");
    assert_eq!(put["config"]["display_units"], json!("metric"), "{put}");
    assert_eq!(
        put["applied_role_map"][0]["ok"],
        json!(true),
        "role_map should apply to AHU_1: {put}"
    );

    let fdd_body = json!({
        "mode": "registry",
        "building_id": "ZIP_BUILDING_1",
        "rule_ids": ["FC1"],
        "params": {
            "FC1": { "confirm_seconds": 60 }
        }
    })
    .to_string();
    let (status, fdd) = post_bytes(
        srv.port,
        "/api/fdd/run",
        fdd_body.as_bytes(),
        "application/json",
    );
    assert_eq!(status, 200, "fdd run: {fdd}");
    assert_eq!(fdd.get("ok"), Some(&json!(true)), "fdd run: {fdd}");
    assert!(
        fdd.get("rules_run").and_then(|v| v.as_u64()).unwrap_or(0) >= 1,
        "expected FC1 to run: {fdd}"
    );
}
