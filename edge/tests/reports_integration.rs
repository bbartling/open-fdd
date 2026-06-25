//! Report builder API integration tests.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use open_fdd_edge_prototype::auth::env_file::{generate_auth_env, parse_env_file, GenerateOptions};

static SERVER_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

struct Server {
    _child: Child,
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
            "openfdd-report-it-{}-{:?}",
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
        let token = serde_json::from_str::<serde_json::Value>(&body)
            .ok()
            .and_then(|v| {
                v.get("token")
                    .or_else(|| v.get("access_token"))
                    .and_then(|t| t.as_str())
                    .map(str::to_string)
            })
            .unwrap();
        Server {
            _child: child,
            port,
            token,
        }
    }
}

fn http_raw(method: &str, url: &str, token: Option<&str>, body: Option<&str>) -> (u16, String) {
    let parsed = url.strip_prefix("http://").unwrap_or(url);
    let (host_port, path) = parsed.split_once('/').unwrap_or((parsed, ""));
    let path = format!("/{path}");
    let mut stream = TcpStream::connect(host_port).unwrap();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\n");
    if let Some(t) = token {
        req.push_str(&format!("Authorization: Bearer {t}\r\n"));
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
    let mut resp = String::new();
    stream.read_to_string(&mut resp).unwrap();
    let status = resp
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let body = resp.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
    (status, body)
}

fn http_post_json(url: &str, body: &str, token: Option<&str>) -> (u16, String) {
    http_raw("POST", url, token, Some(body))
}

fn http_get(url: &str, token: &str) -> (u16, String) {
    http_raw("GET", url, Some(token), None)
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
    let (_, draft_body) = http_post_json(
        &format!("{base}/api/reports/draft"),
        r#"{"title":"Integration Test Report"}"#,
        Some(&srv.token),
    );
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
        Some(&srv.token),
        None,
    );
    assert_eq!(status, 200);
    assert!(pdf_bytes.starts_with("%PDF"));
    assert!(pdf_bytes.len() > 128);
}

#[test]
fn report_download_rejects_anonymous() {
    let srv = Server::start();
    let base = format!("http://127.0.0.1:{}", srv.port);
    let (_, draft_body) = http_post_json(
        &format!("{base}/api/reports/draft"),
        r#"{"title":"Auth Test"}"#,
        Some(&srv.token),
    );
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
