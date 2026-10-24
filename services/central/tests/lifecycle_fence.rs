//! Two processes share one control-plane directory. One process runs a site
//! purge. The other creates an account, disables an account, and shares a site
//! after the purge has planned and before it deletes. Both identity updates and
//! the newly shared site files remain.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

type TestError = Box<dyn std::error::Error + Send + Sync>;

struct Proc {
    child: Child,
    port: u16,
}

impl Proc {
    fn spawn(workspace: &Path, barrier: &Path) -> Result<Self, TestError> {
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let port = listener.local_addr()?.port();
        drop(listener);
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let sql_rules = manifest_dir.join("../../sql_rules");
        let bin = env!("CARGO_BIN_EXE_openfdd-central");
        let child = Command::new(bin)
            .env("OPENFDD_CENTRAL_HOST", "127.0.0.1")
            .env("OPENFDD_CENTRAL_PORT", port.to_string())
            .env("OPENFDD_MQTT_ENABLED", "0")
            .env("OPENFDD_STARTER_SEED", "0")
            .env("OPENFDD_WORKSPACE", workspace)
            .env("OPENFDD_PARQUET_ROOT", workspace.join(".cache/parquet"))
            .env("OPENFDD_SQL_RULES_DIR", &sql_rules)
            .env("OPENFDD_LIFECYCLE_BARRIER_DIR", barrier)
            .env_remove("OPENFDD_DATABASE_URL")
            .env_remove("OPENFDD_JWT_SECRET")
            .env_remove("OPENFDD_RESET_DB")
            .env_remove("OPENFDD_ALLOW_DESTRUCTIVE_DB")
            .spawn()?;
        let proc = Self { child, port };
        let deadline = Instant::now() + Duration::from_secs(30);
        while Instant::now() < deadline {
            let (status, body) = http(proc.port, "GET", "/api/health", None)?;
            if status == 200 && body.contains("openfdd-central") {
                return Ok(proc);
            }
            thread::sleep(Duration::from_millis(100));
        }
        Err(format!("central did not become ready on port {port}").into())
    }
}

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn http(
    port: u16,
    method: &str,
    path: &str,
    body: Option<&str>,
) -> Result<(u16, String), TestError> {
    let host_port = format!("127.0.0.1:{port}");
    let mut stream = match TcpStream::connect(&host_port) {
        Ok(stream) => stream,
        Err(_) => return Ok((0, String::new())),
    };
    stream.set_read_timeout(Some(Duration::from_secs(60)))?;
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n")
        .into_bytes();
    if let Some(body) = body {
        req.extend_from_slice(b"Content-Type: application/json\r\n");
        req.extend_from_slice(format!("Content-Length: {}\r\n\r\n", body.len()).as_bytes());
        req.extend_from_slice(body.as_bytes());
    } else {
        req.extend_from_slice(b"\r\n");
    }
    stream.write_all(&req)?;
    let mut buf = Vec::new();
    let mut chunk = [0u8; 8192];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(err)
                if err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut =>
            {
                break;
            }
            Err(err) => return Err(err.into()),
        }
    }
    let text = String::from_utf8_lossy(&buf);
    let status = text
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse().ok())
        .unwrap_or(0);
    let body = text
        .split("\r\n\r\n")
        .nth(1)
        .unwrap_or("")
        .trim()
        .to_string();
    Ok((status, body))
}

fn marker(workspace: &Path, site: &str) -> bool {
    workspace
        .join("data/datasets")
        .join(site)
        .join("marker.txt")
        .is_file()
}

#[test]
fn two_processes_keep_shared_site_and_identity_updates() -> Result<(), TestError> {
    let workspace = std::env::temp_dir().join(format!(
        "openfdd-lifecycle-fence-{}-{}",
        std::process::id(),
        uuid::Uuid::new_v4()
    ));
    let _ = std::fs::remove_dir_all(&workspace);
    let barrier = workspace.join("barrier");
    std::fs::create_dir_all(&barrier)?;
    let cp = workspace.join("openfdd/control_plane");
    std::fs::create_dir_all(&cp)?;
    let sole = format!("w4bsole{}", uuid::Uuid::new_v4().simple());
    let shared = format!("w4bshare{}", uuid::Uuid::new_v4().simple());
    for site in [&sole, &shared] {
        let dataset = workspace.join("data/datasets").join(site);
        std::fs::create_dir_all(&dataset)?;
        std::fs::write(dataset.join("marker.txt"), b"fixture")?;
    }
    std::fs::write(
        cp.join("users.json"),
        serde_json::to_vec_pretty(&json!({
            "users": [
                {
                    "username": "w4bowner",
                    "role": "operator",
                    "tenant_ids": ["sole", "share"],
                    "password": "fixture",
                    "disabled": false,
                    "session_version": 0
                },
                {
                    "username": "w4bpeer",
                    "role": "operator",
                    "tenant_ids": ["peer"],
                    "password": "fixture",
                    "disabled": false,
                    "session_version": 0
                }
            ]
        }))?,
    )?;
    std::fs::write(
        cp.join("tenants.json"),
        serde_json::to_vec_pretty(&json!({
            "tenants": [
                {"id": "sole", "name": "sole", "building_ids": [sole]},
                {"id": "share", "name": "share", "building_ids": [shared]},
                {"id": "peer", "name": "peer", "building_ids": []},
                {"id": "created", "name": "created", "building_ids": []}
            ]
        }))?,
    )?;

    let deleter = Proc::spawn(&workspace, &barrier)?;
    let writer = Proc::spawn(&workspace, &barrier)?;
    let delete_port = deleter.port;
    let writer_port = writer.port;
    let delete_thread = thread::spawn(move || {
        http(
            delete_port,
            "DELETE",
            "/api/admin/users/w4bowner?confirm=true",
            None,
        )
    });
    let planned = barrier.join("planned");
    let deadline = Instant::now() + Duration::from_secs(30);
    while !planned.is_file() {
        if Instant::now() >= deadline {
            return Err("purge did not reach the overlap barrier".into());
        }
        thread::sleep(Duration::from_millis(20));
    }
    let (status, body) = http(
        writer_port,
        "PUT",
        "/api/admin/users",
        Some(
            &json!({
                "username": "w4bcreated",
                "role": "viewer",
                "tenant_ids": ["created"],
                "password": "fixture",
                "disabled": false
            })
            .to_string(),
        ),
    )?;
    assert_eq!(status, 200, "create: {body}");
    let (status, body) = http(
        writer_port,
        "POST",
        "/api/admin/users/w4bpeer/disabled",
        Some(r#"{"disabled":true}"#),
    )?;
    assert_eq!(status, 200, "disable: {body}");
    let (status, body) = http(
        writer_port,
        "PUT",
        "/api/admin/users",
        Some(
            &json!({
                "username": "w4bpeer",
                "role": "operator",
                "tenant_ids": ["peer", "share"],
                "disabled": true
            })
            .to_string(),
        ),
    )?;
    assert_eq!(status, 200, "share: {body}");
    std::fs::write(barrier.join("release"), b"release")?;
    let (status, body) = delete_thread
        .join()
        .map_err(|_| -> TestError { "delete thread panicked".into() })??;
    assert_eq!(status, 200, "delete: {body}");
    let parsed: Value = serde_json::from_str(&body)?;
    assert_eq!(
        parsed.get("phase").and_then(Value::as_str),
        Some("complete")
    );
    let purged = parsed
        .get("purged")
        .and_then(Value::as_array)
        .ok_or("delete response missing purged")?;
    assert!(
        purged
            .iter()
            .any(|row| row.get("building_id").and_then(Value::as_str) == Some(sole.as_str())),
        "sole site was not purged: {body}"
    );
    assert!(
        !purged
            .iter()
            .any(|row| row.get("building_id").and_then(Value::as_str) == Some(shared.as_str())),
        "shared site was purged: {body}"
    );
    assert!(!marker(&workspace, &sole), "sole marker remained");
    assert!(marker(&workspace, &shared), "shared marker was removed");
    let users: Value = serde_json::from_slice(&std::fs::read(cp.join("users.json"))?)?;
    let rows = users
        .get("users")
        .and_then(Value::as_array)
        .ok_or("users file missing users")?;
    assert!(
        !rows
            .iter()
            .any(|row| row.get("username").and_then(Value::as_str) == Some("w4bowner")),
        "owner returned: {users}"
    );
    let peer = rows
        .iter()
        .find(|row| row.get("username").and_then(Value::as_str) == Some("w4bpeer"))
        .ok_or_else(|| -> TestError { format!("peer missing: {users}").into() })?;
    assert_eq!(peer.get("disabled").and_then(Value::as_bool), Some(true));
    let member = peer
        .get("tenant_ids")
        .and_then(Value::as_array)
        .ok_or("peer missing tenant_ids")?;
    assert!(
        member.iter().any(|id| id.as_str() == Some("share")),
        "share was lost: {peer}"
    );
    assert!(
        rows.iter()
            .any(|row| row.get("username").and_then(Value::as_str) == Some("w4bcreated")),
        "created account was lost: {users}"
    );
    let ops: Value = serde_json::from_slice(&std::fs::read(cp.join("lifecycle_operations.json"))?)?;
    let phase = ops.pointer("/operations/0/phase").and_then(Value::as_str);
    assert_eq!(phase, Some("complete"), "operation record: {ops}");
    drop(deleter);
    drop(writer);
    let _ = std::fs::remove_dir_all(&workspace);
    Ok(())
}
