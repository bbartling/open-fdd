//! Kali Wave P2c — pre-auth disclosure + tenant list ACL (auth ON).
//! Failing tests first: anonymous must not see tenants / topology / MCP.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use jsonwebtoken::{encode, EncodingKey, Header};
use serde_json::{json, Value};

static SERVER_LOCK: Mutex<()> = Mutex::new(());

const SECRET: &str = "kali-p2c-test-secret-at-least-32b!!";

struct Server {
    child: Child,
    port: u16,
    workspace: PathBuf,
    _guard: std::sync::MutexGuard<'static, ()>,
}

impl Server {
    fn start_auth_mt() -> Self {
        let guard = SERVER_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let port = TcpListener::bind("127.0.0.1:0")
            .expect("bind ephemeral")
            .local_addr()
            .expect("port")
            .port();
        let workspace = std::env::temp_dir().join(format!(
            "openfdd-p2c-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).unwrap();
        let cp = workspace.join("openfdd/control_plane");
        std::fs::create_dir_all(&cp).unwrap();
        std::fs::write(
            cp.join("tenants.json"),
            serde_json::to_vec_pretty(&json!({
                "tenants": [
                    {
                        "id": "tenant_a",
                        "name": "Tenant A Corp",
                        "building_ids": ["BLDG_SHARED", "BLDG_A_ONLY"]
                    },
                    {
                        "id": "tenant_b",
                        "name": "Tenant B Corp",
                        "building_ids": ["BLDG_SHARED", "BLDG_B_ONLY"]
                    }
                ]
            }))
            .unwrap(),
        )
        .unwrap();

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
            .env("OPENFDD_JWT_SECRET", SECRET)
            .env("OPENFDD_ADMIN_PASSWORD", "admin-p2c-pass")
            .env("OPENFDD_MULTI_TENANT", "1")
            .spawn()
            .expect("start openfdd-central");

        for _ in 0..80 {
            let (status, body) = http("GET", port, "/api/health", None, None);
            if status == 200 && body.contains("\"openfdd-central\"") {
                return Self {
                    child,
                    port,
                    workspace,
                    _guard: guard,
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

fn mint(sub: &str, role: &str, tenant_ids: &[&str]) -> String {
    #[derive(serde::Serialize)]
    struct Claims {
        sub: String,
        role: String,
        exp: i64,
        iat: i64,
        tenant_ids: Vec<String>,
    }
    let now = chrono::Utc::now().timestamp();
    let claims = Claims {
        sub: sub.into(),
        role: role.into(),
        exp: now + 3600,
        iat: now,
        tenant_ids: tenant_ids.iter().map(|s| (*s).to_string()).collect(),
    };
    encode(
        &Header::default(),
        &claims,
        &EncodingKey::from_secret(SECRET.as_bytes()),
    )
    .expect("mint jwt")
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
    let text = String::from_utf8_lossy(&buf);
    let status = text
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    let body = text
        .split("\r\n\r\n")
        .nth(1)
        .unwrap_or("")
        .trim()
        .to_string();
    (status, body)
}

fn parse(body: &str) -> Value {
    serde_json::from_str(body).unwrap_or(json!({"_raw": body}))
}

/// Kali V1: anonymous GET /api/tenants must not inherit Admin / leak plane.
#[test]
fn anonymous_tenants_denied_when_auth_on() {
    let server = Server::start_auth_mt();
    let (st, body) = http("GET", server.port, "/api/tenants", None, None);
    assert_eq!(st, 401, "anonymous /api/tenants must 401, got {st} {body}");
    let v = parse(&body);
    assert!(
        v.get("tenants").is_none()
            || v.get("tenants")
                .and_then(|t| t.as_array())
                .map(|a| a.is_empty())
                .unwrap_or(true),
        "must not return tenant roster: {body}"
    );
    assert!(
        !body.contains("Tenant A Corp") && !body.contains("BLDG_B_ONLY"),
        "must not leak tenant names/buildings: {body}"
    );
}

/// Kali V1: Tenant A sees only A; B only B; hub admin sees both.
#[test]
fn tenants_scoped_by_membership() {
    let server = Server::start_auth_mt();
    let tok_a = mint("ops-a", "operator", &["tenant_a"]);
    let tok_b = mint("ops-b", "operator", &["tenant_b"]);
    let tok_admin = mint("admin", "admin", &[]);

    let (st, body) = http("GET", server.port, "/api/tenants", None, Some(&tok_a));
    assert_eq!(st, 200, "{body}");
    let v = parse(&body);
    let ids: Vec<&str> = v["tenants"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|t| t["id"].as_str())
        .collect();
    assert_eq!(ids, vec!["tenant_a"], "{body}");
    assert!(
        !body.contains("tenant_b") && !body.contains("BLDG_B_ONLY"),
        "A must not see B: {body}"
    );

    let (st, body) = http("GET", server.port, "/api/tenants", None, Some(&tok_b));
    assert_eq!(st, 200, "{body}");
    let v = parse(&body);
    let ids: Vec<&str> = v["tenants"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|t| t["id"].as_str())
        .collect();
    assert_eq!(ids, vec!["tenant_b"], "{body}");

    let (st, body) = http("GET", server.port, "/api/tenants", None, Some(&tok_admin));
    assert_eq!(st, 200, "{body}");
    assert!(body.contains("tenant_a") && body.contains("tenant_b"), "{body}");
}

/// Kali V2: sensitive public surfaces must not disclose topology when unauthenticated.
#[test]
fn anonymous_topology_endpoints_denied_or_generic() {
    let server = Server::start_auth_mt();
    let sensitive = [
        "/api/capabilities",
        "/api/health/stack",
        "/api/building/snapshot",
        "/api/dashboard/summary",
    ];
    let banned = [
        "\"mcp\"",
        "bacnet_bind",
        "OPENFDD_BACNET",
        "data_management",
        "portfolio",
        "arrow-datafusion",
        "oxigraph",
        "workspace/",
        "historian",
        "fdd_registry",
        "tenant_budgets",
    ];
    for path in sensitive {
        let (st, body) = http("GET", server.port, path, None, None);
        assert!(
            st == 401 || st == 200,
            "{path}: unexpected {st} {body}"
        );
        if st == 200 {
            for needle in banned {
                assert!(
                    !body.contains(needle),
                    "{path}: public body must not contain {needle}: {body}"
                );
            }
            // Allow only minimal readiness keys.
            let v = parse(&body);
            assert_eq!(v.get("ok"), Some(&json!(true)), "{path}: {body}");
            assert!(
                v.get("services").is_none()
                    && v.get("capabilities").is_none()
                    && v.get("contract").is_none(),
                "{path}: must not include inventories: {body}"
            );
        }
    }
}

/// Health readiness stays public and must stay non-sensitive.
#[test]
fn health_stays_public_and_lean() {
    let server = Server::start_auth_mt();
    let (st, body) = http("GET", server.port, "/api/health", None, None);
    assert_eq!(st, 200, "{body}");
    assert!(body.contains("openfdd-central"), "{body}");
    for needle in ["bacnet_bind", "\"mcp\"", "tenants.json", "admin-p2c"] {
        assert!(!body.contains(needle), "health leaked {needle}: {body}");
    }
}

/// Critical MT matrix: select + buildings_visible + data-path IDOR (gate 31 family).
#[test]
fn mt_isolation_matrix_select_and_datapath() {
    let server = Server::start_auth_mt();
    let tok_a = mint("ops-a", "operator", &["tenant_a"]);
    let tok_b = mint("ops-b", "operator", &["tenant_b"]);
    let tok_admin = mint("admin", "admin", &[]);

    // Unauth select → 401
    let (st, body) = http(
        "POST",
        server.port,
        "/api/tenants/select",
        Some(r#"{"tenant_id":"tenant_a"}"#),
        None,
    );
    assert_eq!(st, 401, "unauth select: {st} {body}");

    // A cannot select B
    let (st, body) = http(
        "POST",
        server.port,
        "/api/tenants/select",
        Some(r#"{"tenant_id":"tenant_b"}"#),
        Some(&tok_a),
    );
    assert_eq!(st, 403, "A select B: {st} {body}");
    let v = parse(&body);
    assert_eq!(v.get("ok"), Some(&json!(false)), "{body}");

    // buildings_visible scoped
    let (st, body) = http("GET", server.port, "/api/tenants", None, Some(&tok_a));
    assert_eq!(st, 200, "{body}");
    let v = parse(&body);
    let visible: Vec<&str> = v["buildings_visible"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|b| b.as_str())
        .collect();
    assert!(
        visible.contains(&"BLDG_A_ONLY") && visible.contains(&"BLDG_SHARED"),
        "A visible: {visible:?}"
    );
    assert!(
        !visible.contains(&"BLDG_B_ONLY"),
        "A must not see BLDG_B_ONLY: {visible:?}"
    );

    // Foreign building data-path → 403 + ok:false (never empty-200 leak)
    let foreign_gets = [
        "/api/csv/import/package/mapping?building_id=BLDG_B_ONLY",
        "/api/fdd/series?building_id=BLDG_B_ONLY&equipment_id=AHU_1&rule_id=FC1",
        "/api/fdd/equipment?building_id=BLDG_B_ONLY",
    ];
    for path in foreign_gets {
        let (st, body) = http("GET", server.port, path, None, Some(&tok_a));
        assert!(
            st == 403 || st == 401,
            "A→B {path}: expected 403, got {st} {body}"
        );
        let v = parse(&body);
        assert_eq!(
            v.get("ok"),
            Some(&json!(false)),
            "A→B {path}: deny body must ok:false: {body}"
        );
    }

    let (st, body) = http(
        "POST",
        server.port,
        "/api/analytics/runtime",
        Some(r#"{"building_id":"BLDG_B_ONLY"}"#),
        Some(&tok_a),
    );
    assert!(
        st == 403 || st == 401,
        "A analytics B: expected 403, got {st} {body}"
    );
    assert_eq!(parse(&body).get("ok"), Some(&json!(false)), "{body}");

    // Shared building is in scope for A (may 404/empty if no package — not 403)
    let (st, body) = http(
        "GET",
        server.port,
        "/api/fdd/equipment?building_id=BLDG_SHARED",
        None,
        Some(&tok_a),
    );
    assert_ne!(st, 403, "shared building must be in A scope: {st} {body}");

    // B denied on A's exclusive building
    let (st, body) = http(
        "GET",
        server.port,
        "/api/fdd/equipment?building_id=BLDG_A_ONLY",
        None,
        Some(&tok_b),
    );
    assert_eq!(st, 403, "B→A equip: {st} {body}");

    // Hub admin can read foreign building without 403
    let (st, body) = http(
        "GET",
        server.port,
        "/api/fdd/equipment?building_id=BLDG_B_ONLY",
        None,
        Some(&tok_admin),
    );
    assert_ne!(st, 403, "hub admin cross-tenant: {st} {body}");
    assert_ne!(st, 401, "hub admin must auth: {st} {body}");
}

/// Admin surface + agent-token least-privilege (O2c / P2c matrix).
#[test]
fn admin_and_agent_token_least_privilege() {
    let server = Server::start_auth_mt();
    let tok_a = mint("ops-a", "operator", &["tenant_a"]);
    let tok_admin = mint("admin", "admin", &[]);

    for path in [
        "/api/admin/users",
        "/api/admin/tenants",
        "/api/admin/historian-limits",
    ] {
        let (st, body) = http("GET", server.port, path, None, Some(&tok_a));
        assert_eq!(st, 403, "ops on {path}: {st} {body}");
        assert_eq!(parse(&body).get("ok"), Some(&json!(false)), "{body}");
    }

    let (st, body) = http(
        "POST",
        server.port,
        "/api/auth/agent-token",
        Some(r#"{"ttl_secs":600,"tenant_id":"tenant_a"}"#),
        Some(&tok_a),
    );
    assert_eq!(st, 403, "ops mint agent: {st} {body}");

    let (st, body) = http(
        "POST",
        server.port,
        "/api/auth/agent-token",
        Some(r#"{"ttl_secs":600,"tenant_id":"tenant_a"}"#),
        Some(&tok_admin),
    );
    assert_eq!(st, 200, "admin mint: {st} {body}");
    let agent = parse(&body)["token"]
        .as_str()
        .expect("token")
        .to_string();
    assert_eq!(parse(&body)["role"].as_str(), Some("operator"));

    let (st, body) = http("GET", server.port, "/api/admin/users", None, Some(&agent));
    assert_eq!(st, 403, "agent JWT must not admin: {st} {body}");

    let (st, body) = http(
        "GET",
        server.port,
        "/api/fdd/equipment?building_id=BLDG_B_ONLY",
        None,
        Some(&agent),
    );
    assert_eq!(
        st, 403,
        "tenant-scoped agent must not see B only: {st} {body}"
    );

    let (st, body) = http(
        "GET",
        server.port,
        "/api/fdd/equipment?building_id=BLDG_A_ONLY",
        None,
        Some(&agent),
    );
    assert_ne!(st, 403, "agent scoped to A: {st} {body}");
}
