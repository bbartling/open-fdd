//! Central must expose the legacy edge dashboard families used by the UI shell (#549).

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
    fn start() -> Self {
        let port = TcpListener::bind("127.0.0.1:0")
            .expect("bind ephemeral")
            .local_addr()
            .expect("port")
            .port();
        let workspace =
            std::env::temp_dir().join(format!("openfdd-central-dash-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let repo_root = manifest_dir.join("../..");
        let sql_rules = repo_root.join("sql_rules");
        let bin = env!("CARGO_BIN_EXE_openfdd-central");
        let mut child = Command::new(bin)
            .env("OPENFDD_CENTRAL_HOST", "127.0.0.1")
            .env("OPENFDD_CENTRAL_PORT", port.to_string())
            .env("OPENFDD_MQTT_ENABLED", "0")
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("OPENFDD_PARQUET_ROOT", workspace.join(".cache/parquet"))
            .env("OPENFDD_SQL_RULES_DIR", &sql_rules)
            .spawn()
            .expect("start openfdd-central");

        for _ in 0..80 {
            let (status, body) = http("GET", port, "/api/health", None);
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

fn http(method: &str, port: u16, path: &str, body: Option<&str>) -> (u16, String) {
    let host_port = format!("127.0.0.1:{port}");
    let mut stream = match TcpStream::connect(&host_port) {
        Ok(s) => s,
        Err(_) => return (0, String::new()),
    };
    stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n")
        .into_bytes();
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

#[test]
fn dashboard_shell_routes_are_not_404() {
    let server = Server::start();
    let paths = [
        "/api/capabilities",
        "/api/health/stack",
        "/api/building/snapshot",
        "/api/faults/status",
        "/api/faults/summary",
        "/api/export/meta",
        "/api/data-management/summary",
        "/api/host/stats",
        "/api/fdd-schema/tables",
        "/api/fdd-rules",
        "/api/reports",
        "/api/reports/templates",
    ];
    for path in paths {
        let (status, body) = http("GET", server.port, path, None);
        assert_ne!(status, 404, "{path} returned 404: {body}");
        assert!(
            (200..500).contains(&status),
            "{path} unexpected status {status}: {body}"
        );
    }

    let (status, body) = http(
        "POST",
        server.port,
        "/api/reports/draft",
        Some(r#"{"title":"smoke draft","template_id":"blank"}"#),
    );
    assert_ne!(status, 404, "POST /api/reports/draft returned 404: {body}");
}
