use reqwest::blocking::{multipart, Client};
use serde_json::{json, Value};
use std::env;
use std::path::Path;
use std::time::Duration;

pub struct BridgeClient {
    http: Client,
    http_long: Client,
    base: String,
    token: Option<String>,
}

impl BridgeClient {
    pub fn from_env() -> Self {
        let base = env::var("OPENFDD_API_BASE").unwrap_or_else(|_| "http://127.0.0.1:8080".into());
        let token = env::var("OPENFDD_MCP_TOKEN")
            .ok()
            .filter(|t| !t.is_empty())
            .or_else(|| env::var("OPENFDD_INTEGRATOR_TOKEN").ok());
        let timeout_secs = env::var("OPENFDD_MCP_TIMEOUT_SECS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(120);
        let long_secs = env::var("OPENFDD_MCP_CSV_TIMEOUT_SECS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(600);
        let http = Client::builder()
            .timeout(Duration::from_secs(timeout_secs))
            .build()
            .expect("reqwest client");
        let http_long = Client::builder()
            .timeout(Duration::from_secs(long_secs))
            .build()
            .expect("reqwest long client");
        Self {
            http,
            http_long,
            base,
            token,
        }
    }

    pub fn get(&self, path: &str) -> Result<Value, String> {
        self.request(self.http.get(self.url(path)))
    }

    pub fn post(&self, path: &str, body: &Value) -> Result<Value, String> {
        self.request(self.http.post(self.url(path)).json(body))
    }

    pub fn patch(&self, path: &str, body: &Value) -> Result<Value, String> {
        self.request(self.http.patch(self.url(path)).json(body))
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base.trim_end_matches('/'), path)
    }

    fn auth(&self, req: reqwest::blocking::RequestBuilder) -> reqwest::blocking::RequestBuilder {
        if let Some(t) = &self.token {
            req.header("Authorization", format!("Bearer {t}"))
        } else {
            req
        }
    }

    fn request(&self, req: reqwest::blocking::RequestBuilder) -> Result<Value, String> {
        self.auth(req)
            .send()
            .map_err(|e| e.to_string())?
            .json()
            .map_err(|e| e.to_string())
    }

    pub fn csv_import_preview(&self, args: &Value) -> Result<Value, String> {
        let files = args.get("files").and_then(|v| v.as_array()).ok_or(
            "files array required — each entry: {filename, path} or {filename, content_base64}",
        )?;
        if files.is_empty() {
            return Err("files array is empty".into());
        }
        let session_id = args.get("session_id").and_then(|v| v.as_str());
        let mut total_bytes = 0usize;
        let mut staged: Vec<(String, Vec<u8>)> = Vec::new();
        for f in files {
            let name = f
                .get("filename")
                .and_then(|v| v.as_str())
                .unwrap_or("upload.csv");
            let raw = if let Some(path) = f.get("path").and_then(|v| v.as_str()) {
                read_local_csv_path(path)?
            } else if let Some(b64) = f.get("content_base64").and_then(|v| v.as_str()) {
                use base64::Engine;
                base64::engine::general_purpose::STANDARD
                    .decode(b64)
                    .map_err(|e| e.to_string())?
            } else {
                return Err(format!(
                    "file {name}: provide path (host filesystem) or content_base64"
                ));
            };
            total_bytes += raw.len();
            staged.push((name.to_string(), raw));
        }
        if total_bytes <= 900_000 {
            let payload = json!({
                "session_id": session_id,
                "files": staged.iter().map(|(name, raw)| {
                    use base64::Engine;
                    json!({
                        "filename": name,
                        "content_base64": base64::engine::general_purpose::STANDARD.encode(raw)
                    })
                }).collect::<Vec<_>>()
            });
            return self.post("/api/csv/import/preview", &payload);
        }
        let mut form = multipart::Form::new();
        if let Some(sid) = session_id {
            form = form.text("session_id", sid.to_string());
        }
        for (name, raw) in staged {
            let part = multipart::Part::bytes(raw).file_name(name.clone());
            form = form.part("file", part);
        }
        let req = self
            .http_long
            .post(self.url("/api/csv/import/preview"))
            .multipart(form);
        self.auth(req)
            .send()
            .map_err(|e| e.to_string())?
            .json()
            .map_err(|e| e.to_string())
    }

    pub fn csv_import_plan(&self, args: &Value) -> Result<Value, String> {
        let session_id = args
            .get("session_id")
            .and_then(|v| v.as_str())
            .ok_or("session_id required")?;
        let plan = args.get("plan").cloned().unwrap_or_else(|| args.clone());
        let body = if plan.get("mode").is_some() || plan.get("files").is_some() {
            json!({ "session_id": session_id, "plan": plan })
        } else {
            args.clone()
        };
        self.post("/api/csv/import/plan", &body)
    }

    pub fn csv_import_preflight(&self, args: &Value) -> Result<Value, String> {
        let session_id = args
            .get("session_id")
            .and_then(|v| v.as_str())
            .ok_or("session_id required")?;
        let mut body = json!({ "session_id": session_id });
        if let Some(plan) = args.get("plan") {
            body["plan"] = plan.clone();
        }
        self.post("/api/csv/import/preflight", &body)
    }

    pub fn ingest_contract(&self) -> Result<Value, String> {
        self.get("/api/ingest/contract")
    }

    pub fn commissioning_export(&self) -> Result<Value, String> {
        self.get("/api/model/commissioning-export")
    }

    pub fn commissioning_import(&self, args: &Value) -> Result<Value, String> {
        let payload = args.get("payload").cloned().unwrap_or_else(|| args.clone());
        self.post(
            "/api/model/commissioning-import",
            &json!({ "payload": payload }),
        )
    }

    pub fn rules_batch(&self) -> Result<Value, String> {
        self.post("/api/rules/batch", &json!({}))
    }

    pub fn fdd_rules_save(&self, args: &Value) -> Result<Value, String> {
        self.post("/api/fdd-rules", args)
    }

    pub fn fdd_rules_activate(&self, rule_id: &str) -> Result<Value, String> {
        self.post(&format!("/api/fdd-rules/{rule_id}/activate"), &json!({}))
    }

    pub fn reports_from_fdd_sql_run(&self, args: &Value) -> Result<Value, String> {
        self.post("/api/reports/from-fdd-sql-run", args)
    }

    pub fn csv_workbench_quality(&self, args: &Value) -> Result<Value, String> {
        self.post("/api/csv-workbench/quality", args)
    }

    pub fn integration_smoke(&self, args: &Value) -> Result<Value, String> {
        let mut steps: Vec<Value> = Vec::new();
        let mut agent_next: Vec<String> = Vec::new();

        let health = self.get("/api/health")?;
        steps.push(smoke_step(
            "health",
            health.get("ok").and_then(|v| v.as_bool()).unwrap_or(true),
            health,
        ));

        let stack = self
            .get("/api/health/stack")
            .unwrap_or_else(|e| json!({"ok": false, "error": e}));
        steps.push(smoke_step(
            "stack",
            stack.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
            stack,
        ));

        let contract = self
            .ingest_contract()
            .unwrap_or_else(|e| json!({"ok": false, "error": e}));
        steps.push(smoke_step(
            "ingest_contract",
            contract.get("ok").and_then(|v| v.as_bool()) == Some(true),
            contract,
        ));

        let mut session_id = args
            .get("session_id")
            .and_then(|v| v.as_str())
            .map(str::to_string);

        if session_id.is_none() {
            if let Some(dir) = args.get("import_dir").and_then(|v| v.as_str()) {
                match list_csv_files(dir) {
                    Ok(file_specs) if !file_specs.is_empty() => {
                        let preview = self.csv_import_preview(&json!({ "files": file_specs }))?;
                        session_id = preview
                            .get("session_id")
                            .and_then(|v| v.as_str())
                            .map(str::to_string);
                        steps.push(smoke_step(
                            "csv_preview",
                            preview.get("ok").and_then(|v| v.as_bool()) == Some(true),
                            preview,
                        ));
                    }
                    Ok(_) => steps.push(smoke_step(
                        "csv_preview",
                        false,
                        json!({"ok": false, "error": "import_dir has no .csv files"}),
                    )),
                    Err(e) => steps.push(smoke_step(
                        "csv_preview",
                        false,
                        json!({"ok": false, "error": e}),
                    )),
                }
            }
        }

        let mut preflight_pass = false;
        if let Some(sid) = session_id.as_deref() {
            let preflight = self.csv_import_preflight(&json!({ "session_id": sid }))?;
            let verdict = preflight
                .get("verdict")
                .and_then(|v| v.as_str())
                .unwrap_or("fail");
            preflight_pass = verdict == "pass";
            steps.push(smoke_step("preflight", preflight_pass, preflight.clone()));
            if !preflight_pass {
                if let Some(hints) = preflight
                    .get("validation")
                    .and_then(|v| v.get("agent_hints"))
                    .and_then(|v| v.as_array())
                {
                    for h in hints {
                        if let Some(s) = h.as_str() {
                            agent_next.push(s.to_string());
                        }
                    }
                }
                agent_next
                    .push("Clean data in workspace/agent-toolshed/ and re-run preflight".into());
            }

            if args.get("confirm").and_then(|v| v.as_bool()) == Some(true) && preflight_pass {
                let exec = self.post(
                    "/api/csv/import/execute",
                    &json!({ "session_id": sid, "confirm": true }),
                )?;
                steps.push(smoke_step(
                    "execute",
                    exec.get("ok").and_then(|v| v.as_bool()) == Some(true),
                    exec,
                ));
            }
        }

        if args.get("confirm").and_then(|v| v.as_bool()) == Some(true) {
            if let Some(bundle) = args.get("commissioning") {
                let imported = self.commissioning_import(bundle)?;
                steps.push(smoke_step(
                    "commissioning_import",
                    imported.get("ok").and_then(|v| v.as_bool()) == Some(true),
                    imported,
                ));
            }
            if args
                .get("run_fdd")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
            {
                let batch = self.rules_batch()?;
                steps.push(smoke_step(
                    "rules_batch",
                    batch.get("ok").and_then(|v| v.as_bool()) == Some(true),
                    batch,
                ));
            }
            if args
                .get("run_report")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
            {
                if let Some(report_body) = args.get("report") {
                    let report = self.reports_from_fdd_sql_run(report_body)?;
                    steps.push(smoke_step(
                        "reports_from_fdd_sql_run",
                        report.get("ok").and_then(|v| v.as_bool()) == Some(true),
                        report,
                    ));
                }
            }
        }

        let all_ok = steps
            .iter()
            .all(|s| s.get("ok").and_then(|v| v.as_bool()) == Some(true));
        Ok(json!({
            "ok": all_ok,
            "verdict": if all_ok { "pass" } else { "fail" },
            "session_id": session_id,
            "preflight_pass": preflight_pass,
            "steps": steps,
            "agent_next_actions": agent_next
        }))
    }

    pub fn historian_query(&self, args: &Value) -> Result<Value, String> {
        if args.as_object().map(|o| o.is_empty()).unwrap_or(true) {
            self.get("/api/historian/query")
        } else {
            self.post("/api/historian/query", args)
        }
    }

    pub fn fdd_rules_list(&self) -> Result<Value, String> {
        self.get("/api/fdd-rules")
    }

    pub fn fdd_rule_test_sql(&self, args: &Value) -> Result<Value, String> {
        let rule_id = args
            .get("rule_id")
            .and_then(|v| v.as_str())
            .ok_or("rule_id required")?;
        let mut body = args.clone();
        if let Some(obj) = body.as_object_mut() {
            obj.remove("rule_id");
        }
        self.post(&format!("/api/fdd-rules/{rule_id}/test-sql"), &body)
    }

    pub fn fdd_run(&self, args: &Value) -> Result<Value, String> {
        let mut body = args.clone();
        if let Some(obj) = body.as_object_mut() {
            obj.remove("confirm");
        }
        self.post("/api/fdd/run", &body)
    }

    pub fn model_assignments_save(&self, args: &Value) -> Result<Value, String> {
        self.post("/api/model/assignments/save", args)
    }

    pub fn reports_draft(&self, args: &Value) -> Result<Value, String> {
        let mut body = args.clone();
        if let Some(obj) = body.as_object_mut() {
            obj.remove("confirm");
        }
        self.post("/api/reports/draft", &body)
    }

    pub fn reports_patch(&self, args: &Value) -> Result<Value, String> {
        let report_id = args
            .get("report_id")
            .and_then(|v| v.as_str())
            .ok_or("report_id required")?;
        let mut body = args.clone();
        if let Some(obj) = body.as_object_mut() {
            obj.remove("report_id");
            obj.remove("confirm");
        }
        self.patch(&format!("/api/reports/{report_id}"), &body)
    }

    pub fn reports_render_pdf(&self, args: &Value) -> Result<Value, String> {
        let report_id = args
            .get("report_id")
            .and_then(|v| v.as_str())
            .ok_or("report_id required")?;
        self.post(&format!("/api/reports/{report_id}/render/pdf"), &json!({}))
    }

    pub fn site_update_dry_run(&self) -> Value {
        json!({
            "ok": true,
            "dry_run": true,
            "steps": [
                "tar -czf ~/openfdd-backups/latest/workspace-full.tgz workspace/",
                "OPENFDD_IMAGE_TAG=<tag> ./scripts/openfdd_stack_up.sh standalone",
                "./scripts/openfdd_health_check.sh",
                "./scripts/openfdd_drivers_validate.sh"
            ],
            "doc": "docs/quick-start/site-lifecycle.md",
            "note": "MCP does not execute site update — operator or bench agent runs scripts on host."
        })
    }

    pub fn ghcr_manifest_check(&self, args: &Value) -> Result<Value, String> {
        let health = self.get("/api/health")?;
        let running = health
            .get("image_tag")
            .or_else(|| health.get("version"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let expected = args
            .get("expected_tag")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or_else(|| env::var("OPENFDD_IMAGE_TAG").ok())
            .unwrap_or_default();
        Ok(json!({
            "ok": !expected.is_empty() && (running == expected || running == format!("v{expected}")),
            "running_tag": running,
            "expected_tag": expected,
            "git_sha": health.get("git_sha").cloned().unwrap_or(Value::Null),
            "git_sha_short": health.get("git_sha_short").cloned().unwrap_or(Value::Null),
            "image_ref": health.get("image_ref").cloned().unwrap_or(Value::Null),
            "doc": "scripts/openfdd_rust_check_ghcr_platform.sh"
        }))
    }

    pub fn bench_topology(&self) -> Value {
        if let Ok(path) = env::var("OPENFDD_BENCH_TOPOLOGY_FILE") {
            if let Ok(text) = std::fs::read_to_string(&path) {
                return serde_json::from_str(&text).unwrap_or_else(
                    |e| json!({"ok": false, "error": format!("invalid topology JSON: {e}")}),
                );
            }
        }
        json!({
            "ok": true,
            "note": "Set OPENFDD_BENCH_TOPOLOGY_FILE to a gitignored JSON file with bench IPs.",
            "doc": "docs/agent/bench-driver-setup-wsl-agent.md",
            "bridge": self.base,
            "commission_default": "http://127.0.0.1:9091"
        })
    }

    pub fn driver_status(&self) -> Value {
        let endpoints = [
            ("/api/health", "GET"),
            ("/api/haystack/status", "GET"),
            ("/api/modbus/commission/status", "GET"),
            ("/api/bacnet/commission/status", "GET"),
            ("/api/json-api/poll/status", "GET"),
        ];
        let mut out = serde_json::Map::new();
        for (path, method) in endpoints {
            let key = path.trim_start_matches("/api/").replace('/', "_");
            let result = if method == "GET" {
                self.get(path)
            } else {
                self.post(path, &json!({}))
            };
            out.insert(
                key,
                result.unwrap_or_else(|e| json!({"ok": false, "error": e})),
            );
        }
        json!({"ok": true, "drivers": out})
    }

    pub fn haystack_read(&self, args: &Value) -> Result<Value, String> {
        let body = if args.get("filter").is_some() {
            json!({ "filter": args["filter"] })
        } else if args.get("ids").is_some() {
            json!({ "ids": args["ids"] })
        } else {
            json!({ "filter": "point and cur" })
        };
        self.post("/api/haystack/read", &body)
    }

    pub fn bacnet_read(&self, args: &Value) -> Result<Value, String> {
        let commission =
            env::var("OPENFDD_COMMISSION_BASE").unwrap_or_else(|_| "http://127.0.0.1:9091".into());
        let point_id = args
            .get("point_id")
            .and_then(|v| v.as_str())
            .ok_or("point_id required")?;
        let url = format!("{}/api/bacnet/read", commission.trim_end_matches('/'));
        let mut req = self.http.post(&url).json(&json!({ "point_id": point_id }));
        if let Some(t) = &self.token {
            req = req.header("Authorization", format!("Bearer {t}"));
        }
        req.send()
            .map_err(|e| e.to_string())?
            .json()
            .map_err(|e| e.to_string())
    }
}

fn smoke_step(name: &str, ok: bool, detail: Value) -> Value {
    json!({ "name": name, "ok": ok, "detail": detail })
}

fn list_csv_files(dir: &str) -> Result<Vec<Value>, String> {
    if dir.contains("..") {
        return Err("path traversal (..) not allowed".into());
    }
    let p = Path::new(dir);
    if !p.is_dir() {
        return Err(format!("import_dir not found: {dir}"));
    }
    let mut out = Vec::new();
    for entry in std::fs::read_dir(p).map_err(|e| format!("read_dir {dir}: {e}"))? {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if path.is_file()
            && path
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| e.eq_ignore_ascii_case("csv"))
        {
            out.push(json!({
                "filename": path.file_name().and_then(|n| n.to_str()).unwrap_or("upload.csv"),
                "path": path.display().to_string()
            }));
        }
    }
    out.sort_by(|a, b| {
        a.get("filename")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .cmp(b.get("filename").and_then(|v| v.as_str()).unwrap_or(""))
    });
    Ok(out)
}

fn read_local_csv_path(path: &str) -> Result<Vec<u8>, String> {
    if path.contains("..") {
        return Err("path traversal (..) not allowed".into());
    }
    let p = Path::new(path);
    if !p.is_file() {
        return Err(format!("file not found: {path}"));
    }
    std::fs::read(p).map_err(|e| format!("read {path}: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_path_traversal() {
        assert!(read_local_csv_path("../etc/passwd").is_err());
    }
}
