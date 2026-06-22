mod drivers;
mod fdd;
mod historian;
mod model;
mod control;
mod ops;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use chrono::Utc;
use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::Sha256;
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::thread;

type HmacSha256 = Hmac<Sha256>;

const REPORTS: &str = r#"[
  {"report_id":"rcx-demo-001","kind":"rcx","status":"ready","path":"workspace/reports/rcx/rcx-demo-001.md"}
]"#;


#[derive(Clone, Debug)]
struct Principal {
    sub: String,
    role: String,
}

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let root = env::var("FRONTEND_DIR").unwrap_or_else(|_| "/app/frontend".to_string());
    let service_mode = env::var("SERVICE_MODE").unwrap_or_else(|_| "bridge".to_string());
    drivers::bacnet::start_hourly_override_scanner(service_mode.clone());
    let listener = TcpListener::bind(format!("0.0.0.0:{port}"))?;
    println!("Open-FDD Rust Edge API listening on http://0.0.0.0:{port}");
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let root = root.clone();
                thread::spawn(move || {
                    let _ = handle(stream, Path::new(&root));
                });
            }
            Err(err) => eprintln!("connection error: {err}"),
        }
    }
    Ok(())
}

fn handle(mut stream: TcpStream, frontend: &Path) -> std::io::Result<()> {
    let mut buf = [0_u8; 32768];
    let n = stream.read(&mut buf)?;
    if n == 0 {
        return Ok(());
    }
    let req = String::from_utf8_lossy(&buf[..n]);
    let (method, path, headers, body) = parse_request(&req);
    let clean_path = path.split('?').next().unwrap_or(path.as_str()).to_string();

    if method == "OPTIONS" {
        return options(&mut stream);
    }
    if method == "GET" && clean_path == "/api/health" {
        return json_response(&mut stream, json!({
            "ok": true,
            "auth_required": true,
            "mode": "rust-jwt-agent-api",
            "services": ["bridge-api", "dashboard", "historian", "commission", "bacnet", "modbus", "haystack-gateway", "arrow", "datafusion", "control", "json-api", "agent-api"]
        }));
    }
    if method == "POST" && clean_path == "/api/auth/login" {
        return login(&mut stream, &body);
    }
    if method == "GET" && !clean_path.starts_with("/api/") {
        return static_file(&mut stream, frontend, &clean_path);
    }

    let principal = match authorize(&headers) {
        Ok(p) => p,
        Err(e) => return status_json(&mut stream, "401 Unauthorized", json!({"ok": false, "error": e})),
    };

    match (method.as_str(), clean_path.as_str()) {
        ("GET", "/api/auth/whoami") => json_response(&mut stream, json!({"ok": true, "principal": {"sub": principal.sub, "role": principal.role}})),
        ("GET", "/api/ui/tabs") => raw_json(&mut stream, ops::bridge::ui_tabs_json()),
        ("GET", "/api/bridge/status") => raw_json(&mut stream, ops::bridge::status_json()),
        ("GET", "/api/agent/manifest") => json_response(&mut stream, agent_manifest()),
        ("GET", "/api/agent/tools") => json_response(&mut stream, agent_tools()),
        ("POST", "/api/agent/bootstrap") => require_role(&mut stream, &principal, &["integrator", "agent"], agent_bootstrap()),
        ("POST", "/api/agent/update") => require_role(&mut stream, &principal, &["integrator", "agent"], agent_update()),
        ("GET", "/api/ops/stack") => json_response(&mut stream, stack_status()),

        ("GET", "/api/health/stack") => json_response(&mut stream, stack_status()),
        ("GET", "/api/historian/query") => raw_json(&mut stream, historian::arrow_table::query_json()),
        ("POST", "/api/historian/query") => raw_json(&mut stream, historian::arrow_table::query_json()),
        ("POST", "/api/ops/docker/update") => require_role(&mut stream, &principal, &["integrator", "agent"], agent_update()),
        ("GET", "/api/building/checkin") => json_response(&mut stream, building_checkin()),
        ("GET", "/api/algorithms") => json_response(&mut stream, algorithms()),
        ("GET", "/api/control/cdl/status") => raw_json(&mut stream, control::cdl::status_json()),
        ("GET", "/api/control/cdl/bindings") => raw_json(&mut stream, model::assignments::algorithm_bindings_json()),
        ("POST", "/api/control/cdl/bindings/save") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(model::assignments::save_assignment_json()).unwrap()),
        ("POST", "/api/algorithms/run") => require_role(&mut stream, &principal, &["integrator", "agent"], json!({"ok": true, "run_id": "alg-demo-001", "result": serde_json::from_str::<Value>(control::cdl::simulate_json()).unwrap()})),
        ("GET", "/api/model/haystack") => raw_json(&mut stream, drivers::haystack::model_json()),
        ("GET", "/api/model/assignments") => raw_json(&mut stream, model::assignments::assignments_json()),
        ("POST", "/api/model/assignments/save") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(model::assignments::save_assignment_json()).unwrap()),
        ("POST", "/api/model/assignments/resolve") => raw_json(&mut stream, model::assignments::resolve_json()),
        ("GET", "/api/model/algorithm-bindings") => raw_json(&mut stream, model::assignments::algorithm_bindings_json()),
        ("GET", "/api/haystack/about") => raw_json(&mut stream, drivers::haystack::about_json()),
        ("GET", "/api/haystack/status") => raw_json(&mut stream, drivers::haystack::status_json()),
        ("POST", "/api/haystack/read") => raw_json(&mut stream, drivers::haystack::model_json()),
        ("POST", "/api/haystack/nav") => raw_json(&mut stream, drivers::haystack::model_json()),
        ("POST", "/api/haystack/ops") => raw_json(&mut stream, drivers::haystack::ops_json()),
        ("POST", "/api/haystack/import") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(drivers::haystack::import_json()).unwrap()),
        ("POST", "/api/model/haystack/import") => require_role(&mut stream, &principal, &["integrator", "agent"], json!({"ok": true, "preserve_ids": true, "imported": 4})),
        ("POST", "/api/model/query") => json_response(&mut stream, json!({"ok": true, "rows": serde_json::from_str::<Value>(drivers::haystack::model_json()).unwrap()["rows"].clone()})),
        ("GET", "/api/fdd/datafusion/demo") => raw_json(&mut stream, fdd::datafusion_sql::result_json()),
        ("POST", "/api/fdd/run") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(fdd::datafusion_sql::result_json()).unwrap()),
        ("GET", "/api/rules") => raw_json(&mut stream, fdd::datafusion_sql::rules_json()),
        ("POST", "/api/rules/save") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(fdd::datafusion_sql::save_json()).unwrap()),
        ("POST", "/api/rules/batch") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(fdd::datafusion_sql::batch_json()).unwrap()),
        ("GET", "/api/arrow/demo") => raw_json(&mut stream, historian::arrow_table::demo_rows_json()),
        ("POST", "/api/bacnet/whois") => { let body = drivers::bacnet::whois_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/bacnet/points") => { let body = drivers::bacnet::points_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/bacnet/commission/status") => { let body = drivers::bacnet::commission_status_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/bacnet/poll/status") => { let body = drivers::bacnet::poll_status_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/bacnet/driver/tree") => { let body = drivers::bacnet::driver_tree_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/drivers/tree") => { let body = drivers::tree::driver_tree_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/health/workspace") => json_response(&mut stream, drivers::framework::workspace_health()),
        ("GET", "/api/bacnet/driver/health") => { let body = drivers::bacnet::driver_health_json(); raw_json(&mut stream, &body) },
        ("POST", "/api/bacnet/driver/sync-discovery") => require_role(&mut stream, &principal, &["integrator", "agent"], drivers::bacnet::sync_discovery_value()),
        ("PATCH", "/api/bacnet/driver/point") => require_role(&mut stream, &principal, &["integrator", "agent"], json!({"ok": true, "updated": "point polling settings"})),
        ("POST", "/api/bacnet/point-discovery") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            require_role(&mut stream, &principal, &["integrator", "agent"], drivers::bacnet::point_discovery_value(&payload))
        },
        ("POST", "/api/bacnet/read") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            let response_body = drivers::bacnet::read_present_value_json(&payload);
            raw_json(&mut stream, &response_body)
        },
        ("POST", "/api/bacnet/read-priority-array") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            require_role(&mut stream, &principal, &["integrator", "agent"], drivers::bacnet::read_priority_array_value(&payload))
        },
        ("GET", "/api/bacnet/overrides/status") => { let body = drivers::bacnet::overrides_json(); raw_json(&mut stream, &body) },
        ("POST", "/api/bacnet/overrides/scan-once") => require_role(&mut stream, &principal, &["integrator", "agent"], drivers::bacnet::scan_once_value()),
        ("GET", "/api/bacnet/overrides/export") => { let body = drivers::bacnet::overrides_csv(); response(&mut stream, "200 OK", "text/csv; charset=utf-8", body.as_bytes()) },
        ("GET", "/api/bacnet/overrides/export/p8") => { let body = drivers::bacnet::priority8_csv(); response(&mut stream, "200 OK", "text/csv; charset=utf-8", body.as_bytes()) },
        ("GET", "/api/bacnet/overrides/export/non-p8") => { let body = drivers::bacnet::non_priority8_csv(); response(&mut stream, "200 OK", "text/csv; charset=utf-8", body.as_bytes()) },
        
        ("POST", "/api/bacnet/write-dry-run") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(drivers::bacnet::write_dry_run_json()).unwrap()),
("POST", "/api/bacnet/write") => {
            let value: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            let approved = value.get("approved").and_then(|v| v.as_bool()).unwrap_or(false);
            if approved && (principal.role == "integrator") {
                json_response(&mut stream, json!({"ok": true, "dry_run": true, "safety": "BACnet write requires explicit human approval; prototype never writes to field bus"}))
            } else {
                status_json(&mut stream, "403 Forbidden", json!({"ok": false, "error": "BACnet writes require integrator role and approved=true"}))
            }
        },
        ("GET", "/api/modbus/points") => { let body = drivers::modbus::points_json(); raw_json(&mut stream, &body) },
        ("GET", "/api/modbus/commission/status") => { let body = drivers::modbus::commission_status_json(); raw_json(&mut stream, &body) },
        ("POST", "/api/modbus/scan") => require_role(&mut stream, &principal, &["integrator", "agent"], drivers::modbus::scan_value()),
        ("POST", "/api/modbus/read") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            let response_body = drivers::modbus::read_value(&payload);
            raw_json(&mut stream, &response_body)
        },
        ("GET", "/api/json-api/sources") => raw_json(&mut stream, drivers::json_api::sources_json()),
        ("POST", "/api/json-api/poll-once") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(drivers::json_api::poll_once_json()).unwrap()),
        ("POST", "/api/json-api/register") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(drivers::json_api::register_json()).unwrap()),
        ("GET", "/api/control/status") => raw_json(&mut stream, control::cdl::simulate_json()),
        ("POST", "/api/control/simulate") => require_role(&mut stream, &principal, &["integrator", "agent"], serde_json::from_str::<Value>(control::cdl::simulate_json()).unwrap()),
        ("POST", "/api/reports/rcx/plan") => json_response(&mut stream, json!({"ok": true, "sections": ["executive_summary", "faults", "overrides", "energy_opportunities", "trend_plots"]})),
        ("GET", "/api/reports/rcx/list") => raw_json(&mut stream, REPORTS),
        ("POST", "/api/reports/rcx/generate") => require_role(&mut stream, &principal, &["integrator", "agent"], json!({"ok": true, "report_id": "rcx-demo-001", "path": "workspace/reports/rcx/rcx-demo-001.md", "sections": ["faults", "overrides", "plotly_trends", "recommendations"]})),
        _ => status_json(&mut stream, "404 Not Found", json!({"ok": false, "error": "unknown endpoint", "path": clean_path})),
    }
}

fn parse_request(req: &str) -> (String, String, Vec<(String, String)>, String) {
    let mut lines = req.split("\r\n");
    let first = lines.next().unwrap_or("");
    let mut parts = first.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path = parts.next().unwrap_or("/").to_string();
    let mut headers = Vec::new();
    let mut body_started = false;
    let mut body_lines = Vec::new();
    for line in lines {
        if body_started {
            body_lines.push(line);
            continue;
        }
        if line.is_empty() {
            body_started = true;
            continue;
        }
        if let Some((k, v)) = line.split_once(':') {
            headers.push((k.trim().to_ascii_lowercase(), v.trim().to_string()));
        }
    }
    (method, path, headers, body_lines.join("\r\n"))
}

fn login(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let value: Value = serde_json::from_str(body).unwrap_or(json!({}));
    let role = value.get("role").and_then(|v| v.as_str()).unwrap_or("agent");
    if !["operator", "integrator", "agent"].contains(&role) {
        return status_json(stream, "400 Bad Request", json!({"ok": false, "error": "role must be operator, integrator, or agent"}));
    }
    let sub = value.get("sub").and_then(|v| v.as_str()).unwrap_or("edge-agent");
    let token = create_jwt(sub, role);
    json_response(stream, json!({"ok": true, "token_type": "Bearer", "access_token": token, "expires_in": 8 * 3600, "role": role}))
}

fn secret() -> String {
    env::var("OPENFDD_JWT_SECRET").unwrap_or_else(|_| "dev-change-me-openfdd-rust-edge".to_string())
}

fn create_jwt(sub: &str, role: &str) -> String {
    let header = json!({"alg":"HS256","typ":"JWT"});
    let now = Utc::now().timestamp();
    let claims = json!({"sub": sub, "role": role, "iat": now, "exp": now + 8 * 3600, "aud": "open-fdd-rust-edge"});
    let h = URL_SAFE_NO_PAD.encode(header.to_string().as_bytes());
    let c = URL_SAFE_NO_PAD.encode(claims.to_string().as_bytes());
    let msg = format!("{h}.{c}");
    let mut mac = HmacSha256::new_from_slice(secret().as_bytes()).unwrap();
    mac.update(msg.as_bytes());
    let sig = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    format!("{msg}.{sig}")
}

fn authorize(headers: &[(String, String)]) -> Result<Principal, String> {
    let auth = headers.iter().find(|(k, _)| k == "authorization").map(|(_, v)| v.clone()).ok_or("missing Authorization: Bearer token")?;
    let token = auth.strip_prefix("Bearer ").ok_or("expected Bearer token")?;
    verify_jwt(token)
}

fn verify_jwt(token: &str) -> Result<Principal, String> {
    let parts: Vec<&str> = token.split('.').collect();
    if parts.len() != 3 {
        return Err("malformed JWT".into());
    }
    let msg = format!("{}.{}", parts[0], parts[1]);
    let mut mac = HmacSha256::new_from_slice(secret().as_bytes()).unwrap();
    mac.update(msg.as_bytes());
    let expected = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    if expected != parts[2] {
        return Err("invalid JWT signature".into());
    }
    let bytes = URL_SAFE_NO_PAD.decode(parts[1]).map_err(|_| "invalid JWT payload")?;
    let claims: Value = serde_json::from_slice(&bytes).map_err(|_| "invalid JWT claims")?;
    let exp = claims.get("exp").and_then(|v| v.as_i64()).unwrap_or(0);
    if exp < Utc::now().timestamp() {
        return Err("expired JWT".into());
    }
    Ok(Principal {
        sub: claims.get("sub").and_then(|v| v.as_str()).unwrap_or("unknown").to_string(),
        role: claims.get("role").and_then(|v| v.as_str()).unwrap_or("operator").to_string(),
    })
}

fn require_role(stream: &mut TcpStream, principal: &Principal, roles: &[&str], body: Value) -> std::io::Result<()> {
    if roles.contains(&principal.role.as_str()) {
        json_response(stream, body)
    } else {
        status_json(stream, "403 Forbidden", json!({"ok": false, "error": "insufficient role", "role": principal.role}))
    }
}

fn agent_manifest() -> Value {
    json!({
        "name": "open-fdd-rust-edge",
        "description": "AI-drivable Open-FDD-style edge API for commissioning, modeling, algorithms, FDD, reports, and safe updates.",
        "auth": {"type": "JWT", "scheme": "Bearer", "login": "POST /api/auth/login", "ttl_hours": 8},
        "safety": [
            "No BACnet writes unless integrator JWT and approved=true",
            "No docker volume prune",
            "Never delete workspace/",
            "Do not print secrets"
        ],
        "start_session": ["POST /api/auth/login", "GET /api/building/checkin", "GET /api/agent/tools"]
    })
}

fn agent_tools() -> Value {
    json!({
        "tools": [
            {"name":"auth.login","method":"POST","path":"/api/auth/login","public":true},
            {"name":"health","method":"GET","path":"/api/health","public":true},
            {"name":"building.checkin","method":"GET","path":"/api/building/checkin","requires":"JWT"},
            {"name":"bacnet.whois","method":"POST","path":"/api/bacnet/whois","requires":"JWT"},
            {"name":"bacnet.point_discovery","method":"POST","path":"/api/bacnet/point-discovery","requires":"integrator|agent"},
            {"name":"bacnet.override_scan","method":"POST","path":"/api/bacnet/overrides/scan-once","requires":"integrator|agent"},
            {"name":"bacnet.override_export_all","method":"GET","path":"/api/bacnet/overrides/export","requires":"JWT"},
            {"name":"bacnet.override_export_p8","method":"GET","path":"/api/bacnet/overrides/export/p8","requires":"JWT"},
            {"name":"bacnet.override_export_non_p8","method":"GET","path":"/api/bacnet/overrides/export/non-p8","requires":"JWT"},
            {"name":"bacnet.driver_tree","method":"GET","path":"/api/bacnet/driver/tree","requires":"JWT"},
            {"name":"modbus.points","method":"GET","path":"/api/modbus/points","requires":"JWT"},
            {"name":"modbus.scan","method":"POST","path":"/api/modbus/scan","requires":"integrator|agent"},
            {"name":"json_api.sources","method":"GET","path":"/api/json-api/sources","requires":"JWT"},
            {"name":"json_api.register","method":"POST","path":"/api/json-api/register","requires":"integrator|agent"},
            {"name":"json_api.poll_once","method":"POST","path":"/api/json-api/poll-once","requires":"integrator|agent"},
            {"name":"haystack.status","method":"GET","path":"/api/haystack/status","requires":"JWT"},
            {"name":"haystack.read","method":"POST","path":"/api/haystack/read","requires":"JWT"},
            {"name":"model.haystack","method":"GET","path":"/api/model/haystack","requires":"JWT"},
            {"name":"model.import","method":"POST","path":"/api/model/haystack/import","requires":"integrator|agent"},
            {"name":"model.assignments","method":"GET","path":"/api/model/assignments","requires":"JWT"},
            {"name":"model.assignments_save","method":"POST","path":"/api/model/assignments/save","requires":"integrator|agent"},
            {"name":"model.resolve","method":"POST","path":"/api/model/assignments/resolve","requires":"JWT"},
            {"name":"control.cdl_bindings","method":"GET","path":"/api/control/cdl/bindings","requires":"JWT"},
            {"name":"control.cdl_bindings_save","method":"POST","path":"/api/control/cdl/bindings/save","requires":"integrator|agent"},
            {"name":"algorithms.run","method":"POST","path":"/api/algorithms/run","requires":"integrator|agent"},
            {"name":"fdd.run","method":"POST","path":"/api/fdd/run","requires":"integrator|agent"},
            {"name":"rules.batch","method":"POST","path":"/api/rules/batch","requires":"integrator|agent"},
            {"name":"historian.query","method":"POST","path":"/api/historian/query","requires":"JWT"},
            {"name":"reports.rcx_plan","method":"POST","path":"/api/reports/rcx/plan","requires":"JWT"},
            {"name":"reports.rcx_generate","method":"POST","path":"/api/reports/rcx/generate","requires":"integrator|agent"},
            {"name":"ops.update","method":"POST","path":"/api/ops/docker/update","requires":"integrator|agent"}
        ]
    })
}

fn agent_bootstrap() -> Value {
    json!({
        "ok": true,
        "dry_run": true,
        "plan": [
            "create workspace/ without deleting existing data",
            "write docker-compose.yml",
            "create auth secret if missing",
            "start containers",
            "validate GET /api/health",
            "validate JWT login",
            "validate agent manifest"
        ]
    })
}

fn agent_update() -> Value {
    json!({
        "ok": true,
        "dry_run": true,
        "steps": [
            "backup workspace/",
            "pull container images",
            "recreate services",
            "validate health",
            "keep backup if validation fails"
        ],
        "forbidden": ["docker compose down -v", "docker volume prune", "delete workspace/"]
    })
}

fn stack_status() -> Value {
    json!({
        "ok": true,
        "services": [
            {"id":"openfdd-bridge","label":"API + dashboard + historian","status":"online","auth_required":true},
            {"id":"openfdd-commission","label":"BACnet + Modbus + JSON polling","status":"online","auth_required":true},
            {"id":"openfdd-haystack-gateway","label":"Haystack read/nav/ops integration","status":"online","auth_required":true},
            {"id":"bacnet","status":"ready","write_guard":"human approval required"},
            {"id":"modbus","status":"ready"},
            {"id":"haystack","status":"ready"},
            {"id":"arrow-datafusion","status":"ready"},
            {"id":"control-engine","status":"ready"}
        ]
    })
}

fn building_checkin() -> Value {
    json!({
        "ok": true,
        "site": "Demo Site",
        "equipment": 1,
        "points": 5,
        "active_faults": 2,
        "overrides": 2,
        "recommended_next_steps": [
            "review SAT_DEVIATION_HIGH fault",
            "clear or document operator P8 SAT setpoint override",
            "confirm duct static trim/respond sequence"
        ]
    })
}

fn algorithms() -> Value {
    json!({
        "algorithms": [
            {"id":"g36_trim_respond","name":"G36 AHU/VAV Trim & Respond","engine":"open-control-engine CDL","status":"ready"},
            {"id":"sat_deviation","name":"SAT Deviation Detector","engine":"DataFusion SQL","status":"active"},
            {"id":"duct_static_deviation","name":"Duct Static Deviation","engine":"DataFusion SQL","status":"active"},
            {"id":"override_watch","name":"BACnet Supervisory Override Watch","engine":"BACnet ReadProperty priority-array","status":"hourly"}
        ]
    })
}

fn raw_json(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    response(stream, "200 OK", "application/json", body.as_bytes())
}

fn json_response(stream: &mut TcpStream, value: Value) -> std::io::Result<()> {
    raw_json(stream, &value.to_string())
}

fn status_json(stream: &mut TcpStream, status: &str, value: Value) -> std::io::Result<()> {
    response(stream, status, "application/json", value.to_string().as_bytes())
}

fn options(stream: &mut TcpStream) -> std::io::Result<()> {
    let headers = "HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET,POST,OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type, Authorization\r\nContent-Length: 0\r\n\r\n";
    stream.write_all(headers.as_bytes())
}

fn static_file(stream: &mut TcpStream, frontend: &Path, path: &str) -> std::io::Result<()> {
    let rel = if path == "/" { "index.html" } else { path.trim_start_matches('/') };
    if rel.contains("..") {
        return response(stream, "400 Bad Request", "text/plain", b"bad path");
    }
    let file = PathBuf::from(frontend).join(rel);
    match fs::read(&file) {
        Ok(bytes) => {
            let ctype = match file.extension().and_then(|s| s.to_str()).unwrap_or("") {
                "html" => "text/html; charset=utf-8",
                "css" => "text/css; charset=utf-8",
                "js" => "application/javascript; charset=utf-8",
                _ => "application/octet-stream",
            };
            response(stream, "200 OK", ctype, &bytes)
        }
        Err(_) => response(stream, "404 Not Found", "text/plain", b"not found"),
    }
}

fn response(stream: &mut TcpStream, status: &str, content_type: &str, body: &[u8]) -> std::io::Result<()> {
    let headers = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nCache-Control: no-store, no-cache, must-revalidate, max-age=0\r\nPragma: no-cache\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Content-Type, Authorization\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(headers.as_bytes())?;
    stream.write_all(body)
}
