//! Model projection + SPARQL HTTP contract (#1441).
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "integration tests are not cfg(test); allow-unwrap-in-tests does not cover tests/ binaries"
)]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::thread;
use std::time::Duration;

use serde_json::json;

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
        let workspace = std::env::temp_dir().join(format!(
            "openfdd-model-projection-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        let _ = std::fs::remove_dir_all(&workspace);
        std::fs::create_dir_all(&workspace).expect("mkdir workspace");

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let repo_root = manifest_dir.join("../..");
        let sql_rules = repo_root.join("sql_rules");
        let bin = env!("CARGO_BIN_EXE_openfdd-central");
        let mut child = Command::new(bin)
            .env("OPENFDD_CENTRAL_HOST", "127.0.0.1")
            .env("OPENFDD_CENTRAL_PORT", port.to_string())
            .env("OPENFDD_MQTT_ENABLED", "0")
            .env("OPENFDD_WORKSPACE", &workspace)
            .env("OPENFDD_SQL_RULES_DIR", &sql_rules)
            .spawn()
            .expect("spawn central");
        let server = Self {
            child,
            port,
            workspace,
        };
        server.wait_ready();
        server
    }

    fn wait_ready(&self) {
        for _ in 0..120 {
            if Self::get(self.port, "/api/health").is_ok() {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        panic!("central did not become ready");
    }

    fn get(port: u16, path: &str) -> Result<(u16, String), String> {
        let mut stream =
            TcpStream::connect(format!("127.0.0.1:{port}")).map_err(|e| e.to_string())?;
        stream
            .write_all(
                format!("GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                    .as_bytes(),
            )
            .map_err(|e| e.to_string())?;
        let mut buf = String::new();
        stream.read_to_string(&mut buf).map_err(|e| e.to_string())?;
        let status = buf
            .lines()
            .next()
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);
        Ok((status, buf))
    }

    fn post_json(port: u16, path: &str, body: &str) -> Result<(u16, String), String> {
        let mut stream =
            TcpStream::connect(format!("127.0.0.1:{port}")).map_err(|e| e.to_string())?;
        let req = format!(
            "POST {path} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        stream.write_all(req.as_bytes()).map_err(|e| e.to_string())?;
        let mut buf = String::new();
        stream.read_to_string(&mut buf).map_err(|e| e.to_string())?;
        let status = buf
            .lines()
            .next()
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);
        Ok((status, buf))
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.workspace);
    }
}

fn persist_meta(workspace: &PathBuf, building_id: &str) {
    let root = workspace
        .join("data")
        .join("csv_buildings")
        .join(building_id);
    std::fs::create_dir_all(&root).expect("mkdir building");
    let meta = json!({
        "schema": "openfdd_semantic_meta_v1",
        "building_id": building_id,
        "points": [{
            "equipment_id": "EQ_A",
            "column": "SAT",
            "haystack_tags": ["sensor", "point", "air", "temp"],
            "unit": "°F",
            "kind": "Number",
        }],
        "equipment": [{
            "equipment_id": "EQ_A",
            "haystack_tags": ["ahu", "equip"],
        }]
    });
    std::fs::write(
        root.join("semantic_meta.json"),
        serde_json::to_vec_pretty(&meta).expect("meta json"),
    )
    .expect("write meta");
}

#[test]
fn model_projection_and_sparql_http_status_contract() {
    let server = Server::start();
    let bid = "T1441_HTTP_CONTRACT";
    persist_meta(&server.workspace, bid);

    let (st, _) = Server::get(
        server.port,
        &format!("/api/model/projection?building_id=NO_META_{bid}"),
    )
    .expect("get projection");
    assert_eq!(st, 404);

    let (st, _) = Server::get(
        server.port,
        &format!("/api/model/projection?building_id={bid}&equipment_id=EQ_MISSING"),
    )
    .expect("get scoped projection");
    assert_eq!(st, 400);

    let (st, body) = Server::get(
        server.port,
        &format!("/api/model/projection?building_id={bid}"),
    )
    .expect("get projection ok");
    assert_eq!(st, 200);
    assert!(body.contains("ofdd_static_ui_model_projection_v1"));

    let (st, _) = Server::post_json(
        server.port,
        "/api/model/sparql",
        &json!({
            "building_id": format!("NO_META_{bid}"),
            "query_id": "fdd_role_candidates",
        })
        .to_string(),
    )
    .expect("sparql missing");
    assert_eq!(st, 404);

    let (st, _) = Server::post_json(
        server.port,
        "/api/model/sparql",
        &json!({
            "building_id": bid,
            "equipment_id": "EQ_MISSING",
            "query_id": "fdd_role_candidates",
        })
        .to_string(),
    )
    .expect("sparql unknown equip");
    assert_eq!(st, 400);
}
