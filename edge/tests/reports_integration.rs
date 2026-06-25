//! Report builder API integration tests.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use open_fdd_edge_prototype::auth::env_file::{generate_auth_env, parse_env_file, GenerateOptions};

static SERVER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn pick_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("bind ephemeral port")
        .local_addr()
        .expect("port")
        .port()
}

struct Server {
    _lock: std::sync::MutexGuard<'static, ()>,
    child: Child,
    port: u16,
    token: String,
}

impl Server {
    fn start() -> Self {
        let lock = SERVER_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let port = pick_port();
        let workspace =
            std::env::temp_dir().join(format!("openfdd-report-it-{}", std::process::id()));
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
            .env("OPENFDD_MODBUS_ENABLED", "0")
            .stdout(Stdio::null())
            .stderr(Stdio::piped());
        for (k, v) in &auth_map {
            cmd.env(k, v);
        }
        let mut child = cmd.spawn().expect("start edge");
        let mut ready = false;
        for _ in 0..120 {
            let (status, body) = http_raw(
                "GET",
                &format!("http://127.0.0.1:{port}/api/health"),
                None,
                None,
            );
            if status == 200 && body.contains("\"ok\"") {
                ready = true;
                break;
            }
            thread::sleep(Duration::from_millis(250));
        }
        if !ready {
            let mut stderr = String::new();
            if let Some(mut err) = child.stderr.take() {
                let _ = err.read_to_string(&mut stderr);
            }
            let _ = child.kill();
            let _ = child.wait();
            panic!("edge server did not become ready on port {port}; stderr:\n{stderr}");
        }
        let login = serde_json::json!({"username":"integrator","password":pw}).to_string();
        let (status, body) = http_post_json(
            &format!("http://127.0.0.1:{port}/api/auth/login"),
            &login,
            None,
        );
        assert_eq!(status, 200, "login failed: {body}");
        let token = serde_json::from_str::<serde_json::Value>(&body)
            .ok()
            .and_then(|v| {
                v.get("token")
                    .or_else(|| v.get("access_token"))
                    .and_then(|t| t.as_str())
                    .map(str::to_string)
            })
            .expect("login token missing");
        Server {
            _lock: lock,
            child,
            port,
            token,
        }
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn http_raw(method: &str, url: &str, body: Option<&str>, bearer: Option<&str>) -> (u16, String) {
    let url = url.strip_prefix("http://").unwrap_or(url);
    let (host_port, path) = url.split_once('/').unwrap_or((url, ""));
    let path = if path.is_empty() {
        "/".to_string()
    } else {
        format!("/{path}")
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
        req.push_str(&format!("Content-Length: {}\r\n", b.len()));
        req.push_str("\r\n");
        req.push_str(b);
    } else {
        req.push_str("\r\n");
    }
    if stream.write_all(req.as_bytes()).is_err() {
        return (0, String::new());
    }
    let mut buf = Vec::new();
    if stream.read_to_end(&mut buf).is_err() {
        return (0, String::new());
    }
    let resp = String::from_utf8_lossy(&buf);
    let status = resp
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let body = resp.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
    (status, body)
}

fn http_post_json(url: &str, body: &str, bearer: Option<&str>) -> (u16, String) {
    http_raw("POST", url, Some(body), bearer)
}

fn http_get(url: &str, token: &str) -> (u16, String) {
    http_raw("GET", url, None, Some(token))
}

#[test]
fn report_templates_requires_auth_or_returns_templates() {
    let srv = Server::start();
    let (status, body) = http_get(
        &format!("http://127.0.0.1:{}/api/reports/templates", srv.port),
        &srv.token,
    );
    assert_eq!(status, 200);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(json["ok"], true);
    assert!(!json["templates"].as_array().unwrap().is_empty());
}

#[test]
fn report_draft_reorder_and_pdf_download() {
    let srv = Server::start();
    let base = format!("http://127.0.0.1:{}", srv.port);
    let (status, draft_body) = http_post_json(
        &format!("{base}/api/reports/draft"),
        r#"{"title":"Integration Test Report"}"#,
        Some(&srv.token),
    );
    assert_eq!(status, 200);
    let draft: serde_json::Value = serde_json::from_str(&draft_body).unwrap();
    assert_eq!(draft["ok"], true);
    let report_id = draft["report_id"].as_str().unwrap();
    assert!(draft["sections"].as_array().unwrap().len() >= 5);

    let sections = draft["sections"].as_array().unwrap();
    let ids: Vec<String> = sections
        .iter()
        .filter_map(|s| s.get("id").and_then(|v| v.as_str()).map(str::to_string))
        .collect();
    let mut reversed = ids.clone();
    reversed.reverse();
    let reorder_body = serde_json::json!({"section_ids": reversed}).to_string();
    let (status, _) = http_post_json(
        &format!("{base}/api/reports/{report_id}/sections/reorder"),
        &reorder_body,
        Some(&srv.token),
    );
    assert_eq!(status, 200);

    let (status, render_body) = http_post_json(
        &format!("{base}/api/reports/{report_id}/render/pdf"),
        "{}",
        Some(&srv.token),
    );
    assert_eq!(status, 200);
    let render: serde_json::Value = serde_json::from_str(&render_body).unwrap();
    assert_eq!(render["ok"], true);

    let (status, pdf_bytes) = http_raw(
        "GET",
        &format!("{base}/api/reports/{report_id}/download.pdf"),
        None,
        Some(&srv.token),
    );
    assert_eq!(status, 200);
    assert!(pdf_bytes.starts_with("%PDF"));
    assert!(pdf_bytes.len() > 128);
}

#[test]
fn report_download_rejects_anonymous() {
    let srv = Server::start();
    let base = format!("http://127.0.0.1:{}", srv.port);
    let (status, draft_body) = http_post_json(
        &format!("{base}/api/reports/draft"),
        r#"{"title":"Auth Test"}"#,
        Some(&srv.token),
    );
    assert_eq!(status, 200);
    let report_id = serde_json::from_str::<serde_json::Value>(&draft_body).unwrap()["report_id"]
        .as_str()
        .unwrap()
        .to_string();
    let (status, _) = http_raw(
        "GET",
        &format!("{base}/api/reports/{report_id}/download.pdf"),
        None,
        None,
    );
    assert_eq!(status, 401);
}
