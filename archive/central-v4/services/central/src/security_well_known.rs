//! Public well-known resources served by central (not SPA fallback).

use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};

/// RFC 9116 security contact file for bare central (portal stack API origin).
const SECURITY_TXT: &str = "\
Contact: https://github.com/bbartling/open-fdd/security/advisories/new
Expires: 2027-12-31T23:59:59Z
Preferred-Languages: en
Canonical: https://github.com/bbartling/open-fdd/security/advisories/new
Policy: https://github.com/bbartling/open-fdd/blob/master/SECURITY.md
";

pub async fn security_txt() -> Response {
    let mut headers = HeaderMap::new();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/plain; charset=utf-8"),
    );
    headers.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("public, max-age=86400"),
    );
    (StatusCode::OK, headers, SECURITY_TXT).into_response()
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::Request;
    use tower::ServiceExt;

    use super::*;

    #[tokio::test]
    async fn security_txt_is_plain_text_with_contact() {
        let response = security_txt().await;
        assert_eq!(response.status(), StatusCode::OK);
        let ctype = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        assert!(
            ctype.starts_with("text/plain"),
            "expected text/plain, got {ctype}"
        );
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let text = std::str::from_utf8(&body).expect("utf8");
        assert!(text.contains("Contact:"));
        assert!(text.contains("security/advisories/new"));
        assert!(text.contains("Expires:"));
    }

    #[tokio::test]
    async fn security_txt_route_registered_on_public_router() {
        use std::sync::Arc;

        let state = Arc::new(crate::state::AppState::new());
        let app = crate::routes::router(state);
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/.well-known/security.txt")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
    }
}
