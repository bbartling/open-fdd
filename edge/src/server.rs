//! HTTP edge server and route handlers.

use crate::auth;
use crate::auth::audit;
use crate::auth::auth_config;
use crate::auth::config::Principal;
use crate::auth::login::{authenticate, login_response};
use crate::auth::rbac::{can_write_field_bus, role_allowed};
use crate::{
    control, csv_ingest, dashboard, data_management, drivers, export, faults, fdd, historian,
    import, ingest, model, ops, reports, timeseries, validation, version,
};

use serde_json::{json, Value};
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

const MAX_BODY_BYTES: usize = 1_048_576;
const MAX_CSV_UPLOAD_BYTES: usize = 128 * 1024 * 1024;
const READ_TIMEOUT_SECS: u64 = 30;
const CSV_READ_TIMEOUT_SECS: u64 = 600;

fn max_body_bytes_for_path(path: &str) -> usize {
    let route = path.split('?').next().unwrap_or(path);
    if route == "/api/csv/import/preview" {
        env::var("OPENFDD_MAX_CSV_UPLOAD_BYTES")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(MAX_CSV_UPLOAD_BYTES)
    } else {
        env::var("OPENFDD_MAX_BODY_BYTES")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(MAX_BODY_BYTES)
    }
}

fn read_timeout_secs_for_path(path: &str) -> u64 {
    let route = path.split('?').next().unwrap_or(path);
    if route.starts_with("/api/csv/import/") {
        env::var("OPENFDD_CSV_READ_TIMEOUT_SECS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(CSV_READ_TIMEOUT_SECS)
    } else {
        READ_TIMEOUT_SECS
    }
}

pub fn run() -> std::io::Result<()> {
    let cfg = auth_config();
    if let Err(err) = cfg.validate_for_production() {
        if env::var("OPENFDD_ALLOW_INSECURE_AUTH").as_deref() != Ok("1") {
            return Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                err,
            ));
        }
        eprintln!("auth configuration warning: {err}");
    }
    let port = env::var("PORT").unwrap_or_else(|_| "8080".to_string());
    let root = env::var("FRONTEND_DIR").unwrap_or_else(|_| "/app/frontend".to_string());
    let service_mode = env::var("SERVICE_MODE").unwrap_or_else(|_| "bridge".to_string());
    drivers::bacnet::start_hourly_override_scanner(service_mode.clone());
    drivers::bacnet::start_bacnet_poll_loop(service_mode.clone());
    drivers::bacnet_server_runtime::start_background();
    if service_mode == "bridge" {
        drivers::json_api::seed_from_env_if_needed();
    }
    let bind_host = env::var("OPENFDD_BIND_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let listener = TcpListener::bind(format!("{bind_host}:{port}"))?;
    println!("Open-FDD Rust Edge API listening on http://{bind_host}:{port}");
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let root = root.clone();
                thread::spawn(move || {
                    let _ = stream.set_read_timeout(Some(Duration::from_secs(READ_TIMEOUT_SECS)));
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
    let route_path = path.split('?').next().unwrap_or(path.as_str()).to_string();

    if method == "OPTIONS" {
        return options(&mut stream);
    }
    if method == "GET" && (route_path == "/api/health" || route_path == "/health") {
        return json_response(&mut stream, version::health_json(auth_config().required));
    }
    if method == "POST" && route_path == "/api/auth/login" {
        return login_handler(&mut stream, &body);
    }
    if method == "POST" && route_path == "/api/auth/logout" {
        audit::log_event(
            "logout",
            json!({"note":"stateless JWT cleared client-side"}),
        );
        return json_response(&mut stream, json!({"ok": true}));
    }
    if method == "GET" && route_path == "/api/auth/status" {
        let cfg = auth_config();
        return json_response(
            &mut stream,
            json!({"ok": true, "auth_required": cfg.required}),
        );
    }
    if method == "POST" && route_path == "/api/dev/quick-login" {
        return json_response(
            &mut stream,
            ops::dev_stack::quick_login(&parse_json_body_or_empty(&body)),
        );
    }
    if method == "POST" && route_path == "/api/dev/run-script" {
        return json_response(
            &mut stream,
            ops::dev_stack::run_script(&parse_json_body_or_empty(&body)),
        );
    }
    // Public read-only dashboard endpoints (home/login view without JWT).
    if method == "GET"
        && (route_path == "/api/building/snapshot" || route_path == "/api/building/status")
    {
        let body = if route_path == "/api/building/snapshot" {
            dashboard::building_snapshot()
        } else {
            dashboard::building_status()
        };
        return json_response(&mut stream, body);
    }
    if method == "GET"
        && !route_path.starts_with("/api/")
        && !route_path.starts_with("/openfdd-agent/")
    {
        return static_file(&mut stream, frontend, &route_path);
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

    match (method.as_str(), route_path.as_str()) {
        ("GET", "/api/auth/whoami") => json_response(
            &mut stream,
            json!({"ok": true, "principal": {"sub": principal.sub, "role": principal.role}}),
        ),
        ("GET", "/api/auth/me") => json_response(
            &mut stream,
            json!({
                "ok": true,
                "username": principal.sub,
                "role": principal.role,
                "auth_required": auth_config().required
            }),
        ),
        ("POST", "/api/auth/ws-ticket") => {
            let (ticket, _exp) =
                auth::jwt::create_ws_ticket(auth_config(), &principal.sub, &principal.role);
            json_response(
                &mut stream,
                json!({"ok": true, "ticket": ticket, "username": principal.sub, "role": principal.role}),
            )
        }
        ("GET", "/api/ops/stack") => json_response(&mut stream, dashboard::stack_health()),

        ("GET", "/api/health/stack") => json_response(&mut stream, dashboard::stack_health()),
        ("GET", "/api/building/snapshot") => {
            json_response(&mut stream, dashboard::building_snapshot())
        }
        ("GET", "/api/building/status") => json_response(&mut stream, dashboard::building_status()),
        ("GET", "/openfdd-agent/building-insight") => {
            let force = query_string(&path).contains("force=true");
            json_response(&mut stream, dashboard::building_insight(force))
        }
        ("GET", "/api/dashboard/summary") => json_response(&mut stream, dashboard::summary()),
        ("GET", "/api/dashboard/sites") => json_response(&mut stream, dashboard::sites()),
        ("GET", "/api/dashboard/faults") => json_response(&mut stream, dashboard::faults_panel()),
        ("GET", "/api/dashboard/faults/active") => {
            json_response(&mut stream, dashboard::faults_active())
        }
        ("GET", "/api/dashboard/faults/history") => {
            json_response(&mut stream, dashboard::faults_history())
        }
        ("GET", "/api/dashboard/model-coverage") => {
            json_response(&mut stream, dashboard::model_coverage_route())
        }
        ("GET", "/api/dashboard/source-health") => {
            json_response(&mut stream, dashboard::source_health())
        }
        ("GET", "/api/dashboard/historian-health") => {
            json_response(&mut stream, dashboard::historian_health())
        }
        ("GET", "/api/dashboard/security") => {
            json_response(&mut stream, dashboard::security_status())
        }
        ("GET", "/api/dashboard/analytics") => json_response(&mut stream, dashboard::analytics()),
        ("GET", "/api/faults") => json_response(&mut stream, faults::list_json(None)),
        ("GET", "/api/faults/status") => json_response(&mut stream, faults::status_json()),
        ("GET", "/api/faults/summary") => json_response(&mut stream, faults::summary_json()),
        ("GET", "/api/faults/export.csv") => {
            let body = faults::export_csv();
            require_role_csv(
                &mut stream,
                &principal,
                READ_EXPORT_ROLES,
                body,
                "openfdd_faults.csv",
            )
        }
        ("GET", "/api/faults/catalog") => json_response(&mut stream, faults::catalog_json()),
        ("GET", "/api/faults/tree") => json_response(&mut stream, faults::tree_json()),
        ("GET", "/api/faults/applicable") => {
            let site = query_param(&path, "site_id");
            json_response(&mut stream, faults::applicable_json(site.as_deref()))
        }
        ("POST", "/api/faults/validate-scope") => json_response(
            &mut stream,
            faults::validate_scope_json(
                serde_json::from_str::<Value>(&body)
                    .ok()
                    .and_then(|v| {
                        v.get("site_id")
                            .and_then(|s| s.as_str())
                            .map(str::to_string)
                    })
                    .as_deref(),
            ),
        ),
        ("GET", "/api/model/sites") => json_response(&mut stream, dashboard::sites()),
        ("GET", "/api/ui/tabs") => raw_json(&mut stream, ops::bridge::ui_tabs_json()),
        ("GET", "/api/bridge/status") => raw_json(&mut stream, ops::bridge::status_json()),
        ("GET", "/api/agent/manifest") => json_response(&mut stream, agent_manifest()),
        ("GET", "/api/agent/tools") => json_response(&mut stream, agent_tools()),
        ("GET", "/api/ingest/contract") => json_response(&mut stream, ingest::contract_json()),
        ("POST", "/api/agent/dev-harness") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            || ops::agent_chat::chat_reply(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/agent/config") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            ops::agent_chat::config_json,
        ),
        ("POST", "/api/agent/chat") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            || ops::agent_chat::chat_reply(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/agent/chat/cancel") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            ops::agent_chat::cancel_reply,
        ),
        ("POST", "/api/agent/reset") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            ops::agent_chat::reset_reply,
        ),
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
        ("GET", "/api/historian/query") => {
            raw_json(&mut stream, &historian::arrow_table::query_json())
        }
        ("POST", "/api/historian/query") => raw_json(
            &mut stream,
            &historian::arrow_table::query_json_from_body(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/export/meta") => json_response(&mut stream, export::meta_json()),
        ("GET", "/api/export/historian.csv") => {
            let q = export::parse_query(query_string(&path));
            let body = export::historian_csv(&q);
            let name = export::export_filename("historian");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/faults.csv") => {
            let qs = query_string(&path);
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
            let q = export::parse_query(query_string(&path));
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
            let q = export::parse_query(query_string(&path));
            let body = export::validation_runs_csv(&q);
            let name = export::export_filename("validation_runs");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/export/import-jobs.csv") => {
            let body = export::import_jobs_csv();
            let name = export::export_filename("import_jobs");
            require_role_csv(&mut stream, &principal, READ_EXPORT_ROLES, body, &name)
        }
        ("GET", "/api/data-management/summary") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            data_management::storage_summary,
        ),
        ("GET", "/api/data-management/storage") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            data_management::storage_summary,
        ),
        ("GET", "/api/host/stats") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            ops::host_stats::stats_json,
        ),
        ("POST", "/api/data-management/purge/preview") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            data_management::preview_purge(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/data-management/purge/execute") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            data_management::execute_purge(&parse_json_body_or_empty(&body), &principal.role),
        ),
        ("GET", "/api/data-management/policies") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            data_management::get_policies,
        ),
        ("PUT", "/api/data-management/policies") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            data_management::put_policies(&parse_json_body_or_empty(&body), &principal.role),
        ),
        ("GET", "/api/data-management/agent-tools") => require_role_lazy(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            data_management::agent_tools,
        ),
        ("POST", "/api/import/jobs") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            import::create_job(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/csv-workbench/preview") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            model::csv_workbench::preview_model(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/csv-workbench/quality") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            model::csv_workbench::analyze_quality(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/csv-workbench/recipes") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            model::csv_workbench::list_recipes(),
        ),
        ("POST", "/api/csv-workbench/recipes") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::csv_workbench::save_recipe(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/csv-workbench/column-mappings") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            model::csv_workbench::get_column_mappings(query_param(&path, "source_id").as_deref()),
        ),
        ("PUT", "/api/csv-workbench/column-mappings") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::csv_workbench::save_column_mappings(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/csv-workbench/draft-rule") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::csv_workbench::draft_rule(
                &parse_json_body_or_empty(&body),
                principal.sub.as_str(),
            ),
        ),
        ("POST", "/api/csv-workbench/purge-source/preview") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::csv_workbench::purge_source_preview(
                parse_json_body_or_empty(&body)
                    .get("source_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
            ),
        ),
        ("POST", "/api/csv-workbench/purge-source/execute") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::csv_workbench::purge_source_execute(
                parse_json_body_or_empty(&body)
                    .get("source_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
                parse_json_body_or_empty(&body)
                    .get("confirm")
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
            ),
        ),
        ("POST", "/api/csv/import/preview") => {
            let ct = header_value(&headers, "content-type");
            let out = if ct.contains("application/json") {
                csv_ingest::preview_json_handler(&parse_json_body_or_empty(&body))
            } else {
                csv_ingest::preview_handler(&ct, body.as_bytes(), None)
            };
            require_role(
                &mut stream,
                &principal,
                &["integrator", "agent", "operator"],
                out,
            )
        }
        ("POST", "/api/csv/import/plan") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            csv_ingest::plan_handler(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/csv/import/preflight") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            csv_ingest::preflight_handler(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/csv/import/execute") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            csv_ingest::execute_handler(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/datasets") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent", "operator"],
            csv_ingest::list_datasets(),
        ),
        ("DELETE", "/api/datasets") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            match parse_json_body_or_empty(&body)
                .get("dataset_id")
                .and_then(|v| v.as_str())
            {
                Some(id) => match csv_ingest::delete_dataset(id) {
                    Ok(()) => json!({"ok": true}),
                    Err(e) => json!({"ok": false, "error": e}),
                },
                None => json!({"ok": false, "error": "dataset_id required"}),
            },
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
        ("GET", "/api/control/cdl/bindings") => raw_json(
            &mut stream,
            &model::assignments::algorithm_bindings_json_string(),
        ),
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
            json!({
                "ok": true,
                "dry_run": true,
                "result": serde_json::from_str::<Value>(control::cdl::dry_run_json()).unwrap_or(json!({}))
            }),
        ),
        ("GET", "/api/model/haystack") => {
            raw_json(&mut stream, &model::persist::haystack_model_json_string())
        }
        ("GET", "/api/model/sources") => raw_json(&mut stream, &drivers::haystack::sources_json()),
        ("GET", "/api/model/equipment") => {
            raw_json(&mut stream, &drivers::haystack::equipment_json())
        }
        ("GET", "/api/model/points") => raw_json(&mut stream, &drivers::haystack::points_json()),
        ("GET", "/api/model/assignments") => {
            raw_json(&mut stream, &model::assignments::assignments_json_string())
        }
        ("POST", "/api/model/assignments/save") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::assignments::save_from_request(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/model/assignments/resolve") => {
            raw_json(&mut stream, model::assignments::resolve_json())
        }
        ("GET", "/api/model/algorithm-bindings") => raw_json(
            &mut stream,
            &model::assignments::algorithm_bindings_json_string(),
        ),
        ("GET", "/api/model/tree") => json_response(&mut stream, model::commissioning::tree_json()),
        ("GET", "/api/model/graph") => json_response(
            &mut stream,
            model::query::network_graph(query_param(&path, "site_id").as_deref()),
        ),
        ("GET", "/api/model/commissioning-export") => json_response(
            &mut stream,
            model::commissioning::commissioning_export_json(),
        ),
        ("POST", "/api/model/commissioning-import") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::commissioning::import_commissioning(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/model/health") => {
            json_response(&mut stream, model::commissioning::health_json())
        }
        ("GET", "/api/model/bacnet-sync") => {
            json_response(&mut stream, model::commissioning::bacnet_sync_status_json())
        }
        ("POST", "/api/model/bacnet-sync") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::commissioning::bacnet_sync_apply_json(),
        ),
        ("POST", "/api/model/sync-ttl") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            model::commissioning::sync_ttl_json(),
        ),
        ("GET", p) if p.starts_with("/api/model/ttl") => {
            let ttl = model::rdf::haystack_to_turtle();
            response(
                &mut stream,
                "200 OK",
                "text/turtle; charset=utf-8",
                ttl.as_bytes(),
            )
        }
        ("GET", "/api/haystack/about") => raw_json(&mut stream, &drivers::haystack::about_json()),
        ("GET", "/api/haystack/config") => {
            raw_json(&mut stream, &drivers::haystack::config_get_json())
        }
        ("POST", "/api/haystack/config") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(&drivers::haystack::config_save_json(
                &parse_json_body_or_empty(&body),
            ))
            .unwrap_or(json!({"ok": false})),
        ),
        ("GET", "/api/haystack/status") => raw_json(&mut stream, &drivers::haystack::status_json()),
        ("GET", "/api/haystack/ops") => raw_json(&mut stream, &drivers::haystack::ops_json()),
        ("POST", "/api/haystack/test") => raw_json(&mut stream, &drivers::haystack::test_json()),
        ("POST", "/api/haystack/read") => {
            let payload = parse_json_body_or_empty(&body);
            raw_json(&mut stream, &drivers::haystack::read_json(&payload))
        }
        ("POST", "/api/haystack/write") => {
            require_role_lazy(&mut stream, &principal, &["integrator", "agent"], || {
                serde_json::from_str::<Value>(&drivers::haystack::write_json(
                    &parse_json_body_or_empty(&body),
                ))
                .unwrap_or(json!({"ok": false}))
            })
        }
        ("POST", "/api/haystack/nav") => {
            let payload = parse_json_body_or_empty(&body);
            raw_json(&mut stream, &drivers::haystack::nav_json(&payload))
        }
        ("POST", "/api/haystack/ops") => raw_json(&mut stream, &drivers::haystack::ops_json()),
        ("POST", "/api/haystack/poll-once") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(&drivers::haystack::poll_once_json(
                &parse_json_body_or_empty(&body),
            ))
            .unwrap_or(json!({"ok": false})),
        ),
        ("GET", "/api/haystack/driver/tree") => {
            raw_json(&mut stream, &drivers::haystack::driver_tree_json())
        }
        ("POST", "/api/haystack/import") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(&drivers::haystack::import_json(
                &parse_json_body_or_empty(&body),
            ))
            .unwrap_or(json!({"ok": false})),
        ),
        ("POST", "/api/model/haystack/import") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(&drivers::haystack::import_json(
                &parse_json_body_or_empty(&body),
            ))
            .unwrap_or(json!({"ok": false})),
        ),
        ("POST", "/api/model/query") => json_response(
            &mut stream,
            json!({"ok": true, "rows": model::query::haystack_rows()}),
        ),
        ("GET", "/api/model/sparql/predefined") => {
            json_response(&mut stream, model::sparql::predefined())
        }
        ("POST", "/api/model/sparql") => json_response(
            &mut stream,
            model::sparql::execute(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/fdd/run") => match parse_json_body(&body) {
            Ok(payload) => require_role(
                &mut stream,
                &principal,
                &["integrator", "agent"],
                fdd::datafusion_sql::run_fdd_response(&payload),
            ),
            Err(err) => json_response(&mut stream, json!({"ok": false, "error": err})),
        },
        ("GET", "/api/rules") => {
            json_response(&mut stream, fdd::datafusion_sql::list_rules_response())
        }
        ("POST", "/api/rules/save") => match parse_json_body(&body) {
            Ok(payload) => require_role(
                &mut stream,
                &principal,
                &["integrator", "agent"],
                fdd::datafusion_sql::save_rule_response(&payload, &principal.sub),
            ),
            Err(err) => json_response(&mut stream, json!({"ok": false, "error": err})),
        },
        ("POST", "/api/rules/batch") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            fdd::datafusion_sql::batch_run_response(),
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
            fdd::wires::api::save_rule(&parse_json_body_or_empty(&body), &principal.sub),
        ),
        ("POST", "/api/fdd-rules/builder-sql") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            fdd::wires::api::builder_sql(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/fdd-wires/graphs") => raw_json(
            &mut stream,
            &fdd::wires::api::list_graphs(query_param(&path, "site_id").as_deref()),
        ),
        ("POST", "/api/fdd-wires/graphs") => require_role(
            &mut stream,
            &principal,
            &["integrator"],
            fdd::wires::api::create_graph(&parse_json_body_or_empty(&body), &principal.sub),
        ),
        ("POST", "/api/fdd-wires/propose-assignments") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            fdd::wires::api::propose_assignments(&parse_json_body_or_empty(&body), &principal.role),
        ),
        ("POST", "/api/fdd-wires/sync-from-assignments") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            fdd::wires::api::sync_from_assignments(
                &parse_json_body_or_empty(&body),
                &principal.sub,
                &principal.role,
            ),
        ),
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
        ("GET", "/api/openfdd/optimization-enabled") => json_response(
            &mut stream,
            json!({
                "ok": true,
                "enabled": drivers::bacnet_server_runtime::optimization_enabled()
            }),
        ),
        ("POST", "/api/openfdd/optimization-enabled") => {
            require_role(&mut stream, &principal, &["integrator", "agent"], {
                let payload: Value = serde_json::from_str(&body).unwrap_or(json!({}));
                let enabled = payload
                    .get("enabled")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);
                json!({
                    "ok": true,
                    "enabled": drivers::bacnet_server_runtime::set_optimization_enabled(enabled)
                })
            })
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
        ("PATCH", "/api/bacnet/driver/device/remap") => {
            require_role_lazy(&mut stream, &principal, &["integrator", "agent"], || {
                drivers::bacnet::remap_bacnet_device_value(&parse_json_body_or_empty(&body))
            })
        }
        ("DELETE", "/api/bacnet/driver/registry") => {
            require_role_lazy(&mut stream, &principal, &["integrator", "agent"], || {
                drivers::bacnet::clear_bacnet_registry_value()
            })
        }
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
            drivers::bacnet::overrides_csv(),
            "bacnet_overrides_export.csv",
        ),
        ("GET", "/api/bacnet/overrides/export/p8") => require_role_csv(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            drivers::bacnet::priority8_csv(),
            "bacnet_priority8_overrides.csv",
        ),
        ("GET", "/api/bacnet/overrides/export/non-p8") => require_role_csv(
            &mut stream,
            &principal,
            &["operator", "integrator", "agent"],
            drivers::bacnet::non_priority8_csv(),
            "bacnet_non_priority8_overrides.csv",
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
                json_response(&mut stream, drivers::bacnet::write_property_value(&value))
            } else {
                audit::log_event(
                    "forbidden",
                    json!({"route": route_path, "role": principal.role.clone()}),
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
        ("GET", "/api/modbus/poll/status") => {
            let body = drivers::modbus::poll_status_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/modbus/driver/tree") => {
            let body = drivers::modbus::driver_tree_json();
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
            raw_json(&mut stream, &drivers::json_api::sources_json())
        }
        ("GET", "/api/json-api/poll/status") => {
            let body = drivers::json_api::poll_status_json();
            raw_json(&mut stream, &body)
        }
        ("GET", "/api/json-api/driver/tree") => {
            let body = drivers::json_api::driver_tree_json();
            raw_json(&mut stream, &body)
        }
        ("POST", "/api/json-api/poll-once") => {
            require_role(&mut stream, &principal, &["integrator", "agent"], {
                let payload = serde_json::from_str::<Value>(&body).unwrap_or(json!({}));
                if let Some(url) = payload.get("url").and_then(|v| v.as_str()) {
                    drivers::json_api::poll_url(url)
                } else {
                    drivers::json_api::poll_once_value(&payload)
                }
            })
        }
        ("POST", "/api/json-api/refresh") => {
            require_role_lazy(&mut stream, &principal, &["integrator", "agent"], || {
                let payload = serde_json::from_str::<Value>(&body).unwrap_or(json!({}));
                drivers::json_api::refresh_point(&payload)
            })
        }
        ("POST", "/api/json-api/register") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(drivers::json_api::register_json()).unwrap(),
        ),
        ("POST", "/api/json-api/request") => {
            require_role_lazy(&mut stream, &principal, &["integrator", "agent"], || {
                let payload = serde_json::from_str::<Value>(&body).unwrap_or(json!({}));
                drivers::json_api::http_request(&payload)
            })
        }
        ("POST", "/api/json-api/read_and_store") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            drivers::json_api::read_and_store(
                &serde_json::from_str::<Value>(&body).unwrap_or(json!({})),
            ),
        ),
        ("PATCH", "/api/json-api/endpoint/poll") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            drivers::json_api::patch_endpoint_poll(
                &serde_json::from_str::<Value>(&body).unwrap_or(json!({})),
            ),
        ),
        ("POST", "/api/json-api/poll/once") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            drivers::json_api::poll_all_saved(),
        ),
        ("GET", "/api/timeseries/sites") => json_response(&mut stream, timeseries::sites_json()),
        ("GET", "/api/timeseries/series") => {
            let site = query_param(&path, "site_id").unwrap_or_default();
            json_response(&mut stream, timeseries::series_json(&site))
        }
        ("GET", "/api/timeseries/readings") => {
            let params = query_params_map(&path);
            json_response(&mut stream, timeseries::readings_json(&params))
        }
        ("GET", p) if p.starts_with("/api/timeseries/export.csv") => {
            let params = query_params_map(&path);
            match timeseries::export_csv(&params) {
                Ok(csv) => csv_attachment_response(&mut stream, &csv, "openfdd_timeseries.csv"),
                Err(err) => json_response(&mut stream, json!({"ok": false, "error": err})),
            }
        }
        ("GET", "/api/rules/saved") => {
            let rules_body: Value = serde_json::from_str(&fdd::wires::api::list_rules_json())
                .unwrap_or(json!({"rules": []}));
            json_response(
                &mut stream,
                json!({"ok": true, "rules": rules_body.get("rules").cloned().unwrap_or(json!([]))}),
            )
        }
        ("GET", "/api/historian/validation/status") => {
            json_response(&mut stream, historian::store::status_json())
        }
        ("GET", "/api/validation/audit") => {
            json_response(&mut stream, validation::audit_status_json())
        }
        ("GET", "/api/control/status") => raw_json(&mut stream, control::cdl::status_json()),
        ("POST", "/api/control/simulate") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(control::cdl::dry_run_json()).unwrap(),
        ),
        ("POST", "/api/control/dry-run") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            serde_json::from_str::<Value>(control::cdl::dry_run_json()).unwrap(),
        ),
        ("POST", "/api/reports/rcx/plan") => json_response(
            &mut stream,
            json!({"ok": true, "sections": ["executive_summary", "faults", "overrides", "energy_opportunities", "trend_plots"]}),
        ),
        ("GET", "/api/reports/templates") => require_role(
            &mut stream,
            &principal,
            READ_EXPORT_ROLES,
            reports::templates(),
        ),
        ("POST", "/api/reports/draft") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            reports::create_draft(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/reports") => require_role(
            &mut stream,
            &principal,
            READ_EXPORT_ROLES,
            reports::list_reports(),
        ),
        ("POST", "/api/reports/from-validation-run") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            reports::from_validation_run(&parse_json_body_or_empty(&body)),
        ),
        ("POST", "/api/reports/from-fdd-sql-run") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            reports::from_fdd_sql_run(&parse_json_body_or_empty(&body)),
        ),
        ("GET", "/api/reports/rcx/list") => require_role(
            &mut stream,
            &principal,
            READ_EXPORT_ROLES,
            reports::list_rcx_reports(),
        ),
        ("POST", "/api/reports/rcx/generate") => require_role(
            &mut stream,
            &principal,
            &["integrator", "agent"],
            reports::generate_rcx(&parse_json_body_or_empty(&body)),
        ),
        _ => {
            if let Some(resp) =
                handle_reports_dynamic(&mut stream, &principal, method.as_str(), &path, &body)
            {
                return resp;
            }
            if let Some(resp) =
                handle_faults_dynamic(&mut stream, &principal, method.as_str(), &path)
            {
                return resp;
            }
            if let Some(resp) =
                handle_data_management_dynamic(&mut stream, &principal, method.as_str(), &path)
            {
                return resp;
            }
            if let Some(resp) =
                handle_import_job_dynamic(&mut stream, &principal, method.as_str(), &path, &body)
            {
                return resp;
            }
            if let Some(resp) =
                handle_csv_ingest_dynamic(&mut stream, &principal, method.as_str(), &path)
            {
                return resp;
            }
            if let Some(resp) = handle_model_dynamic(&mut stream, method.as_str(), &path) {
                return resp;
            }
            if let Some(resp) =
                handle_json_api_dynamic(&mut stream, &principal, method.as_str(), &path)
            {
                return resp;
            }
            if method == "GET" && route_path.starts_with("/api/bacnet/jobs/") {
                let job_id = route_path.trim_start_matches("/api/bacnet/jobs/");
                return json_response(&mut stream, drivers::bacnet::job_status_json(job_id));
            }
            if let Some(resp) = handle_fdd_wires_dynamic(
                &mut stream,
                &principal,
                method.as_str(),
                &route_path,
                &body,
            ) {
                resp
            } else {
                status_json(
                    &mut stream,
                    "404 Not Found",
                    json!({"ok": false, "error": "unknown endpoint"}),
                )
            }
        }
    }
}

fn parse_json_body(body: &str) -> Result<Value, String> {
    if body.trim().is_empty() {
        Ok(json!({}))
    } else {
        serde_json::from_str(body).map_err(|e| format!("invalid JSON: {e}"))
    }
}

fn parse_json_body_or_empty(body: &str) -> Value {
    parse_json_body(body).unwrap_or_else(|_| json!({}))
}

fn site_scope_param(path: &str) -> String {
    model::scope::resolve_site_id(query_param(path, "site_id").as_deref())
        .unwrap_or_else(fdd::wires::persistence::default_site_id)
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

fn query_params_map(path: &str) -> std::collections::HashMap<String, String> {
    let mut out = std::collections::HashMap::new();
    if let Some(qs) = path.split('?').nth(1) {
        for pair in qs.split('&') {
            let mut parts = pair.splitn(2, '=');
            if let (Some(k), Some(v)) = (parts.next(), parts.next()) {
                out.insert(k.to_string(), v.to_string());
            }
        }
    }
    out
}

fn path_parts(path: &str) -> Vec<&str> {
    let route = path.split('?').next().unwrap_or(path);
    route.trim_matches('/').split('/').collect()
}

fn handle_model_dynamic(
    stream: &mut TcpStream,
    method: &str,
    path: &str,
) -> Option<std::io::Result<()>> {
    if method != "GET" {
        return None;
    }
    let prefix = "/api/model/sites/";
    let suffix = "/equipment";
    if !path.starts_with(prefix) || !path.ends_with(suffix) {
        return None;
    }
    let site_id = path
        .trim_start_matches(prefix)
        .trim_end_matches(suffix)
        .trim();
    if site_id.is_empty() {
        return Some(status_json(
            stream,
            "400 Bad Request",
            json!({"ok": false, "error": "site_id required"}),
        ));
    }
    Some(json_response(stream, model::query::list_equipment(site_id)))
}

fn handle_json_api_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
) -> Option<std::io::Result<()>> {
    let prefix = "/api/json-api/endpoint/";
    if !path.starts_with(prefix) {
        return None;
    }
    let point_id = path.trim_start_matches(prefix).trim();
    if point_id.is_empty() || point_id.contains('/') {
        return None;
    }
    match method {
        "DELETE" => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            drivers::json_api::delete_endpoint(point_id),
        )),
        _ => None,
    }
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
            let mut payload = parse_json_body_or_empty(body);
            payload["rule_id"] = json!(rule_id);
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::save_rule(&payload, &principal.sub),
            ))
        }
        ("PATCH", ["api", "fdd-rules", rule_id]) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            fdd::datafusion_sql::patch_rule_response(
                rule_id,
                &parse_json_body_or_empty(body),
                &principal.sub,
            ),
        )),
        ("PATCH", ["api", "rules", rule_id]) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            fdd::datafusion_sql::patch_rule_response(
                rule_id,
                &parse_json_body_or_empty(body),
                &principal.sub,
            ),
        )),
        ("POST", ["api", "fdd-rules", rule_id, "validate-sql"]) => {
            let mut payload = parse_json_body_or_empty(body);
            payload["rule_id"] = json!(rule_id);
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::validate_rule_sql(&payload),
            ))
        }
        ("POST", ["api", "fdd-rules", rule_id, "test-sql"]) => {
            let mut payload = parse_json_body_or_empty(body);
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
            let site = site_scope_param(path);
            Some(raw_json(
                stream,
                &fdd::wires::api::get_graph(&site, graph_id),
            ))
        }
        ("PUT", ["api", "fdd-wires", "graphs", graph_id]) => {
            let site = site_scope_param(path);
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::update_graph(
                    &site,
                    graph_id,
                    &parse_json_body_or_empty(body),
                    &principal.sub,
                ),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "validate"]) => {
            let site = site_scope_param(path);
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::validate_graph(&site, graph_id),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "test"]) => {
            let site = site_scope_param(path);
            Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                fdd::wires::api::test_graph(&site, graph_id),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "approve"]) => {
            let site = site_scope_param(path);
            Some(require_role(
                stream,
                principal,
                &["integrator"],
                fdd::wires::api::approve_graph(&site, graph_id, &principal.sub, &principal.role),
            ))
        }
        ("POST", ["api", "fdd-wires", "graphs", graph_id, "activate"]) => {
            let site = site_scope_param(path);
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

fn handle_faults_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
) -> Option<std::io::Result<()>> {
    let route = path.split('?').next().unwrap_or(path);
    let prefix = "/api/faults/";
    if !route.starts_with(prefix) {
        return None;
    }
    let tail = route.trim_start_matches(prefix);
    if tail.ends_with("/clear") && method == "POST" {
        let fault_id = tail.trim_end_matches("/clear").trim_end_matches('/');
        if fault_id.is_empty() {
            return Some(status_json(
                stream,
                "400 Bad Request",
                json!({"ok": false, "error": "fault_id required"}),
            ));
        }
        return Some(require_role(
            stream,
            principal,
            &["operator", "integrator", "agent"],
            faults::clear_fault(fault_id, &principal.sub),
        ));
    }
    if method != "GET" {
        return None;
    }
    if tail.is_empty()
        || tail.contains('/')
        || matches!(
            tail,
            "status" | "summary" | "export.csv" | "catalog" | "tree" | "applicable"
        )
    {
        return None;
    }
    Some(require_role(
        stream,
        principal,
        &["operator", "integrator", "agent"],
        faults::get_fault(tail),
    ))
}

fn handle_reports_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
    body: &str,
) -> Option<std::io::Result<()>> {
    let parts = path_parts(path);
    if parts.len() < 3 || parts[0] != "api" || parts[1] != "reports" {
        return None;
    }
    if parts[2] == "templates" || parts[2] == "draft" || parts[2] == "rcx" {
        return None;
    }
    let report_id = reports::safe_report_id(parts[2])?;
    if parts.len() == 3 {
        return match method {
            "GET" => Some(require_role(
                stream,
                principal,
                READ_EXPORT_ROLES,
                reports::get_report(&report_id),
            )),
            "PATCH" => Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                reports::patch_report(&report_id, &parse_json_body_or_empty(body)),
            )),
            "DELETE" => Some(require_role(
                stream,
                principal,
                &["integrator", "agent"],
                reports::delete_report(&report_id),
            )),
            _ => None,
        };
    }
    match (method, parts.get(3).copied(), parts.get(4).copied()) {
        ("GET", Some("data"), None) => Some(require_role(
            stream,
            principal,
            READ_EXPORT_ROLES,
            reports::report_data(&report_id),
        )),
        ("GET", Some("download.pdf"), None) => {
            let path = reports::download_path(&report_id, "pdf")?;
            Some(require_role_file(
                stream,
                principal,
                READ_EXPORT_ROLES,
                &path,
                "application/pdf",
                &format!("{report_id}.pdf"),
            ))
        }
        ("POST", Some("sections"), Some("reorder")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            reports::reorder_sections(&report_id, &parse_json_body_or_empty(body)),
        )),
        ("POST", Some("render"), Some("pdf")) => Some(require_role(
            stream,
            principal,
            &["integrator", "agent"],
            reports::render_pdf_bundle(&report_id),
        )),
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

fn header_value(headers: &[(String, String)], name: &str) -> String {
    headers
        .iter()
        .find(|(k, _)| k == name)
        .map(|(_, v)| v.clone())
        .unwrap_or_default()
}

fn handle_csv_ingest_dynamic(
    stream: &mut TcpStream,
    principal: &Principal,
    method: &str,
    path: &str,
) -> Option<std::io::Result<()>> {
    let parts = path_parts(path);
    if parts.len() >= 4
        && parts[0] == "api"
        && parts[1] == "csv"
        && parts[2] == "import"
        && parts[3] == "sessions"
    {
        if method != "GET" {
            return None;
        }
        if parts.len() == 4 {
            let limit = query_param(path, "limit")
                .and_then(|s| s.parse::<usize>().ok())
                .unwrap_or(20)
                .clamp(1, 100);
            return Some(require_role(
                stream,
                principal,
                &["integrator", "agent", "operator"],
                csv_ingest::list_sessions_handler(limit),
            ));
        }
        if parts.len() == 6 && parts[4] == "latest" && parts[5] == "planned" {
            return Some(require_role(
                stream,
                principal,
                &["integrator", "agent", "operator"],
                csv_ingest::latest_planned_session_handler(),
            ));
        }
        let session_id = parts[4];
        if session_id.contains("..") {
            return Some(json_response(
                stream,
                json!({"ok": false, "error": "invalid session id"}),
            ));
        }
        if parts.get(5) == Some(&"fusion-preview") {
            let limit =
                csv_ingest::fusion_preview_limit_from_query(query_param(path, "limit").as_deref());
            return Some(require_role(
                stream,
                principal,
                &["integrator", "agent", "operator"],
                csv_ingest::fusion_preview_handler(session_id, limit),
            ));
        }
        return Some(require_role(
            stream,
            principal,
            &["integrator", "agent", "operator"],
            csv_ingest::get_session_handler(session_id),
        ));
    }
    if parts.len() >= 4 && parts[0] == "api" && parts[1] == "datasets" {
        let dataset_id = parts[2];
        if dataset_id.contains("..") {
            return Some(json_response(
                stream,
                json!({"ok": false, "error": "invalid dataset id"}),
            ));
        }
        if method == "GET" && parts.get(3) == Some(&"preview") {
            let qs = query_string(path);
            let offset = query_param(path, "offset")
                .and_then(|s| s.parse::<u64>().ok())
                .unwrap_or(0);
            let limit = query_param(path, "limit")
                .and_then(|s| s.parse::<u64>().ok())
                .unwrap_or(100);
            let _ = qs;
            return Some(require_role(
                stream,
                principal,
                &["integrator", "agent", "operator"],
                csv_ingest::preview_dataset(dataset_id, offset, limit),
            ));
        }
    }
    None
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
            import::patch_options(job_id, &parse_json_body_or_empty(body)),
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

fn require_role_file(
    stream: &mut TcpStream,
    principal: &Principal,
    roles: &[&str],
    path: &Path,
    content_type: &str,
    filename: &str,
) -> std::io::Result<()> {
    if !role_allowed(principal, roles) {
        audit::log_event(
            "forbidden",
            json!({"role": principal.role.clone(), "required": roles, "file": filename}),
        );
        return status_json(
            stream,
            "403 Forbidden",
            json!({"ok": false, "error": "insufficient role", "role": principal.role}),
        );
    }
    let bytes = match fs::read(path) {
        Ok(b) => b,
        Err(_) => {
            return status_json(
                stream,
                "404 Not Found",
                json!({"ok": false, "error": "file not found"}),
            );
        }
    };
    file_attachment_response(stream, &bytes, content_type, filename)
}

fn file_attachment_response(
    stream: &mut TcpStream,
    body: &[u8],
    content_type: &str,
    filename: &str,
) -> std::io::Result<()> {
    let headers = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Disposition: attachment; filename=\"{filename}\"\r\n{sec}{cors}Content-Length: {len}\r\nConnection: close\r\n\r\n",
        sec = security_headers(content_type, false),
        cors = cors_origin(),
        len = body.len(),
        filename = filename
    );
    stream.write_all(headers.as_bytes())?;
    stream.write_all(body)
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

fn request_path_from_buf(buf: &[u8]) -> String {
    let header_end = buf
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .unwrap_or(buf.len());
    let first = buf
        .get(..header_end.min(buf.len()))
        .and_then(|h| h.split(|&b| b == b'\n').next())
        .and_then(|line| {
            let line = if line.ends_with(b"\r") {
                &line[..line.len().saturating_sub(1)]
            } else {
                line
            };
            std::str::from_utf8(line).ok()
        })
        .unwrap_or("");
    first
        .split_whitespace()
        .nth(1)
        .unwrap_or("/")
        .split('?')
        .next()
        .unwrap_or("/")
        .to_string()
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
    let route_path = request_path_from_buf(&buf);
    let max_body = max_body_bytes_for_path(&route_path);
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
    let _ = stream.set_read_timeout(Some(Duration::from_secs(read_timeout_secs_for_path(
        &route_path,
    ))));
    if content_length > max_body {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("request body too large (max {max_body} bytes for {route_path})"),
        ));
    }
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

fn require_role_lazy<F: FnOnce() -> Value>(
    stream: &mut TcpStream,
    principal: &Principal,
    roles: &[&str],
    body_fn: F,
) -> std::io::Result<()> {
    if role_allowed(principal, roles) {
        json_response(stream, body_fn())
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
            {"name":"bacnet.driver_remap","method":"PATCH","path":"/api/bacnet/driver/device/remap","requires":"integrator|agent"},
            {"name":"bacnet.driver_registry_clear","method":"DELETE","path":"/api/bacnet/driver/registry","requires":"integrator|agent"},
            {"name":"modbus.points","method":"GET","path":"/api/modbus/points","requires":"JWT"},
            {"name":"modbus.scan","method":"POST","path":"/api/modbus/scan","requires":"integrator|agent"},
            {"name":"json_api.sources","method":"GET","path":"/api/json-api/sources","requires":"JWT"},
            {"name":"json_api.register","method":"POST","path":"/api/json-api/register","requires":"integrator|agent"},
            {"name":"json_api.poll_once","method":"POST","path":"/api/json-api/poll-once","requires":"integrator|agent"},
            {"name":"haystack.config","method":"GET","path":"/api/haystack/config","requires":"JWT"},
            {"name":"haystack.config_save","method":"POST","path":"/api/haystack/config","requires":"integrator|agent"},
            {"name":"haystack.status","method":"GET","path":"/api/haystack/status","requires":"JWT"},
            {"name":"haystack.test","method":"POST","path":"/api/haystack/test","requires":"JWT"},
            {"name":"haystack.about","method":"GET","path":"/api/haystack/about","requires":"JWT"},
            {"name":"haystack.ops","method":"GET","path":"/api/haystack/ops","requires":"JWT"},
            {"name":"haystack.nav","method":"POST","path":"/api/haystack/nav","requires":"JWT"},
            {"name":"haystack.read","method":"POST","path":"/api/haystack/read","requires":"JWT"},
            {"name":"haystack.write","method":"POST","path":"/api/haystack/write","requires":"integrator|agent"},
            {"name":"haystack.poll_once","method":"POST","path":"/api/haystack/poll-once","requires":"integrator|agent"},
            {"name":"haystack.import","method":"POST","path":"/api/haystack/import","requires":"integrator|agent"},
            {"name":"haystack.driver_tree","method":"GET","path":"/api/haystack/driver/tree","requires":"JWT"},
            {"name":"model.haystack","method":"GET","path":"/api/model/haystack","requires":"JWT"},
            {"name":"model.sources","method":"GET","path":"/api/model/sources","requires":"JWT"},
            {"name":"model.equipment","method":"GET","path":"/api/model/equipment","requires":"JWT"},
            {"name":"model.points","method":"GET","path":"/api/model/points","requires":"JWT"},
            {"name":"model.import","method":"POST","path":"/api/model/haystack/import","requires":"integrator|agent"},
            {"name":"model.assignments","method":"GET","path":"/api/model/assignments","requires":"JWT"},
            {"name":"model.assignments_save","method":"POST","path":"/api/model/assignments/save","requires":"integrator|agent"},
            {"name":"model.sparql_catalog","method":"GET","path":"/api/model/sparql/predefined","requires":"JWT"},
            {"name":"model.sparql","method":"POST","path":"/api/model/sparql","requires":"JWT"},
            {"name":"model.resolve","method":"POST","path":"/api/model/assignments/resolve","requires":"JWT"},
            {"name":"control.cdl_bindings","method":"GET","path":"/api/control/cdl/bindings","requires":"JWT"},
            {"name":"control.cdl_bindings_save","method":"POST","path":"/api/control/cdl/bindings/save","requires":"integrator|agent"},
            {"name":"algorithms.run","method":"POST","path":"/api/algorithms/run","requires":"integrator|agent"},
            {"name":"fdd.run","method":"POST","path":"/api/fdd/run","requires":"integrator|agent"},
            {"name":"fdd.wires.graphs","method":"GET","path":"/api/fdd-wires/graphs","requires":"JWT"},
            {"name":"fdd.wires.propose","method":"POST","path":"/api/fdd-wires/propose-assignments","requires":"integrator|agent"},
            {"name":"csv.import.preview","method":"POST","path":"/api/csv/import/preview","requires":"integrator|agent"},
            {"name":"csv.import.plan","method":"POST","path":"/api/csv/import/plan","requires":"integrator|agent"},
            {"name":"csv.import.preflight","method":"POST","path":"/api/csv/import/preflight","requires":"integrator|agent"},
            {"name":"csv.import.execute","method":"POST","path":"/api/csv/import/execute","requires":"integrator|agent"},
            {"name":"ingest.contract","method":"GET","path":"/api/ingest/contract","public":true},
            {"name":"csv.workbench.quality","method":"POST","path":"/api/csv-workbench/quality","requires":"integrator|agent"},
            {"name":"model.commissioning_export","method":"GET","path":"/api/model/commissioning-export","requires":"JWT"},
            {"name":"model.commissioning_import","method":"POST","path":"/api/model/commissioning-import","requires":"integrator|agent"},
            {"name":"reports.from_fdd_sql_run","method":"POST","path":"/api/reports/from-fdd-sql-run","requires":"integrator|agent"},
            {"name":"fdd.rules.save","method":"POST","path":"/api/fdd-rules","requires":"integrator"},
            {"name":"fdd.rules.test_sql","method":"POST","path":"/api/fdd-rules/{id}/test-sql","requires":"integrator|agent"},
            {"name":"historian.query","method":"POST","path":"/api/historian/query","requires":"JWT"},
            {"name":"reports.templates","method":"GET","path":"/api/reports/templates","requires":"JWT"},
            {"name":"reports.draft","method":"POST","path":"/api/reports/draft","requires":"integrator|agent"},
            {"name":"reports.render_pdf","method":"POST","path":"/api/reports/{id}/render/pdf","requires":"integrator|agent"},
            {"name":"reports.download_pdf","method":"GET","path":"/api/reports/{id}/download.pdf","requires":"JWT"},
            {"name":"reports.rcx_plan","method":"POST","path":"/api/reports/rcx/plan","requires":"JWT"},
            {"name":"fdd.rules.list","method":"GET","path":"/api/fdd-rules","requires":"JWT"},
            {"name":"fdd.rules.activate","method":"POST","path":"/api/fdd-rules/{id}/activate","requires":"integrator"},
            {"name":"rules.batch","method":"POST","path":"/api/rules/batch","requires":"integrator|agent"},
            {"name":"timeseries.series","method":"GET","path":"/api/timeseries/series","requires":"JWT"},
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

fn building_checkin() -> Value {
    dashboard::building_status()
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
        "HTTP/1.1 204 No Content\r\n{origin}Access-Control-Allow-Methods: GET,POST,PUT,PATCH,DELETE,OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type, Authorization\r\nContent-Length: 0\r\n\r\n"
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
    h.push_str("X-Frame-Options: DENY\r\n");
    h.push_str("Cross-Origin-Opener-Policy: same-origin\r\n");
    h.push_str("Cross-Origin-Resource-Policy: same-origin\r\n");
    h.push_str("Permissions-Policy: geolocation=(), microphone=(), camera=()\r\n");
    h.push_str(
        "Content-Security-Policy: default-src 'self'; script-src 'self' https://unpkg.com https://cdn.plot.ly; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'self'\r\n",
    );
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
                "svg" => "image/svg+xml",
                "ico" => "image/x-icon",
                "png" => "image/png",
                _ => "application/octet-stream",
            };
            response(stream, "200 OK", ctype, &bytes)
        }
        Err(_) => {
            // React SPA: unknown paths without a file extension serve index.html.
            if !rel.contains('.') {
                let index = PathBuf::from(frontend).join("index.html");
                if let Ok(bytes) = fs::read(&index) {
                    return response(stream, "200 OK", "text/html; charset=utf-8", &bytes);
                }
            }
            response(stream, "404 Not Found", "text/plain", b"not found")
        }
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
