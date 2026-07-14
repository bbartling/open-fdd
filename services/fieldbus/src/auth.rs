//! Bearer API-key auth middleware (mirrors `app/auth.py`).

use axum::{
    extract::Request,
    http::{header, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use subtle::ConstantTimeEq;

use crate::state::AppState;

pub fn api_key() -> String {
    for key in ["OPENFDD_FIELDBUS_API_KEY", "RUSTY_GATEWAY_API_KEY"] {
        if let Ok(v) = std::env::var(key) {
            let trimmed = v.trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }
    }
    String::new()
}

pub fn auth_path_exempt(path: &str) -> bool {
    if matches!(path, "/" | "/health" | "/api/health") {
        return true;
    }
    if matches!(path, "/docs" | "/redoc" | "/openapi.json") {
        return true;
    }
    path.starts_with("/docs/") || path.starts_with("/redoc/")
}

pub async fn auth_middleware(
    axum::extract::State(state): axum::extract::State<AppState>,
    request: Request,
    next: Next,
) -> Response {
    let Some(ref key) = state.api_key else {
        return next.run(request).await;
    };

    let path = request.uri().path().to_string();
    if auth_path_exempt(&path) {
        return next.run(request).await;
    }

    let auth = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !auth.starts_with("Bearer ") {
        return unauthorized("Missing or invalid Authorization header");
    }
    let token = auth[7..].trim();
    if token.as_bytes().ct_eq(key.as_bytes()).unwrap_u8() != 1 {
        return forbidden("Invalid API key");
    }
    next.run(request).await
}

fn unauthorized(detail: &str) -> Response {
    (StatusCode::UNAUTHORIZED, Json(json!({ "detail": detail }))).into_response()
}

fn forbidden(detail: &str) -> Response {
    (StatusCode::FORBIDDEN, Json(json!({ "detail": detail }))).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exempt_paths() {
        assert!(auth_path_exempt("/health"));
        assert!(auth_path_exempt("/api/health"));
        assert!(auth_path_exempt("/docs"));
        assert!(auth_path_exempt("/openapi.json"));
        assert!(!auth_path_exempt("/bacnet/read"));
        assert!(!auth_path_exempt("/api/bacnet/read"));
    }
}
