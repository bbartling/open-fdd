//! P1-M2-01 — browser/API contract conventions (error envelope, request IDs).

use axum::{
    body::Body,
    http::{HeaderMap, HeaderName, HeaderValue, Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;
use serde_json::{json, Value};
use uuid::Uuid;

pub const CONTRACT_VERSION: &str = "openfdd.api.contract.v1";
pub const REQUEST_ID_HEADER: &str = "x-request-id";
/// Server-generated id; the `request_id` on audit events.
pub const SERVER_REQUEST_ID_HEADER: &str = "x-openfdd-server-request-id";

/// Compatibility policy: stable `/api/*` surface; additive fields only.
/// Breaking changes require a new `CONTRACT_VERSION` and React client bump.
pub const COMPATIBILITY_POLICY: &str = "additive_within_contract_version";

/// Public contract types for React clients; handlers adopt incrementally (P1-M2+).
#[allow(dead_code)]
#[derive(Debug, Clone, Serialize)]
pub struct ErrorBody {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<Value>,
    pub retryable: bool,
    pub request_id: String,
}

/// Public contract types for React clients; handlers adopt incrementally (P1-M2+).
#[allow(dead_code)]
#[derive(Debug, Clone, Serialize)]
pub struct ApiErrorEnvelope {
    pub error: ErrorBody,
}

impl ApiErrorEnvelope {
    #[allow(dead_code)]
    pub fn new(
        code: impl Into<String>,
        message: impl Into<String>,
        request_id: impl Into<String>,
        retryable: bool,
        details: Option<Value>,
    ) -> Self {
        Self {
            error: ErrorBody {
                code: code.into(),
                message: message.into(),
                details,
                retryable,
                request_id: request_id.into(),
            },
        }
    }
}

pub fn ensure_request_id(headers: &HeaderMap) -> String {
    headers
        .get(REQUEST_ID_HEADER)
        .and_then(|v| v.to_str().ok())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| Uuid::new_v4().to_string())
}

/// Axum middleware: ensure every response echoes `x-request-id`.
///
/// Central always generates its own id for audit records
/// ([`crate::audit::RequestContext`]) and returns it in
/// [`SERVER_REQUEST_ID_HEADER`]. A caller-supplied `x-request-id` is still
/// echoed for client correlation but is stored only as the bounded caller id.
pub async fn request_id_middleware(mut req: Request<Body>, next: Next) -> Response {
    let caller = req
        .headers()
        .get(REQUEST_ID_HEADER)
        .and_then(|v| v.to_str().ok())
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = crate::audit::RequestContext::new(
        caller.as_deref(),
        req.method().as_str(),
        req.uri().path(),
    )
    .with_untrusted_headers(req.headers());
    let server_id = ctx.server_id.clone();
    let rid = caller.unwrap_or_else(|| server_id.clone());
    req.headers_mut().insert(
        HeaderName::from_static(REQUEST_ID_HEADER),
        HeaderValue::from_str(&rid).unwrap_or_else(|_| HeaderValue::from_static("invalid")),
    );
    let mut res = crate::audit::with_request_context(ctx, next.run(req)).await;
    if res.headers().get(REQUEST_ID_HEADER).is_none() {
        if let Ok(hv) = HeaderValue::from_str(&rid) {
            res.headers_mut()
                .insert(HeaderName::from_static(REQUEST_ID_HEADER), hv);
        }
    }
    if let Ok(hv) = HeaderValue::from_str(&server_id) {
        res.headers_mut()
            .insert(HeaderName::from_static(SERVER_REQUEST_ID_HEADER), hv);
    }
    res
}

/// Stable error envelope helper; route handlers migrate onto this incrementally.
#[allow(dead_code)]
pub fn json_error(
    status: StatusCode,
    code: &str,
    message: &str,
    request_id: &str,
    retryable: bool,
) -> Response {
    (
        status,
        Json(ApiErrorEnvelope::new(
            code, message, request_id, retryable, None,
        )),
    )
        .into_response()
}

pub fn contract_capabilities_extra() -> Value {
    json!({
        "contract_version": CONTRACT_VERSION,
        "compatibility": COMPATIBILITY_POLICY,
        "timestamps": "RFC3339_with_offset",
        "missing_float": "null",
        "revision_header": "expected_meta_revision (jobs)",
        "idempotency_header": "idempotency-key",
        "request_id_header": REQUEST_ID_HEADER,
        "server_request_id_header": SERVER_REQUEST_ID_HEADER,
        "error_envelope": "error.{code,message,details?,retryable,request_id}",
        "job_run_status": ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"],
        "async_ops": "poll via /api/fdd/status and /api/jobs/{id}/runs/{run_id}",
        "react_ui_flag": "OPENFDD_REACT_UI (default off)"
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_envelope_serializes_stable_shape() {
        let env = ApiErrorEnvelope::new(
            "mapping.role_missing",
            "SAT role not mapped",
            "req-1",
            false,
            Some(json!({"role": "SAT"})),
        );
        let v = serde_json::to_value(&env).unwrap();
        assert_eq!(v["error"]["code"], "mapping.role_missing");
        assert_eq!(v["error"]["request_id"], "req-1");
        assert_eq!(v["error"]["retryable"], false);
        assert!(v["error"]["details"].is_object());
    }

    #[test]
    fn contract_version_is_nonempty() {
        assert!(CONTRACT_VERSION.starts_with("openfdd.api.contract."));
    }

    #[test]
    fn json_error_returns_envelope_status() {
        let res = json_error(
            StatusCode::BAD_REQUEST,
            "validation.failed",
            "bad input",
            "req-2",
            false,
        );
        assert_eq!(res.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE while the middleware stamps Actions"
    )]
    async fn server_request_id_is_shared_with_actions_and_the_audit_record() {
        use tower::ServiceExt;

        let _env = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let audit_path = workspace.path().join("security_audit.jsonl");
        struct EnvRestore {
            audit: Option<String>,
            qa: Option<String>,
        }
        impl Drop for EnvRestore {
            fn drop(&mut self) {
                match self.audit.take() {
                    Some(value) => std::env::set_var("OPENFDD_AUDIT_LOG_PATH", value),
                    None => std::env::remove_var("OPENFDD_AUDIT_LOG_PATH"),
                }
                match self.qa.take() {
                    Some(value) => std::env::set_var("OPENFDD_QA_RUN_MANIFEST", value),
                    None => std::env::remove_var("OPENFDD_QA_RUN_MANIFEST"),
                }
            }
        }
        let _restore = EnvRestore {
            audit: std::env::var("OPENFDD_AUDIT_LOG_PATH").ok(),
            qa: std::env::var("OPENFDD_QA_RUN_MANIFEST").ok(),
        };
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", &audit_path);
        std::env::remove_var("OPENFDD_QA_RUN_MANIFEST");

        let app = axum::Router::new()
            .route(
                "/api/export",
                axum::routing::post(|| async {
                    let action_id = crate::actions::start_action("csv_export", "CSV export", None)
                        .expect("action");
                    let mut audit =
                        crate::audit::AuditEvent::new(crate::audit::AuditAction::CsvExport);
                    audit
                        .actor("operator")
                        .outcome(crate::audit::Outcome::Ok)
                        .status(StatusCode::CREATED)
                        .emit();
                    axum::Json(serde_json::json!({ "action_id": action_id }))
                }),
            )
            .layer(axum::middleware::from_fn(request_id_middleware));
        let response = app
            .oneshot(
                Request::post("/api/export")
                    .header(REQUEST_ID_HEADER, "client-label")
                    .header("x-openfdd-qa-run", "client-qa")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        let server = response
            .headers()
            .get(SERVER_REQUEST_ID_HEADER)
            .and_then(|value| value.to_str().ok())
            .expect("server request id")
            .to_string();
        let echoed = response
            .headers()
            .get(REQUEST_ID_HEADER)
            .and_then(|value| value.to_str().ok())
            .expect("echoed caller id");
        assert_eq!(echoed, "client-label");
        assert_ne!(server, "client-label");

        open_fdd_edge_prototype::auth::audit::flush_sink();
        let actions = std::fs::read_to_string(workspace.path().join("data/actions/log.jsonl"))
            .expect("actions log");
        let row: serde_json::Value =
            serde_json::from_str(actions.lines().next().expect("action row")).expect("action json");
        assert_eq!(row["request_id"], server);
        assert_eq!(row["kind"], "csv_export");

        let audit = std::fs::read_to_string(&audit_path).expect("audit log");
        let event: serde_json::Value =
            serde_json::from_str(audit.lines().next().expect("audit row")).expect("audit json");
        assert_eq!(event["event"], "csv.export");
        assert_eq!(event["detail"]["request_id"], server);
        assert_eq!(event["detail"]["caller_request_id"], "client-label");
        assert_eq!(event["detail"]["correlation"]["server_request_id"], server);
        assert!(event["detail"]["qa_run"].is_null());
        assert_eq!(
            event["detail"]["untrusted_labels"]["claimed_qa_run"],
            "client-qa"
        );
    }
}
