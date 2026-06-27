//! HTTP integration tests against the edge binary.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use std::path::PathBuf;

use open_fdd_edge_prototype::auth::env_file::{generate_auth_env, parse_env_file, GenerateOptions};

static SERVER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn pick_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
    listener.local_addr().expect("port").port()
}

struct Server {
    child: Child,
    port: u16,
    integrator_password: String,
    operator_password: String,
}

impl Server {
    fn start() -> Self {
        let _lock = SERVER_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let port = pick_port();
        let workspace =
            std::env::temp_dir().join(format!("openfdd-auth-it-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();
        let auth_path = workspace.join("auth.env.local");
        let generated = generate_auth_env(&GenerateOptions {
            path: auth_path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
        let integrator_password = generated
            .plaintext_passwords
            .get("integrator")
            .cloned()
            .expect("integrator password from generate");
        let operator_password = generated
            .plaintext_passwords
            .get("operator")
            .cloned()
            .expect("operator password from generate");
        let auth_map = parse_env_file(&std::fs::read_to_string(&auth_path).unwrap());

        let bin = env!("CARGO_BIN_EXE_open_fdd_edge_prototype");
        let frontend = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../frontend");
        let mut cmd = Command::new(bin);
        cmd.env("PORT", port.to_string())
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("FRONTEND_DIR", frontend);
        for (k, v) in &auth_map {
            cmd.env(k, v);
        }
        let mut child = cmd.spawn().expect("start edge binary");

        for _ in 0..60 {
            let (status, body) = http_raw(
                "GET",
                &format!("http://127.0.0.1:{port}/api/health"),
                None,
                None,
            );
            if status == 200 && body.contains("\"ok\"") {
                return Self {
                    child,
                    port,
                    integrator_password,
                    operator_password,
                };
            }
            thread::sleep(Duration::from_millis(250));
        }
        let _ = child.kill();
        let _ = child.wait();
        panic!("server did not become ready on port {port}");
    }

    fn url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{}{}", self.port, path)
    }

    fn integrator_password(&self) -> &str {
        &self.integrator_password
    }

    fn operator_password(&self) -> &str {
        &self.operator_password
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn http_raw(method: &str, url: &str, body: Option<&str>, bearer: Option<&str>) -> (u16, String) {
    let (status, headers, body) = http_raw_response(method, url, body, bearer);
    let _ = headers;
    (status, body)
}

fn http_raw_response(
    method: &str,
    url: &str,
    body: Option<&str>,
    bearer: Option<&str>,
) -> (u16, String, String) {
    let url = url.strip_prefix("http://").unwrap();
    let (host_port, path) = url.split_once('/').unwrap_or((url, ""));
    let path = if path.is_empty() {
        "/"
    } else {
        &format!("/{path}")
    };
    let mut stream = match TcpStream::connect(host_port) {
        Ok(s) => s,
        Err(_) => return (0, String::new(), String::new()),
    };
    stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
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
    (
        status,
        resp[..body_start.saturating_sub(4)].to_string(),
        resp[body_start..].to_string(),
    )
}

fn http_get(url: &str) -> String {
    http_raw("GET", url, None, None).1
}

fn http_post_json(url: &str, body: &str, bearer: Option<&str>) -> (u16, String) {
    http_raw("POST", url, Some(body), bearer)
}

#[test]
fn public_health_reports_auth_required() {
    let srv = Server::start();
    let body = http_get(&srv.url("/api/health"));
    assert!(body.contains("\"auth_required\":true"));
}

#[test]
fn stack_requires_bearer_token() {
    let srv = Server::start();
    let (status, _) = http_raw("GET", &srv.url("/api/health/stack"), None, None);
    assert_eq!(status, 401);
}

fn login_json(username: &str, password: &str) -> String {
    serde_json::json!({ "username": username, "password": password }).to_string()
}

#[test]
fn login_integrator_and_access_stack() {
    let srv = Server::start();
    let pw = srv.integrator_password();
    let login_body = login_json("integrator", pw);
    let (status, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    assert_eq!(status, 200);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (stack_status, stack_body) =
        http_raw("GET", &srv.url("/api/health/stack"), None, Some(token));
    assert_eq!(stack_status, 200);
    assert!(stack_body.contains("\"ok\":true"));
}

#[test]
fn rejects_self_mint_login() {
    let srv = Server::start();
    let (status, _) = http_post_json(
        &srv.url("/api/auth/login"),
        r#"{"sub":"agent","role":"agent"}"#,
        None,
    );
    assert_eq!(status, 401);
}

#[test]
fn wrong_password_fails() {
    let srv = Server::start();
    let (status, body) = http_post_json(
        &srv.url("/api/auth/login"),
        r#"{"username":"integrator","password":"wrong-password"}"#,
        None,
    );
    assert_eq!(status, 401);
    assert!(body.contains("invalid credentials"));
}

#[test]
fn operator_forbidden_on_modbus_scan() {
    let srv = Server::start();
    let login_body = login_json("operator", srv.operator_password());
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (status, _) = http_post_json(&srv.url("/api/modbus/scan"), "{}", Some(token));
    assert_eq!(status, 403);
}

#[test]
fn export_requires_authentication() {
    let srv = Server::start();
    let (status, _) = http_raw("GET", &srv.url("/api/export/historian.csv"), None, None);
    assert_eq!(status, 401);
}

#[test]
fn override_export_requires_auth() {
    let srv = Server::start();
    let (status, _) = http_raw("GET", &srv.url("/api/bacnet/overrides/export"), None, None);
    assert_eq!(status, 401);
}

#[test]
fn import_job_lifecycle() {
    let srv = Server::start();
    let pw = srv.integrator_password();
    let login_body = login_json("integrator", pw);
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (create_status, create_body) = http_post_json(
        &srv.url("/api/import/jobs"),
        r#"{"profile_id":"default_csv_import"}"#,
        Some(token),
    );
    assert_eq!(create_status, 200);
    let job_id = serde_json::from_str::<serde_json::Value>(&create_body).unwrap()["job_id"]
        .as_str()
        .unwrap()
        .to_string();
    let csv = "timestamp,equipment_id,oa_t,oa_h,duct_t,zn_t\n2026-06-24T00:00:00Z,equip:validation,62,45,55,72\n";
    let (upload_status, _) = http_raw(
        "POST",
        &srv.url(&format!("/api/import/jobs/{job_id}/upload")),
        Some(csv),
        Some(token),
    );
    assert_eq!(upload_status, 200);
    let (commit_status, commit_body) = http_raw(
        "POST",
        &srv.url(&format!("/api/import/jobs/{job_id}/commit")),
        None,
        Some(token),
    );
    assert_eq!(commit_status, 200);
    assert!(commit_body.contains("\"status\":\"completed\""));
}

#[test]
fn override_export_returns_attachment_filename() {
    let srv = Server::start();
    let pw = srv.integrator_password();
    let login_body = login_json("integrator", pw);
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (status, headers, csv_body) = http_raw_response(
        "GET",
        &srv.url("/api/bacnet/overrides/export"),
        None,
        Some(token),
    );
    assert_eq!(status, 200);
    assert!(headers.contains("Content-Type: text/csv"));
    assert!(headers.contains("filename=\"bacnet_overrides_export.csv\""));
    assert!(csv_body.starts_with("scanned_at,"));
}

#[test]
fn data_management_preview_requires_integrator() {
    let srv = Server::start();
    let pw = srv.integrator_password();
    let login_body = login_json("integrator", pw);
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (status, preview_body) = http_post_json(
        &srv.url("/api/data-management/purge/preview"),
        r#"{"historian_subdir":"validation","dry_run":true}"#,
        Some(token),
    );
    assert_eq!(status, 200);
    assert!(preview_body.contains("\"matched_row_count\""));
}

#[test]
fn data_management_execute_requires_confirmation() {
    let srv = Server::start();
    let pw = srv.integrator_password();
    let login_body = login_json("integrator", pw);
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (status, exec_body) = http_post_json(
        &srv.url("/api/data-management/purge/execute"),
        r#"{"all":true,"dry_run":true}"#,
        Some(token),
    );
    assert_eq!(status, 200);
    assert!(exec_body.contains("confirmation phrase"));
}

#[test]
fn data_management_summary_authenticated() {
    let srv = Server::start();
    let pw = srv.integrator_password();
    let login_body = login_json("integrator", pw);
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (status, summary) = http_raw(
        "GET",
        &srv.url("/api/data-management/summary"),
        None,
        Some(token),
    );
    assert_eq!(status, 200);
    assert!(summary.contains("\"total_row_count\""));
}

#[test]
fn operator_can_export_but_not_scan_once() {
    let srv = Server::start();
    let login_body = login_json("operator", srv.operator_password());
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"]
        .as_str()
        .or(json["access_token"].as_str())
        .unwrap();
    let (export_status, _, csv_body) = http_raw_response(
        "GET",
        &srv.url("/api/bacnet/overrides/export"),
        None,
        Some(token),
    );
    assert_eq!(export_status, 200);
    assert!(csv_body.contains("scanned_at"));
    let (scan_status, _) = http_post_json(
        &srv.url("/api/bacnet/overrides/scan-once"),
        "{}",
        Some(token),
    );
    assert_eq!(scan_status, 403);
}
