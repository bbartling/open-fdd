//! Milestone C0 — Jobs REST adversarial smoke (spawn real binary).

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};

struct Server {
    child: Child,
    port: u16,
    workspace: PathBuf,
}

impl Server {
    fn start() -> Self {
        Self::start_with_env(&[])
    }

    fn start_with_env(extra: &[(&str, &str)]) -> Self {
        let port = TcpListener::bind("127.0.0.1:0")
            .expect("bind ephemeral")
            .local_addr()
            .expect("port")
            .port();
        let workspace =
            std::env::temp_dir().join(format!("openfdd-jobs-api-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let repo_root = manifest_dir.join("../..");
        let sql_rules = repo_root.join("sql_rules");
        let bin = env!("CARGO_BIN_EXE_openfdd-central");
        let mut cmd = Command::new(bin);
        cmd.env("OPENFDD_CENTRAL_HOST", "127.0.0.1")
            .env("OPENFDD_CENTRAL_PORT", port.to_string())
            .env("OPENFDD_MQTT_ENABLED", "0")
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("OPENFDD_PARQUET_ROOT", workspace.join(".cache/parquet"))
            .env("OPENFDD_SQL_RULES_DIR", &sql_rules);
        for (k, v) in extra {
            cmd.env(k, v);
        }
        let mut child = cmd.spawn().expect("start openfdd-central");

        for _ in 0..80 {
            let (status, body) = http("GET", port, "/api/health", None, None);
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

fn http(
    method: &str,
    port: u16,
    path: &str,
    body: Option<&str>,
    bearer: Option<&str>,
) -> (u16, String) {
    let host_port = format!("127.0.0.1:{port}");
    let mut stream = match TcpStream::connect(&host_port) {
        Ok(s) => s,
        Err(_) => return (0, String::new()),
    };
    stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n")
        .into_bytes();
    if let Some(tok) = bearer {
        req.extend_from_slice(format!("Authorization: Bearer {tok}\r\n").as_bytes());
    }
    if let Some(b) = body {
        req.extend_from_slice(b"Content-Type: application/json\r\n");
        req.extend_from_slice(format!("Content-Length: {}\r\n\r\n", b.len()).as_bytes());
        req.extend_from_slice(b.as_bytes());
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
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let body = resp.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
    (status, body)
}

fn json_body(body: &str) -> Value {
    serde_json::from_str(body).unwrap_or(Value::Null)
}

#[test]
fn jobs_crud_runs_stale_findings_wattlab() {
    let server = Server::start();
    let port = server.port;

    let create = json!({"job_name": "C0 Job", "tags": ["c0"]}).to_string();
    let (st, body) = http("POST", port, "/api/jobs", Some(&create), None);
    assert_eq!(st, 201, "{body}");
    let job = &json_body(&body)["job"];
    let job_id = job["job_id"].as_str().unwrap();
    let rev = job["meta_revision"].as_str().unwrap().to_string();

    let (st, body) = http("GET", port, "/api/jobs", None, None);
    assert_eq!(st, 200);
    assert!(json_body(&body)["jobs"].as_array().unwrap().len() >= 1);

    let bad_patch = json!({
        "job_name": "stale",
        "expected_meta_revision": "deadbeefdeadbeefdeadbeefdeadbeef"
    })
    .to_string();
    let (st, body) = http(
        "PATCH",
        port,
        &format!("/api/jobs/{job_id}"),
        Some(&bad_patch),
        None,
    );
    assert_eq!(st, 409, "{body}");

    let good_patch = json!({
        "description": "updated",
        "expected_meta_revision": rev
    })
    .to_string();
    let (st, body) = http(
        "PATCH",
        port,
        &format!("/api/jobs/{job_id}"),
        Some(&good_patch),
        None,
    );
    assert_eq!(st, 200, "{body}");

    let comps = json!({
        "fingerprint_components": {
            "mapping_revision": "m1",
            "telemetry_content_hash": "t1",
            "config_revision": "c1",
            "rule_registry_hash": "r1",
            "engine_version": "1"
        },
        "run_type": "fdd_registry",
        "engine_version": "1",
        "rule_registry_hash": "r1"
    })
    .to_string();
    let (st, body) = http(
        "POST",
        port,
        &format!("/api/jobs/{job_id}/runs"),
        Some(&comps),
        None,
    );
    assert_eq!(st, 201, "{body}");
    let run_id = json_body(&body)["run"]["run_id"]
        .as_str()
        .unwrap()
        .to_string();

    let (st, _) = http(
        "PATCH",
        port,
        &format!("/api/jobs/{job_id}/runs/{run_id}"),
        Some(r#"{"status":"RUNNING"}"#),
        None,
    );
    assert_eq!(st, 200);

    let stale = json!({
        "fingerprint_components": {
            "mapping_revision": "m2",
            "telemetry_content_hash": "t1",
            "config_revision": "c1",
            "rule_registry_hash": "r1",
            "engine_version": "1"
        }
    })
    .to_string();
    let (st, body) = http(
        "POST",
        port,
        &format!("/api/jobs/{job_id}/runs/{run_id}/stale"),
        Some(&stale),
        None,
    );
    assert_eq!(st, 200, "{body}");
    let stale_json = json_body(&body);
    assert_eq!(stale_json["stale"], true);
    assert!(stale_json["reasons"]
        .as_array()
        .unwrap()
        .iter()
        .any(|r| r == "STALE_MAPPING"));

    let findings = json!({
        "findings": {
            "schema_version": "1",
            "findings": [{
                "finding_id": "finding-1",
                "correlation_key": "rule:X:equip:Y",
                "evidence": {"h": "1"}
            }]
        }
    })
    .to_string();
    let (st, body) = http(
        "PUT",
        port,
        &format!("/api/jobs/{job_id}/findings"),
        Some(&findings),
        None,
    );
    assert_eq!(st, 200, "{body}");

    let dispositions = json!({
        "schema_version": "1",
        "dispositions": [{
            "correlation_key": "rule:X:equip:Y",
            "status": "confirmed"
        }]
    })
    .to_string();
    let (st, body) = http(
        "PUT",
        port,
        &format!("/api/jobs/{job_id}/dispositions"),
        Some(&dispositions),
        None,
    );
    assert_eq!(st, 200, "{body}");

    let handoff = json!({"portable_zip_uri": "workspace://exports/x.zip"}).to_string();
    let (st, body) = http(
        "POST",
        port,
        &format!("/api/jobs/{job_id}/wattlab/handoffs"),
        Some(&handoff),
        None,
    );
    assert_eq!(st, 201, "{body}");

    let (st, body) = http(
        "POST",
        port,
        &format!("/api/jobs/{job_id}/archive"),
        Some("{}"),
        None,
    );
    assert_eq!(st, 200, "{body}");
    let (st, body) = http(
        "POST",
        port,
        &format!("/api/jobs/{job_id}/restore"),
        Some("{}"),
        None,
    );
    assert_eq!(st, 200, "{body}");

    let (st, body) = http("GET", port, "/api/jobs/job-../../../etc", None, None);
    assert!(st == 400 || st == 404, "{st} {body}");
}

#[test]
fn jobs_require_jwt_when_secret_set() {
    let server = Server::start_with_env(&[
        ("OPENFDD_JWT_SECRET", "c0-test-secret-at-least-32-bytes!!"),
        ("OPENFDD_ADMIN_PASSWORD", "admin-test-pass"),
    ]);
    let (st, body) = http("GET", server.port, "/api/jobs", None, None);
    assert_eq!(st, 401, "{body}");
}
