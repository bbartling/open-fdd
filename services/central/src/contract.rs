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

/// Compatibility policy: stable `/api/*` surface; additive fields only.
/// Breaking changes require a new `CONTRACT_VERSION` and React client bump.
pub const COMPATIBILITY_POLICY: &str = "additive_within_contract_version";

#[derive(Debug, Clone, Serialize)]
pub struct ErrorBody {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<Value>,
    pub retryable: bool,
    pub request_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ApiErrorEnvelope {
    pub error: ErrorBody,
}

impl ApiErrorEnvelope {
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
pub async fn request_id_middleware(mut req: Request<Body>, next: Next) -> Response {
    let rid = ensure_request_id(req.headers());
    req.headers_mut().insert(
        HeaderName::from_static(REQUEST_ID_HEADER),
        HeaderValue::from_str(&rid).unwrap_or_else(|_| HeaderValue::from_static("invalid")),
    );
    let mut res = next.run(req).await;
    if res.headers().get(REQUEST_ID_HEADER).is_none() {
        if let Ok(hv) = HeaderValue::from_str(&rid) {
            res.headers_mut()
                .insert(HeaderName::from_static(REQUEST_ID_HEADER), hv);
        }
    }
    res
}

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
}
