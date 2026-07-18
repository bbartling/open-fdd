//! Central HTTP integration: CSV upload → parquet ingest → FDD registry run.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};

static SERVER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

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
        let _lock = SERVER_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());

        let port = pick_port();
        let workspace =
            std::env::temp_dir().join(format!("openfdd-central-it-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();
        let parquet_root = workspace.join(".cache/parquet");
        std::fs::create_dir_all(&parquet_root).unwrap();

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let repo_root = manifest_dir.join("../..");
        let sql_rules = repo_root.join("sql_rules");
        assert!(
            sql_rules.join("registry.yaml").is_file(),
            "sql_rules missing"
        );

        let bin = env!("CARGO_BIN_EXE_openfdd-central");
        let mut child = Command::new(bin)
            .env("OPENFDD_CENTRAL_HOST", "127.0.0.1")
            .env("OPENFDD_CENTRAL_PORT", port.to_string())
            .env("OPENFDD_MQTT_ENABLED", "0")
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("OPENFDD_PARQUET_ROOT", &parquet_root)
            .env("OPENFDD_SQL_RULES_DIR", &sql_rules)
            .spawn()
            .expect("start openfdd-central");

        for _ in 0..80 {
            let (status, body) = http_raw(
                "GET",
                &format!("http://127.0.0.1:{port}/api/health"),
                None,
                None,
            );
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

    fn url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{}{}", self.port, path)
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.workspace);
    }
}

fn http_raw(method: &str, url: &str, body: Option<&str>, bearer: Option<&str>) -> (u16, String) {
    let url = url.strip_prefix("http://").unwrap();
    let (host_port, path) = url.split_once('/').unwrap_or((url, ""));
    let path = if path.is_empty() {
        "/"
    } else {
        &format!("/{path}")
    };
    let mut stream = match TcpStream::connect(host_port) {
        Ok(s) => s,
        Err(_) => return (0, String::new()),
    };
    stream.set_read_timeout(Some(Duration::from_secs(60))).ok();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n");
    if let Some(token) = bearer {
        req.push_str(&format!("Authorization: Bearer {token}\r\n"));
    }
    if let Some(b) = body {
        req.push_str("Content-Type: application/json\r\n");
        req.push_str(&format!("Content-Length: {}\r\n", b.len()));
        req.push_str("\r\n");
        req.push_str(b);
    } else {
        req.push_str("\r\n");
    }
    stream.write_all(req.as_bytes()).unwrap();
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

fn post_json(url: &str, body: &str) -> (u16, Value) {
    let (status, text) = http_raw("POST", url, Some(body), None);
    assert_ne!(status, 0, "HTTP connect failed for POST {url}");
    let json: Value = serde_json::from_str(&text).unwrap_or(json!({"raw": text}));
    (status, json)
}

#[test]
fn csv_upload_execute_then_fc1_registry_run() {
    let srv = Server::start();
    let fixture = include_str!("fixtures/fc1_duct_static.csv");
    let b64 = STANDARD.encode(fixture.as_bytes());

    let preview_body = json!({
        "files": [{
            "filename": "fc1_duct_static.csv",
            "content_base64": b64
        }]
    })
    .to_string();
    let (status, prev) = post_json(&srv.url("/api/csv/import/preview"), &preview_body);
    assert_eq!(status, 200, "preview status: {prev}");
    assert_eq!(prev.get("ok"), Some(&json!(true)), "preview: {prev}");
    let session_id = prev["session_id"].as_str().expect("session_id");

    let plan_body = json!({
        "session_id": session_id,
        "plan": {
            "mode": "append",
            "output_dataset_name": "fc1_smoke_job",
            "ambiguous_policy": "first",
            "fill_policy": "forward",
            "files": [{
                "filename": "fc1_duct_static.csv",
                "timestamp_column": "Date",
                "timezone": "America/Chicago",
                "value_columns": [
                    "duct_static",
                    "duct_static_sp",
                    "fan_cmd"
                ]
            }]
        }
    })
    .to_string();
    let (status, plan) = post_json(&srv.url("/api/csv/import/plan"), &plan_body);
    assert_eq!(status, 200, "plan: {plan}");
    assert_eq!(plan.get("ok"), Some(&json!(true)), "plan: {plan}");

    let preflight_body = json!({ "session_id": session_id }).to_string();
    let (status, preflight) = post_json(&srv.url("/api/csv/import/preflight"), &preflight_body);
    assert_eq!(status, 200, "preflight: {preflight}");
    assert_eq!(
        preflight.get("ok"),
        Some(&json!(true)),
        "preflight: {preflight}"
    );

    let execute_body = json!({ "session_id": session_id, "confirm": true }).to_string();
    let (status, execute) = post_json(&srv.url("/api/csv/import/execute"), &execute_body);
    assert_eq!(status, 200, "execute: {execute}");
    assert_eq!(execute.get("ok"), Some(&json!(true)), "execute: {execute}");
    let parquet = execute.get("parquet_ingest").expect("parquet_ingest");
    assert_eq!(
        parquet.get("ok"),
        Some(&json!(true)),
        "parquet_ingest: {parquet}"
    );

    let fdd_body = json!({
        "params": {
            "mode": "registry",
            "rule_ids": ["FC1"],
            "FC1": { "confirm_seconds": 60 }
        }
    })
    .to_string();
    let (status, fdd) = post_json(&srv.url("/api/fdd/run"), &fdd_body);
    assert_eq!(status, 200, "fdd run: {fdd}");
    assert_eq!(fdd.get("ok"), Some(&json!(true)), "fdd run: {fdd}");
    assert!(
        fdd.get("rules_run").and_then(|v| v.as_u64()).unwrap_or(0) >= 1,
        "expected FC1 to run: {fdd}"
    );
}
