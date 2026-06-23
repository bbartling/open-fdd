mod auth;
mod bench;
mod control;
mod data_management;
mod drivers;
mod export;
mod fdd;
mod historian;
mod import;
mod model;
mod ops;
mod validation;

use auth::audit;
use auth::auth_config;
use auth::config::Principal;
use auth::login::{authenticate, login_response};
use auth::rbac::{can_write_field_bus, role_allowed};

use serde_json::{json, Value};
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::thread;

const REPORTS: &str = r#"[
  {"report_id":"rcx-demo-001","kind":"rcx","status":"ready","path":"workspace/reports/rcx/rcx-demo-001.md"}
]"#;

fn main() -> std::io::Result<()> {
    let cfg = auth_config();
    if let Err(err) = cfg.validate_for_production() {
        eprintln!("auth configuration warning: {err}");
    }
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
    let req = read_http_request(&mut stream)?;
    let (method, path, headers, body) = parse_request(&req);
    let clean_path = path.split('?').next().unwrap_or(path.as_str()).to_string();

    if method == "OPTIONS" {
        return options(&mut stream);
    }
    if method == "GET" && (clean_path == "/api/health" || clean_path == "/health") {
        return json_response(
            &mut stream,
            json!({
                "ok": true,
                "auth_required": auth_config().required,
                "mode": "rust-jwt-edge-auth",
                "services": ["bridge-api", "dashboard", "historian", "commission", "bacnet", "modbus", "haystack-gateway", "arrow", "datafusion", "control", "json-api", "agent-api"]
            }),
        );
    }
    if method == "POST" && clean_path == "/api/auth/login" {
        return login_handler(&mut stream, &body);
    }
    if method == "POST" && clean_path == "/api/auth/logout" {
        audit::log_event(
            "logout",
            json!({"note":"stateless JWT cleared client-side"}),
        );
        return json_response(&mut stream, json!({"ok": true}));
    }
    if method == "GET" && !clean_path.starts_with("/api/") {
        return static_file(&mut stream, frontend, &clean_path);
    }

    let principal = match authorize(&headers) {
        Ok(p) => p,
        Err(e) => {
            audit::log_event("auth_failure", json!({"reason": e}));
            return status_json(
                &mut stream,
                "401 Unauthorized",
                json!({"ok": false, "error": e}),
            );
        }
    };

    match (method.as_str(), clean_path.as_str()) {
        ("GET", "/api/auth/whoami") => json_response(
            &mut stream,
            json!({"ok": true, "principal": {"sub": principal.sub, "role": principal.role}}),
        ),
        ("GET", "/api/ui/tabs") => raw_json(&mut stream, ops::bridge::ui_tabs_json()),
        ("GET", "/api/bridge/status") => raw_json(&mut stream, ops::bridge::status_json()),
        ("GET", "/api/agent/manifest") => json_response(&mut stream, agent_manifest()),
        ("GET", "/api/agent/tools") => json_response(&mut stream, agent_tools()),
        ("POST", "/api/agent/bootstrap") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            agent_bootstrap(),
        ),
        ("POST", "/api/agent/update") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            agent_update(),
        ),
        ("GET", "/api/ops/stack") => json_response(&mut stream, stack_status()),

        ("GET", "/api/health/stack") => json_response(&mut stream, stack_status()),
        ("GET", "/api/historian/query") => {
            raw_json(&mut stream, historian::arrow_table::query_json())
        }
        ("POST", "/api/historian/query") => {
            raw_json(&mut stream, historian::arrow_table::query_json())
        }
        ("GET", "/api/export/meta") => json_response(&mut stream, export::meta_json()),
        ("GET", "/api/export/historian.csv") => {
            let q = export::parse_query(query_string(&clean_path));
            let body = export::historian_csv(&q);
            let name = export::export_filename("historian");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/faults.csv") => {
            let qs = query_string(&clean_path);
            let q = export::parse_query(qs);
            let summary = qs
                .split('&')
                .any(|p| p == "summary=1" || p.starts_with("summary=1&"));
            let body = export::faults_csv(&q, summary);
            let name = export::export_filename(if summary {
                "fault_summary"
            } else {
                "fault_results"
            });
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/fault-summary.csv") => {
            let q = export::parse_query(query_string(&clean_path));
            let body = export::faults_csv(&q, true);
            let name = export::export_filename("fault_summary");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/model-points.csv") => {
            let body = export::model_points_csv();
            let name = export::export_filename("model_points");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/rules.csv") => {
            let body = export::rules_csv();
            let name = export::export_filename("rules");
            require_role_csv(
                &mut stream,
                &principal,
                &["integrator", "agent"],
                body,
                &name,
            )
        }
        ("GET", "/api/export/validation-runs.csv") => {
            let q = export::parse_query(query_string(&clean_path));
            let body = export::validation_runs_csv(&q);
            let name = export::export_filename("validation_runs");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/import-jobs.csv") => {
            let body = export::import_jobs_csv();
            let name = export::export_filename("import_jobs");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/data-management/summary") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            data_management::storage_summary(),
        ),
        ("GET", "/api/data-management/storage") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            data_management::storage_summary(),
        ),
        ("POST", "/api/data-management/purge/preview") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            data_management::preview_purge(&parse_json_body(&body)),
        ),
        ("POST", "/api/data-management/purge/execute") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            data_management::execute_purge(&parse_json_body(&body), &principal.role),
        ),
        ("GET", "/api/data-management/policies") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            data_management::get_policies(),
        ),
        ("PUT", "/api/data-management/policies") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            data_management::put_policies(&parse_json_body(&body), &principal.role),
        ),
        ("GET", "/api/data-management/agent-tools") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            data_management::agent_tools(),
        ),
        ("POST", "/api/import/jobs") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            import::create_job(&parse_json_body(&body)),
        ),
        ("POST", "/api/ops/docker/update") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            agent_update(),
        ),
        ("GET", "/api/building/checkin") => json_response(&mut stream, building_checkin()),
        ("GET", "/api/algorithms") => json_response(&mut stream, algorithms()),
        ("GET", "/api/control/cdl/status") => raw_json(&mut stream, control::cdl::status_json()),
        ("GET", "/api/control/cdl/bindings") => {
            raw_json(&mut stream, model::assignments::algorithm_bindings_json())
        }
        ("POST", "/api/control/cdl/bindings/save") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(model::assignments::save_assignment_json()).unwrap(),
        ),
        ("POST", "/api/algorithms/run") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            json!({"ok": true, "run_id": "alg-demo-001", "result": serde_json::from_str::<Value>(control::cdl::simulate_json()).unwrap()}),
        ),
        ("GET", "/api/model/haystack") => raw_json(&mut stream, drivers::haystack::model_json()),
        ("GET", "/api/model/assignments") => {
            raw_json(&mut stream, model::assignments::assignments_json())
        }
        ("POST", "/api/model/assignments/save") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(model::assignments::save_assignment_json()).unwrap(),
        ),
        ("POST", "/api/model/assignments/resolve") => {
            raw_json(&mut stream, model::assignments::resolve_json())
        }
        ("GET", "/api/model/algorithm-bindings") => {
            raw_json(&mut stream, model::assignments::algorithm_bindings_json())
        }
        ("GET", "/api/haystack/about") => raw_json(&mut stream, drivers::haystack::about_json()),
        ("GET", "/api/haystack/status") => raw_json(&mut stream, drivers::haystack::status_json()),
        ("POST", "/api/haystack/read") => raw_json(&mut stream, drivers::haystack::model_json()),
        ("POST", "/api/haystack/nav") => raw_json(&mut stream, drivers::haystack::model_json()),
        ("POST", "/api/haystack/ops") => raw_json(&mut stream, drivers::haystack::ops_json()),
        ("POST", "/api/haystack/import") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(drivers::haystack::import_json()).unwrap(),
        ),
        ("POST", "/api/model/haystack/import") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            json!({"ok": true, "preserve_ids": true, "imported": 4}),
        ),
        ("POST", "/api/model/query") => json_response(
            &mut stream,
            json!({"ok": true, "rows": serde_json::from_str::<Value>(drivers::haystack::model_json()).unwrap()["rows"].clone()}),
        ),
        ("GET", "/api/fdd/datafusion/demo") => {
            raw_json(&mut stream, fdd::datafusion_sql::result_json())
        }
        ("POST", "/api/fdd/run") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(fdd::datafusion_sql::result_json()).unwrap(),
        ),
        ("GET", "/api/rules") => raw_json(&mut stream, fdd::datafusion_sql::rules_json()),
        ("POST", "/api/rules/save") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(fdd::datafusion_sql::save_json()).unwrap(),
        ),
        ("POST", "/api/rules/batch") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(fdd::datafusion_sql::batch_json()).unwrap(),
        ),

        ("GET", "/api/fdd-schema/tables") => {
            raw_json(&mut stream, &fdd::wires::api::schema_tables_json())
        }
        ("GET", "/api/fdd-schema/fdd-inputs") => {
            raw_json(&mut stream, &fdd::wires::api::schema_fdd_inputs_json())
        }
        ("GET", "/api/fdd-schema/equipment-types") => {
            raw_json(&mut stream, &fdd::wires::api::schema_equipment_types_json())
        }
        ("GET", "/api/fdd-rules") => raw_json(&mut stream, &fdd::wires::api::list_rules_json()),
        ("POST", "/api/fdd-rules") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            fdd::wires::api::save_rule(&parse_json_body(&body), &principal.sub),
        ),
        ("POST", "/api/fdd-rules/builder-sql") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            fdd::wires::api::builder_sql(&parse_json_body(&body)),
        ),
        ("GET", "/api/fdd-wires/graphs") => raw_json(
            &mut stream,
            &fdd::wires::api::list_graphs(query_param(&path, "site_id").as_deref()),
        ),
        ("POST", "/api/fdd-wires/graphs") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            fdd::wires::api::create_graph(&parse_json_body(&body), &principal.sub),
        ),
        ("POST", "/api/fdd-wires/propose-assignments") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            fdd::wires::api::propose_assignments(&parse_json_body(&body), &principal.role),
        ),
        ("GET", "/api/arrow/demo") => {
            raw_json(&mut stream, historian::arrow_table::demo_rows_json())
        }
        ("POST", "/api/bacnet/whois") => {
            let body = drivers::bacnet::whois_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/bacnet/points") => {
            let body = drivers::bacnet::points_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/bacnet/commission/status") => {
            let body = drivers::bacnet::commission_status_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/bacnet/poll/status") => {
            let body = drivers::bacnet::poll_status_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/drivers/tree") => raw_json(&mut stream, &drivers::tree::unified_tree_json()),
        ("GET", "/api/bacnet/server/points") => {
            raw_json(&mut stream, &drivers::bacnet_server::server_points_json())
        }
        ("POST", "/api/bacnet/priority-array") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            raw_json(&mut stream, &drivers::bacnet::priority_array_json(&payload))
        }
        ("GET", "/api/bacnet/driver/tree") => {
            let body = drivers::bacnet::driver_tree_json();
            raw_json(&mut stream, &body)
        }
        ("POST", "/api/bacnet/driver/sync-discovery") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            drivers::bacnet::sync_discovery_value(),
        ),
        ("PATCH", "/api/bacnet/driver/point") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            json!({"ok": true, "updated": "point polling settings"}),
        ),
        ("POST", "/api/bacnet/point-discovery") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            require_role(
                &mut stream,
                &principal,
                &["integrator", "agent"],
                drivers::bacnet::point_discovery_value(&payload),
            )
        }
        ("POST", "/api/bacnet/read") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            let response_body = drivers::bacnet::read_present_value_json(&payload);
            raw_json(&mut stream, &response_body)
        }
        ("GET", "/api/bacnet/overrides/status") => require_role(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            drivers::tree::overrides_status_ui(),
        ),
        ("GET", "/api/bacnet/overrides/summary") => require_role(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            drivers::bacnet::overrides_summary_json(),
        ),
        ("POST", "/api/bacnet/overrides/scan-once") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            drivers::bacnet::scan_once_value(),
        ),
        ("GET", "/api/bacnet/overrides/export") => require_role_csv(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            "bacnet_overrides_export.csv",
            drivers::bacnet::overrides_csv(),
        ),
        ("GET", "/api/bacnet/overrides/export/p8") => require_role_csv(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            "bacnet_priority8_overrides.csv",
            drivers::bacnet::priority8_csv(),
        ),
        ("GET", "/api/bacnet/overrides/export/non-p8") => require_role_csv(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            "bacnet_non_priority8_overrides.csv",
            drivers::bacnet::non_priority8_csv(),
        ),

        ("POST", "/api/bacnet/write-dry-run") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(drivers::bacnet::write_dry_run_json()).unwrap(),
        ),
        ("POST", "/api/bacnet/write") => {
            let value: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            let approved = value
                .get("approved")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if can_write_field_bus(&principal.role, approved) {
                json_response(
                    &mut stream,
                    json!({"ok": true, "dry_run": true, "safety": "BACnet write requires explicit human approval; prototype never writes to field bus"}),
                )
            } else {
                audit::log_event(
                    "forbidden",
                    json!({"route": clean_path, "role": principal.role.clone()}),
                );
                status_json(
                    &mut stream,
                    "403 Forbidden",
                    json!({"ok": false, "error": "BACnet writes require integrator role and approved=true"}),
                )
            }
        }
        ("GET", "/api/modbus/points") => {
            let body = drivers::modbus::points_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/modbus/commission/status") => {
            let body = drivers::modbus::commission_status_json();
            raw_json(&mut stream, &body)
        }
        ("POST", "/api/modbus/scan") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            drivers::modbus::scan_value(),
        ),
        ("POST", "/api/modbus/read") => {
            let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
            let response_body = drivers::modbus::read_value(&payload);
            raw_json(&mut stream, &response_body)
        }
        ("GET", "/api/json-api/sources") => {
            raw_json(&mut stream, drivers::json_api::sources_json())
        }
        ("POST", "/api/json-api/poll-once") => {
            require_role(&mut stream, &principal, &["integrator", "agent"], {
                let payload = serde_json::from_str::<Value>(&body).unwrap_or(json!({}));
                if let Some(url) = payload.get("url").and_then(|v| v.as_str()) {
                    drivers::json_api::poll_url(url)
                } else {
                    drivers::json_api::poll_test_source()
                }
            })
        }
        ("POST", "/api/json-api/register") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(drivers::json_api::register_json()).unwrap(),
        ),
        ("GET", "/api/historian/validation/status") => {
            json_response(&mut stream, historian::store::status_json())
        }
        ("GET", "/api/validation-runs/current/status") => {
            json_response(&mut stream, bench::smoke::status_json())
        }
        ("POST", "/api/validation-runs/current/sample") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::capture_sample(&serde_json::from_str(&body).unwrap_or(json!({}))),
        ),
        ("POST", "/api/validation-runs/current/eval") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::evaluate_historian_fdd(),
        ),
        ("POST", "/api/validation-runs/current/cycle") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::evaluate_sample(&serde_json::from_str(&body).unwrap_or(json!({}))),
        ),
        ("POST", "/api/validation-runs/current/inject-scenario") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::inject_scenario(&serde_json::from_str(&body).unwrap_or(json!({}))),
        ),
        // Deprecated aliases — remove after downstream scripts migrate.
        ("GET", "/api/historian/bench/5007/status") => {
            json_response(&mut stream, historian::store::status_json())
        }
        ("GET", "/api/bench/5007/smoke/status") => {
            json_response(&mut stream, bench::smoke::status_json())
        }
        ("POST", "/api/bench/5007/smoke/sample") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::capture_sample(&serde_json::from_str(&body).unwrap_or(json!({}))),
        ),
        ("POST", "/api/bench/5007/smoke/eval") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::evaluate_historian_fdd(),
        ),
        ("POST", "/api/bench/5007/smoke/cycle") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::evaluate_sample(&serde_json::from_str(&body).unwrap_or(json!({}))),
        ),
        ("POST", "/api/bench/5007/smoke/inject-scenario") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            bench::smoke::inject_scenario(&serde_json::from_str(&body).unwrap_or(json!({}))),
        ),
        ("GET", "/api/control/status") => raw_json(&mut stream, control::cdl::simulate_json()),
        ("POST", "/api/control/simulate") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(control::cdl::simulate_json()).unwrap(),
        ),
        ("POST", "/api/reports/rcx/plan") => json_response(
            &mut stream,
            json!({"ok": true, "sections": ["executive_summary", "faults", "overrides", "energy_opportunities", "trend_plots"]}),
        ),
        ("GET", "/api/reports/rcx/list") => raw_json(&mut stream, REPORTS),
        ("POST", "/api/reports/rcx/generate") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            json!({"ok": true, "report_id": "rcx-demo-001", "path": "workspace/reports/rcx/rcx-demo-001.md", "sections": ["faults", "overrides", "plotly_trends", "recommendations"]}),
        ),
        _ => {
            if let Some(resp) = handle_data_management_dynamic(
                &mut stream,
                &principal,
                method.as_str(),
                &clean_path,
            ) {
                return resp;
            }
            if let Some(resp) = handle_import_job_dynamic(
                &mut stream,
                &principal,
                method.as_str(),
                &clean_path,
                &body,
            ) {
                return resp;
            }
            if method == "GET" && clean_path.starts_with("/api/bacnet/jobs/") {
                let job_id = clean_path.trim_start_matches("/api/bacnet/jobs/");
                return json_response(
                    &mut stream,
                    json!({"ok": true, "job_id": job_id, "status": "complete", "result": {}}),
                );
            }
            if let Some(resp) = handle_fdd_wires_dynamic(
                &mut stream,
                &principal,
                method.as_str(),
                &clean_path,
                &body,
            ) {
                resp
            } else {
                status_json(
                    &mut stream,
                    "404 Not Found",
                    json!({"ok": false, "error": "unknown endpoint", "path": clean_path}),
                )
            }
        }
    }
}

fn parse_json_body(body: &str) -> Value {
    serde_json::from_str(body).unwrap_or(json!({}))
}

fn query_param(path: &str, key: &str) -> Option<String> {
    path.split('?').nth(1).and_then(|qs| {
        qs.split('&').find_map(|pair| {
            let mut parts = pair.splitn(2, '=');
            if parts.next()? == key {
                Some(parts.next()?.to_string())
            } else {
                None
            }
        })
    })
}

fn path_parts(path: &str) -> Vec<&str> {
    path.trim_matches('/').split('/').collect()
}

fn handle_fdd_wires_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
    body: &str,
) -> Option<std::io::Result<()>> {
    let parts = path_parts(path);
    if parts.len() < 3 || parts[0] != "api" {
        return None;
    }

    match (method, parts.as_slice()) {
        ("GET", ["api", "fdd-rules", rule_id]) => {
            Some(raw_json(stream, &fdd::wires::api::get_rule_json(rule_id)))
        }
        ("PUT", ["api", "fdd-rules", rule_id]) => {
            let mut payload = parse_json_body(body);
            payload["rule_id"] = json!(rule_id);
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::save_rule(&payload, &principal.sub),
            ))
        }
        ("POST", ["api", "fdd-rules", rule_id, "validate-sql"]) => {
            let mut payload = parse_json_body(body);
            payload["rule_id"] = json!(rule_id);
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::validate_rule_sql(&payload),
            ))
        }
        ("POST", ["api", "fdd-rules", rule_id, "test-sql"]) => {
            let mut payload = parse_json_body(body);
            payload["rule_id"] = json!(rule_id);
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::test_rule_sql(&payload),
            ))
        }
        ("POST", ["api", "fdd-rules", rule_id, "activate"]) => Some(require_role(
            stream,
            principal,
            &["integrator"],
            fdd::wires::api::activate_rule(rule_id, &principal.sub, &principal.role),
        )),
        ("GET", ["api", "fdd-wires", "graphs", graph_id]) => {
            let site = query_param(path, "site_id").unwrap_or_else(|| "site:demo".to_string());
            Some(raw_json(
                stream,
                &fdd::wires::api::get_graph(&site, graph_id),
            ))
        }
        ("PUT", ["api", "fdd-wires", "graphs", graph_id]) => {
            let site = query_param(path, "site_id").unwrap_or_else(|| "site:demo".to_string());
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::update_graph(
                    &site,
                    graph_id,
                    &parse_json_body(body),
                    &principal.sub,
                ),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "validate"]) => {
            let site = query_param(path, "site_id").unwrap_or_else(|| "site:demo".to_string());
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::validate_graph(&site, graph_id),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "test"]) => {
            let site = query_param(path, "site_id").unwrap_or_else(|| "site:demo".to_string());
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::test_graph(&site, graph_id),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "approve"]) => {
            let site = query_param(path, "site_id").unwrap_or_else(|| "site:demo".to_string());
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::approve_graph(&site, graph_id, &principal.sub, &principal.role),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "activate"]) => {
            let site = query_param(path, "site_id").unwrap_or_else(|| "site:demo".to_string());
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::activate_graph(&site, graph_id, &principal.sub, &principal.role),
            ))
        }
        _ => None,
    }
}

fn handle_data_management_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
) -> Option<std::io::Result<()>> {
    let parts = path_parts(path);
    if parts.len() != 5 || parts[0] != "api" || parts[1] != "data-management" || parts[2] != "purge"
    {
        return None;
    }
    if method != "GET" {
        return None;
    }
    let job_id = parts[4];
    if job_id.contains("..") || job_id.contains('/') {
        return Some(json_response(
            stream,
            json!({"ok": false, "error": "invalid job id"}),
        ));
    }
    Some(require_role(
        stream,
        principal,
        &["integrator", "agent", "operator"],
        data_management::purge_job_status(job_id),
    ))
}

fn handle_import_job_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
    body: &str,
) -> Option<std::io::Result<()>> {
    let parts = path_parts(path);
    if parts.len() < 4 || parts[0] != "api" || parts[1] != "import" || parts[2] != "jobs" {
        return None;
    }
    let job_id = import::safe_job_id(parts[3])?;
    match (method, parts.get(4).copied()) {
        ("POST", Some("upload")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            import::upload_csv(job_id, body),
        )),
        ("GET", Some("preview")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent", "operator"],
            import::preview_job(job_id),
        )),
        ("PATCH", Some("options")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            import::patch_options(job_id, &parse_json_body(body)),
        )),
        ("POST", Some("commit")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            import::commit_job(job_id),
        )),
        ("GET", Some("status")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent", "operator"],
            import::status_job(job_id),
        )),
        ("GET", Some("report")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent", "operator"],
            import::report_job(job_id),
        )),
        _ => None,
    }
}

const READ_EXPORT_ROLES: &[&str] = &["operator", "integrator", "agent"];

fn query_string(path: &str) -> &str {
    path.split('?').nth(1).unwrap_or("")
}

fn csv_attachment_response(
    stream: &mut TcpStream,
    body: &str,
    filename: &str,
) -> std::io::Result<()> {
    let content_type = "text/csv; charset=utf-8";
    let headers = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Disposition: attachment; filename=\"{filename}\"\r\n{sec}{cors}Content-Length: {len}\r\nConnection: close\r\n\r\n",
        sec = security_headers(content_type, false),
        cors = cors_origin(),
        len = body.len(),
        filename = filename
    );
    stream.write_all(headers.as_bytes())?;
    stream.write_all(body.as_bytes())
}

fn require_role_csv(
    stream: &mut TcpStream,
    principal: &Principal,
    roles: &[&str],
    body: String,
    filename: &str,
) -> std::io::Result<()> {
    if role_allowed(principal, roles) {
        csv_attachment_response(stream, &body, filename)
    } else {
        audit::log_event(
            "forbidden",
            json!({"role": principal.role.clone(), "required": roles, "export": filename}),
        );
        status_json(
            stream,
            "403 Forbidden",
            json!({"ok": false, "error": "insufficient role", "role": principal.role}),
        )
    }
}

fn read_http_request(stream: &mut TcpStream) -> std::io::Result<String> {
    let mut buf = Vec::with_capacity(4096);
    let mut chunk = [0_u8; 4096];
    loop {
        let n = stream.read(&mut chunk)?;
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
        if buf.windows(4).any(|w| w == b"\r\n\r\n") {
            break;
        }
        if buf.len() > 65536 {
            break;
        }
    }
    if buf.is_empty() {
        return Ok(String::new());
    }
    let header_end = buf
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .map(|i| i + 4)
        .unwrap_or(buf.len());
    let headers = &buf[..header_end];
    let content_length = headers
        .split(|&b| b == b'\n')
        .filter_map(|line| {
            let line = if line.ends_with(b"\r") {
                &line[..line.len() - 1]
            } else {
                line
            };
            let line = std::str::from_utf8(line).ok()?;
            let (name, value) = line.split_once(':')?;
            if name.trim().eq_ignore_ascii_case("content-length") {
                value.trim().parse::<usize>().ok()
            } else {
                None
            }
        })
        .next()
        .unwrap_or(0);
    let body_start = header_end;
    while buf.len().saturating_sub(body_start) < content_length {
        let n = stream.read(&mut chunk)?;
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
    }
    Ok(String::from_utf8_lossy(&buf).into_owned())
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

fn login_handler(stream: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let value: Value = serde_json::from_str(body).unwrap_or(json!({}));
    let cfg = auth_config();
    match authenticate(cfg, &value) {
        Ok(result) => json_response(stream, login_response(result)),
        Err(err) => {
            if err.contains("too many") {
                status_json(
                    stream,
                    "429 Too Many Requests",
                    json!({"ok": false, "error": err}),
                )
            } else {
                status_json(
                    stream,
                    "401 Unauthorized",
                    json!({"ok": false, "error": err}),
                )
            }
        }
    }
}

fn authorize(headers: &[(String, String)]) -> Result<Principal, String> {
    let cfg = auth_config();
    if !cfg.required {
        return Ok(Principal {
            sub: "anonymous".to_string(),
            role: "integrator".to_string(),
        });
    }
    let auth = headers
        .iter()
        .find(|(k, _)| k == "authorization")
        .map(|(_, v)| v.clone())
        .ok_or("missing Authorization: Bearer token")?;
    let token = auth
        .strip_prefix("Bearer ")
        .ok_or("expected Bearer token")?;
    auth::jwt::verify_token(cfg, token)
}

fn require_role_csv(
    stream: &mut TcpStream,
    principal: &Principal,
    roles: &[&str],
    filename: &str,
    body: String,
) -> std::io::Result<()> {
    if role_allowed(principal, roles) {
        csv_attachment_response(stream, filename, &body)
    } else {
        audit::log_event(
            "forbidden",
            json!({"role": principal.role.clone(), "required": roles, "export": filename}),
        );
        status_json(
            stream,
            "403 Forbidden",
            json!({"ok": false, "error": "insufficient role", "role": principal.role}),
        )
    }
}

fn csv_attachment_response(
    stream: &mut TcpStream,
    filename: &str,
    body: &str,
) -> std::io::Result<()> {
    let headers = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/csv; charset=utf-8\r\nContent-Disposition: attachment; filename=\"{}\"\r\n{sec}{cors}Content-Length: {len}\r\nConnection: close\r\n\r\n",
        filename.replace('"', ""),
        sec = security_headers("text/csv; charset=utf-8", true),
        cors = cors_origin(),
        len = body.len()
    );
    stream.write_all(headers.as_bytes())?;
    stream.write_all(body.as_bytes())
}

fn require_role(
    stream: &mut TcpStream,
    principal: &Principal,
    roles: &[&str],
    body: Value,
) -> std::io::Result<()> {
    if role_allowed(principal, roles) {
        json_response(stream, body)
    } else {
        audit::log_event(
            "forbidden",
            json!({"role": principal.role.clone(), "required": roles}),
        );
        status_json(
            stream,
            "403 Forbidden",
            json!({"ok": false, "error": "insufficient role", "role": principal.role}),
        )
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
            {"name":"fdd.wires.graphs","method":"GET","path":"/api/fdd-wires/graphs","requires":"JWT"},
            {"name":"fdd.wires.propose","method":"POST","path":"/api/fdd-wires/propose-assignments","requires":"integrator|agent"},
            {"name":"fdd.rules.list","method":"GET","path":"/api/fdd-rules","requires":"JWT"},
            {"name":"fdd.rules.activate","method":"POST","path":"/api/fdd-rules/{id}/activate","requires":"integrator"},
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

fn protocol_enabled(env_key: &str) -> bool {
    env::var(env_key)
        .map(|v| v != "0" && v.to_lowercase() != "false")
        .unwrap_or(true)
}

fn stack_status() -> Value {
    let bacnet = if protocol_enabled("OPENFDD_BACNET_ENABLED") {
        json!({"id":"bacnet","status":"ready","write_guard":"human approval required"})
    } else {
        json!({"id":"bacnet","status":"disabled","note":"OPENFDD_BACNET_ENABLED=0"})
    };
    let modbus = if protocol_enabled("OPENFDD_MODBUS_ENABLED") {
        json!({"id":"modbus","status":"ready"})
    } else {
        json!({"id":"modbus","status":"disabled","note":"OPENFDD_MODBUS_ENABLED=0"})
    };
    let haystack = if protocol_enabled("OPENFDD_HAYSTACK_ENABLED") {
        json!({"id":"haystack","status":"ready"})
    } else {
        json!({"id":"haystack","status":"disabled","note":"OPENFDD_HAYSTACK_ENABLED=0"})
    };
    let commission = if protocol_enabled("OPENFDD_BACNET_ENABLED")
        || protocol_enabled("OPENFDD_MODBUS_ENABLED")
    {
        json!({"id":"openfdd-commission","label":"BACnet + Modbus + JSON polling","status":"online","auth_required":true})
    } else {
        json!({"id":"openfdd-commission","label":"Field-bus polling","status":"disabled","auth_required":false,"note":"Not started in desktop JSON/CSV mode"})
    };
    let haystack_svc = if protocol_enabled("OPENFDD_HAYSTACK_ENABLED") {
        json!({"id":"openfdd-haystack-gateway","label":"Haystack read/nav/ops integration","status":"online","auth_required":true})
    } else {
        json!({"id":"openfdd-haystack-gateway","label":"Haystack gateway","status":"disabled","auth_required":false})
    };
    json!({
        "ok": true,
        "auth_required": auth_config().required,
        "services": [
            {"id":"openfdd-bridge","label":"API + dashboard + historian","status":"online","auth_required":true},
            commission,
            haystack_svc,
            bacnet,
            modbus,
            haystack,
            {"id":"json-api","status": if protocol_enabled("OPENFDD_JSON_API_ENABLED") { "ready" } else { "disabled" }},
            {"id":"csv-import","status": if protocol_enabled("OPENFDD_IMPORT_ENABLED") { "ready" } else { "disabled" }},
            {"id":"csv-export","status": if protocol_enabled("OPENFDD_EXPORT_ENABLED") { "ready" } else { "disabled" }},
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
    response(
        stream,
        status,
        "application/json",
        value.to_string().as_bytes(),
    )
}

fn options(stream: &mut TcpStream) -> std::io::Result<()> {
    let origin = cors_origin();
    let headers = format!(
        "HTTP/1.1 204 No Content\r\n{origin}Access-Control-Allow-Methods: GET,POST,PUT,OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type, Authorization\r\nContent-Length: 0\r\n\r\n"
    );
    stream.write_all(headers.as_bytes())
}

fn cors_origin() -> String {
    match env::var("OPENFDD_CORS_ORIGIN") {
        Ok(v) if !v.is_empty() => format!("Access-Control-Allow-Origin: {v}\r\n"),
        _ => String::new(),
    }
}

fn security_headers(content_type: &str, is_auth: bool) -> String {
    let mut h = String::new();
    h.push_str("X-Content-Type-Options: nosniff\r\n");
    h.push_str("Referrer-Policy: no-referrer\r\n");
    h.push_str("X-Frame-Options: SAMEORIGIN\r\n");
    h.push_str(&format!(
        "Content-Security-Policy: default-src 'self'; script-src 'self' https://unpkg.com https://cdn.plot.ly; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'\r\n"
    ));
    if is_auth || content_type.contains("json") {
        h.push_str(
            "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\nPragma: no-cache\r\n",
        );
    }
    h
}

fn static_file(stream: &mut TcpStream, frontend: &Path, path: &str) -> std::io::Result<()> {
    let rel = if path == "/" {
        "index.html"
    } else {
        path.trim_start_matches('/')
    };
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

fn response(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &[u8],
) -> std::io::Result<()> {
    let is_auth = status.contains("401") || status.contains("403") || status.contains("429");
    let headers = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n{sec}{cors}Content-Length: {len}\r\nConnection: close\r\n\r\n",
        sec = security_headers(content_type, is_auth),
        cors = cors_origin(),
        len = body.len()
    );
    stream.write_all(headers.as_bytes())?;
    stream.write_all(body)
}
