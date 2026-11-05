//! Response hardening: nosniff on API paths and deliberate security.txt on bare central.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "integration tests are not cfg(test); allow-unwrap-in-tests does not cover tests/ binaries"
)]

use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::thread;
use std::time::Duration;

struct Server {
    child: Child,
    port: u16,
    workspace: PathBuf,
}

impl Server {
    fn start(auth: bool) -> Self {
        let port = TcpListener::bind("127.0.0.1:0")
            .expect("bind ephemeral")
            .local_addr()
            .expect("port")
            .port();
        let workspace = std::env::temp_dir().join(format!(
            "openfdd-sec-headers-{}-{}",
            std::process::id(),
            if auth { "auth" } else { "open" }
        ));
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
        if auth {
            cmd.env(
                "OPENFDD_JWT_SECRET",
                "sec-headers-test-secret-at-least-32b!!",
            )
            .env("OPENFDD_ADMIN_PASSWORD", "admin-sec-headers-pass");
        }
        let mut child = cmd.spawn().expect("start openfdd-central");

        for _ in 0..80 {
            let (status, _, body) = http("GET", port, "/api/health", None, None);
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

fn parse_headers(raw: &str) -> (u16, HashMap<String, String>, String) {
    let mut lines = raw.split("\r\n");
    let status = lines
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let mut headers = HashMap::new();
    for line in lines.by_ref() {
        if line.is_empty() {
            break;
        }
        if let Some((name, value)) = line.split_once(": ") {
            headers.insert(name.to_ascii_lowercase(), value.to_string());
        }
    }
    let body = lines.collect::<Vec<_>>().join("\r\n");
    (status, headers, body)
}

fn http(
    method: &str,
    port: u16,
    path: &str,
    body: Option<&str>,
    bearer: Option<&str>,
) -> (u16, HashMap<String, String>, String) {
    let host_port = format!("127.0.0.1:{port}");
    let mut stream = match TcpStream::connect(&host_port) {
        Ok(s) => s,
        Err(_) => return (0, HashMap::new(), String::new()),
    };
    stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
    let mut header_block =
        format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n");
    if let Some(token) = bearer {
        header_block.push_str(&format!("Authorization: Bearer {token}\r\n"));
    }
    if let Some(b) = body {
        header_block.push_str("Content-Type: application/json\r\n");
        header_block.push_str(&format!("Content-Length: {}\r\n\r\n", b.len()));
        header_block.push_str(b);
    } else {
        header_block.push_str("\r\n");
    }
    stream.write_all(header_block.as_bytes()).unwrap();
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
    parse_headers(&resp)
}

fn assert_nosniff(headers: &HashMap<String, String>, context: &str) {
    assert_eq!(
        headers.get("x-content-type-options").map(String::as_str),
        Some("nosniff"),
        "{context}: expected X-Content-Type-Options: nosniff, got {:?}",
        headers.get("x-content-type-options")
    );
}

#[test]
fn public_health_json_has_nosniff() {
    let server = Server::start(false);
    let (status, headers, body) = http("GET", server.port, "/api/health", None, None);
    assert_eq!(status, 200, "health body: {body}");
    assert!(
        headers
            .get("content-type")
            .is_some_and(|v| v.contains("application/json")),
        "expected JSON health, got {:?}",
        headers.get("content-type")
    );
    assert_nosniff(&headers, "GET /api/health");
}

#[test]
fn protected_route_401_has_nosniff() {
    let server = Server::start(true);
    let (status, headers, body) = http("GET", server.port, "/api/tenants", None, None);
    assert_eq!(status, 401, "expected 401 without JWT: {body}");
    assert_nosniff(&headers, "GET /api/tenants unauthenticated");
}

#[test]
fn unknown_path_404_has_nosniff() {
    let server = Server::start(false);
    let (status, headers, body) = http(
        "GET",
        server.port,
        "/api/this-route-does-not-exist-sec-headers",
        None,
        None,
    );
    assert_eq!(status, 404, "unexpected body: {body}");
    assert_nosniff(&headers, "GET unknown API path");
}

#[test]
fn security_txt_plain_text_on_bare_central() {
    let server = Server::start(false);
    let (status, headers, body) = http("GET", server.port, "/.well-known/security.txt", None, None);
    assert_eq!(status, 200, "security.txt body: {body}");
    let ctype = headers
        .get("content-type")
        .map(String::as_str)
        .unwrap_or("");
    assert!(
        ctype.starts_with("text/plain"),
        "expected text/plain, got {ctype}"
    );
    assert!(
        !body.trim_start().starts_with("<!"),
        "security.txt must not be HTML"
    );
    assert!(
        body.contains("Contact:") && body.contains("security/advisories/new"),
        "security.txt must include advisory contact"
    );
    assert_nosniff(&headers, "GET /.well-known/security.txt");
}
