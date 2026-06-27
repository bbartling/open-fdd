//! Dashboard and fault API integration tests.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use open_fdd_edge_prototype::auth::env_file::{generate_auth_env, parse_env_file, GenerateOptions};

static SERVER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

struct Server {
    child: Child,
    port: u16,
    token: String,
}

impl Server {
    fn start() -> Self {
        let _lock = SERVER_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let workspace = std::env::temp_dir().join(format!(
            "openfdd-dash-it-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();
        let auth_path = workspace.join("auth.env.local");
        let generated = generate_auth_env(&GenerateOptions {
            path: auth_path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
        let pw = generated
            .plaintext_passwords
            .get("integrator")
            .cloned()
            .unwrap();
        let auth_map = parse_env_file(&std::fs::read_to_string(&auth_path).unwrap());
        let bin = env!("CARGO_BIN_EXE_open_fdd_edge_prototype");
        let frontend = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../frontend");
        let mut cmd = Command::new(bin);
        cmd.env("PORT", port.to_string())
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("FRONTEND_DIR", frontend)
            .env("OPENFDD_BACNET_ENABLED", "0")
            .env("OPENFDD_MODBUS_ENABLED", "0");
        for (k, v) in &auth_map {
            cmd.env(k, v);
        }
        let child = cmd.spawn().expect("start edge");
        for _ in 0..60 {
            let (status, _) = http_raw(
                "GET",
                &format!("http://127.0.0.1:{port}/api/health"),
                None,
                None,
            );
            if status == 200 {
                break;
            }
            thread::sleep(Duration::from_millis(200));
        }
        let login = serde_json::json!({"username":"integrator","password":pw}).to_string();
        let (_, body) = http_post_json(
            &format!("http://127.0.0.1:{port}/api/auth/login"),
            &login,
            None,
        );
        let token = serde_json::from_str::<serde_json::Value>(&body).unwrap()["token"]
            .as_str()
            .unwrap()
            .to_string();
        Self { child, port, token }
    }

    fn get(&self, path: &str) -> (u16, String) {
        http_raw(
            "GET",
            &format!("http://127.0.0.1:{}{}", self.port, path),
            None,
            Some(&self.token),
        )
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
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
    stream.set_read_timeout(Some(Duration::from_secs(5))).ok();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n");
    if let Some(token) = bearer {
        req.push_str(&format!("Authorization: Bearer {token}\r\n"));
    }
    if let Some(b) = body {
        req.push_str("Content-Type: application/json\r\n");
        req.push_str(&format!("Content-Length: {}\r\n\r\n{b}", b.len()));
    } else {
        req.push_str("\r\n");
    }
    stream.write_all(req.as_bytes()).unwrap();
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).unwrap();
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

fn http_post_json(url: &str, body: &str, bearer: Option<&str>) -> (u16, String) {
    http_raw("POST", url, Some(body), bearer)
}

#[test]
fn dashboard_summary_public_read() {
    let srv = Server::start();
    let (anon, body) = http_raw(
        "GET",
        &format!("http://127.0.0.1:{}/api/dashboard/summary", srv.port),
        None,
        None,
    );
    assert_eq!(anon, 200);
    assert!(body.contains("\"model_coverage\""));
    assert!(body.contains("\"historian_health\""));
    let (status, authed) = srv.get("/api/dashboard/summary");
    assert_eq!(status, 200);
    assert!(authed.contains("\"model_coverage\""));
}

#[test]
fn building_status_public_without_token() {
    let srv = Server::start();
    let (status, body) = http_raw(
        "GET",
        &format!("http://127.0.0.1:{}/api/building/status", srv.port),
        None,
        None,
    );
    assert_eq!(status, 200);
    let v: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v.get("ok").and_then(|x| x.as_bool()), Some(true));
}

#[test]
fn model_tree_and_commissioning_export_available() {
    let srv = Server::start();
    for path in [
        "/api/model/tree",
        "/api/model/commissioning-export",
        "/api/model/health",
    ] {
        let (status, body) = srv.get(path);
        assert_eq!(status, 200, "GET {path}");
        let v: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(v.get("ok").and_then(|x| x.as_bool()), Some(true));
    }
}

#[test]
fn fault_clear_requires_operator_role() {
    let srv = Server::start();
    let (anon, _) = http_post_json(
        &format!("http://127.0.0.1:{}/api/faults/fault-test/clear", srv.port),
        "{}",
        None,
    );
    assert_eq!(anon, 401);
    let (status, body) = http_post_json(
        &format!("http://127.0.0.1:{}/api/faults/fault-test/clear", srv.port),
        "{}",
        Some(&srv.token),
    );
    assert_eq!(status, 200);
    assert!(body.contains("\"ok\":true"));
}

#[test]
fn building_status_and_analytics_shape() {
    let srv = Server::start();
    let (status, body) = srv.get("/api/building/status");
    assert_eq!(status, 200);
    let v: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v.get("ok").and_then(|x| x.as_bool()), Some(true));
    assert!(v.get("model_counts").is_some());
    assert!(v.get("rule_count").is_some());

    let (a_status, a_body) = srv.get("/api/dashboard/analytics");
    assert_eq!(a_status, 200);
    let a: serde_json::Value = serde_json::from_str(&a_body).unwrap();
    assert!(a.get("rule_health").is_some());
    assert!(a.get("model").is_some());
}

#[test]
fn faults_list_and_csv_export() {
    let srv = Server::start();
    let (status, body) = srv.get("/api/faults");
    assert_eq!(status, 200);
    assert!(body.contains("\"faults\""));
    let (csv_status, csv) = srv.get("/api/faults/export.csv");
    assert_eq!(csv_status, 200);
    assert!(csv.starts_with("fault_id,rule_id"));
}

#[test]
fn desktop_mode_stack_shows_disabled_protocols() {
    let srv = Server::start();
    let (status, body) = srv.get("/api/health/stack");
    assert_eq!(status, 200);
    assert!(body.contains("\"status\":\"gray\""));
    assert!(body.contains("BACnet"));
}
