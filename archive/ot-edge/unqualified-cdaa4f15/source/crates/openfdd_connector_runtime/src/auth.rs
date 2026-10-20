//! Shared fail-closed management-plane API-key middleware.

use axum::{
    extract::Request,
    http::{header, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use subtle::ConstantTimeEq;

#[derive(Clone, Debug)]
pub struct AuthState {
    api_key: Option<String>,
    invalid_api_key: bool,
}

impl AuthState {
    pub fn new(api_key: Option<String>) -> Self {
        let invalid_api_key = api_key.as_deref().is_some_and(|key| key.trim().is_empty());
        let api_key = api_key.map(|key| key.trim().to_string());
        Self {
            api_key,
            invalid_api_key,
        }
    }

    pub fn from_env(env_name: &str) -> Self {
        Self::new(std::env::var(env_name).ok())
    }
}

pub fn is_loopback_http_host(host: &str) -> bool {
    matches!(
        host.trim().to_ascii_lowercase().as_str(),
        "127.0.0.1" | "localhost" | "::1"
    )
}

pub fn require_api_key_for_bind(http_host: &str, api_key: Option<&str>) -> Result<(), String> {
    if api_key.map_or(true, |key| key.trim().is_empty()) && !is_loopback_http_host(http_host) {
        return Err(format!(
            "OPENFDD_CONNECTOR_API_KEY required when HTTP bind is not loopback (host={http_host})"
        ));
    }
    Ok(())
}

pub fn auth_path_exempt(path: &str) -> bool {
    matches!(path, "/" | "/health" | "/api/health")
}

pub async fn auth_middleware(
    axum::extract::State(state): axum::extract::State<AuthState>,
    request: Request,
    next: Next,
) -> Response {
    let path = request.uri().path().to_string();
    if auth_path_exempt(&path) {
        return next.run(request).await;
    }
    if state.invalid_api_key {
        return forbidden("Invalid API key configuration");
    }
    let Some(ref key) = state.api_key else {
        return next.run(request).await;
    };
    let auth = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
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
    use axum::{
        body::Body,
        http::{Request, StatusCode},
        middleware,
        routing::get,
        Router,
    };
    use tower::ServiceExt;

    async fn ok() -> StatusCode {
        StatusCode::OK
    }

    fn app(state: AuthState) -> Router {
        Router::new()
            .route("/", get(ok))
            .route("/health", get(ok))
            .route("/api/health", get(ok))
            .route("/health/", get(ok))
            .route("/private", get(ok))
            .layer(middleware::from_fn_with_state(state, auth_middleware))
    }

    async fn request(app: Router, uri: &str, authorization: Option<&str>) -> StatusCode {
        let mut builder = Request::builder().uri(uri);
        if let Some(authorization) = authorization {
            builder = builder.header("authorization", authorization);
        }
        app.oneshot(builder.body(Body::empty()).unwrap())
            .await
            .unwrap()
            .status()
    }

    #[test]
    fn non_loopback_requires_key() {
        assert!(require_api_key_for_bind("0.0.0.0", None).is_err());
        assert!(require_api_key_for_bind("0.0.0.0", Some("secret")).is_ok());
        assert!(require_api_key_for_bind("0.0.0.0", Some(" ")).is_err());
        assert!(require_api_key_for_bind("127.0.0.1", None).is_ok());
    }

    #[test]
    fn only_readiness_paths_are_public() {
        assert!(auth_path_exempt("/health"));
        assert!(auth_path_exempt("/api/health"));
        assert!(!auth_path_exempt("/api/connector/identity"));
        assert!(!auth_path_exempt("/health/"));
    }

    #[tokio::test]
    async fn middleware_requires_bearer_key_on_protected_paths() {
        let state = AuthState::new(Some("secret".into()));
        assert_eq!(
            request(app(state.clone()), "/private", None).await,
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            request(app(state.clone()), "/private", Some("Bearer wrong")).await,
            StatusCode::FORBIDDEN
        );
        assert_eq!(
            request(app(state.clone()), "/private", Some("Bearer secret")).await,
            StatusCode::OK
        );
        assert_eq!(request(app(state), "/health", None).await, StatusCode::OK);
    }

    #[tokio::test]
    async fn invalid_key_configuration_cannot_authorize_and_exemptions_are_exact() {
        for raw in ["", "   "] {
            let state = AuthState::new(Some(raw.into()));
            assert_ne!(
                request(app(state.clone()), "/private", Some("Bearer ")).await,
                StatusCode::OK
            );
        }
        let state = AuthState::new(Some("secret".into()));
        assert_eq!(request(app(state.clone()), "/", None).await, StatusCode::OK);
        assert_eq!(
            request(app(state.clone()), "/api/health", None).await,
            StatusCode::OK
        );
        assert_eq!(
            request(app(state), "/health/", None).await,
            StatusCode::UNAUTHORIZED
        );
    }
}
