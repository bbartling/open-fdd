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
    auth_path: std::path::PathBuf,
}

impl Server {
    fn start() -> Self {
        let _lock = SERVER_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let port = pick_port();
        let workspace = std::env::temp_dir().join(format!("openfdd-auth-it-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();
        let auth_path = workspace.join("auth.env.local");
        generate_auth_env(&GenerateOptions {
            path: auth_path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
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
                    auth_path,
                };
            }
            thread::sleep(Duration::from_millis(250));
        }
        let _ = child.kill();
        panic!("server did not become ready on port {port}");
    }

    fn url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{}{}", self.port, path)
    }

    fn integrator_password(&self) -> String {
        let text = std::fs::read_to_string(&self.auth_path).unwrap();
        parse_env_file(&text)
            .get("OFDD_INTEGRATOR_PASSWORD")
            .cloned()
            .unwrap()
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
    let path = if path.is_empty() { "/" } else { &format!("/{path}") };
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
    let login_body = login_json("integrator", &pw);
    let (status, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    assert_eq!(status, 200);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"].as_str().or(json["access_token"].as_str()).unwrap();
    let (stack_status, stack_body) = http_raw(
        "GET",
        &srv.url("/api/health/stack"),
        None,
        Some(token),
    );
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
    let text = std::fs::read_to_string(&srv.auth_path).unwrap();
    let map = parse_env_file(&text);
    let op_pw = map.get("OFDD_OPERATOR_PASSWORD").unwrap();
    let login_body = login_json("operator", op_pw);
    let (_, body) = http_post_json(&srv.url("/api/auth/login"), &login_body, None);
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    let token = json["token"].as_str().or(json["access_token"].as_str()).unwrap();
    let (status, _) = http_post_json(&srv.url("/api/modbus/scan"), "{}", Some(token));
    assert_eq!(status, 403);
}
