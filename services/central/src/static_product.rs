//! Optional static product UI (Wave B shell) served from central when enabled.
//!
//! Browser talks to same-origin `/api` only; assets are self-hosted under `/app/`.

use std::path::PathBuf;

use axum::body::Body;
use axum::http::{header, HeaderValue, Request, Response};
use axum::middleware::{self, Next};
use axum::response::Redirect;
use axum::routing::get;
use axum::Router;
use tower_http::services::ServeDir;

const ENV_ENABLE: &str = "OPENFDD_STATIC_PRODUCT_UI";
const ENV_ROOT: &str = "OPENFDD_STATIC_PRODUCT_DIR";

/// Product CSP for `/app/*`: no `unsafe-inline` / `unsafe-eval`; same-origin only.
pub(crate) const CONTENT_SECURITY_POLICY: &str = concat!(
    "default-src 'self'; ",
    "script-src 'self'; ",
    "style-src 'self'; ",
    "img-src 'self' data:; ",
    "font-src 'self' data:; ",
    "connect-src 'self'; ",
    "object-src 'none'; ",
    "base-uri 'self'; ",
    "form-action 'self'; ",
    "frame-ancestors 'self'"
);

/// When `OPENFDD_STATIC_PRODUCT_UI=1`, mount `/app/` static assets from disk.
pub fn router() -> Router {
    if !enabled() {
        return Router::new();
    }
    let root = static_root();
    if !root.join("index.html").is_file() {
        tracing::warn!(
            path = %root.display(),
            "OPENFDD_STATIC_PRODUCT_UI set but index.html missing; static UI disabled"
        );
        return Router::new();
    }
    tracing::info!(path = %root.display(), "static product UI enabled at /app/");
    Router::new()
        .route("/app", get(|| async { Redirect::temporary("/app/") }))
        .nest_service(
            "/app/",
            ServeDir::new(root).append_index_html_on_directories(true),
        )
        .layer(middleware::from_fn(apply_static_product_headers))
}

async fn apply_static_product_headers(request: Request<Body>, next: Next) -> Response<Body> {
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    if let Ok(value) = HeaderValue::from_str(CONTENT_SECURITY_POLICY) {
        headers.insert(header::CONTENT_SECURITY_POLICY, value);
    }
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    response
}

pub(crate) fn enabled() -> bool {
    matches_env_flag(std::env::var(ENV_ENABLE).ok().as_deref())
        || matches_env_flag(std::env::var("OPENFDD_STATIC_UI").ok().as_deref())
}

fn matches_env_flag(raw: Option<&str>) -> bool {
    raw.map(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
    .unwrap_or(false)
}

pub(crate) fn static_root() -> PathBuf {
    if let Ok(dir) = std::env::var(ENV_ROOT) {
        let trimmed = dir.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("static/product")
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;

    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    use super::*;

    struct EnvGuard {
        key: &'static str,
        prev: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let prev = std::env::var(key).ok();
            std::env::set_var(key, value);
            Self { key, prev }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match self.prev.take() {
                Some(v) => std::env::set_var(self.key, v),
                None => std::env::remove_var(self.key),
            }
        }
    }

    #[test]
    fn default_static_root_points_at_repo_tree() {
        let root = static_root();
        assert!(root.ends_with("static/product"));
        assert!(root.join("index.html").is_file());
    }

    #[test]
    fn disabled_without_env() {
        let _lock = crate::test_env_lock::lock_env();
        std::env::remove_var(ENV_ENABLE);
        std::env::remove_var("OPENFDD_STATIC_UI");
        assert!(!enabled());
    }

    #[test]
    fn csp_disallows_unsafe_inline_and_eval() {
        let csp = CONTENT_SECURITY_POLICY.to_ascii_lowercase();
        assert!(!csp.contains("unsafe-inline"));
        assert!(!csp.contains("unsafe-eval"));
        assert!(csp.contains("script-src 'self'"));
    }

    #[test]
    fn static_html_has_no_external_scripts_or_inline_styles() {
        let root = static_root();
        for name in ["index.html", "tree.html", "rcx.html", "fdd.html"] {
            let path = root.join(name);
            let html = fs::read_to_string(&path).unwrap_or_else(|e| panic!("{name}: {e}"));
            assert!(
                !html.contains("http://"),
                "{name} must not reference http:// assets"
            );
            assert!(
                !html.contains("https://"),
                "{name} must not reference https:// assets"
            );
            assert!(
                !html.contains("/api/v1"),
                "{name} must not reference NF /api/v1"
            );
            assert!(
                !html.contains("style=\""),
                "{name} must not use inline style attributes"
            );
            assert!(
                !html.contains("<script") || html.contains("type=\"module\""),
                "{name} must only load module scripts"
            );
        }
    }

    #[test]
    fn vendored_echarts_assets_present() {
        let vendor = static_root().join("assets/vendor");
        assert!(
            vendor.join("echarts.esm.min.js").is_file(),
            "echarts.esm.min.js must be vendored under static product assets"
        );
        assert!(
            vendor.join("LICENSE.echarts.txt").is_file(),
            "ECharts LICENSE must ship beside vendor JS"
        );
        for sidecar in ["echarts.esm.min.js.version"] {
            assert!(
                vendor.join(sidecar).is_file(),
                "{sidecar} must record vendored ECharts version"
            );
        }
        assert!(
            !vendor.join("echarts.min.js").exists(),
            "unused UMD echarts.min.js must not ship; import echarts.esm.min.js only"
        );
    }

    #[test]
    fn static_product_js_avoids_eval() {
        let js_root = static_root().join("assets/js");
        let mut files = Vec::new();
        walk_js(&js_root, &mut files);
        for path in files {
            let src = fs::read_to_string(&path).expect("read js");
            let rel = path.strip_prefix(static_root()).unwrap_or(&path);
            assert!(
                !src.contains("eval(") && !src.contains("new Function"),
                "{} must not use eval or Function constructor",
                rel.display()
            );
        }
    }

    fn walk_js(dir: &Path, out: &mut Vec<std::path::PathBuf>) {
        if !dir.is_dir() {
            return;
        }
        for entry in fs::read_dir(dir).expect("read_dir") {
            let entry = entry.expect("entry");
            let path = entry.path();
            if path.is_dir() {
                walk_js(&path, out);
            } else if path.extension().is_some_and(|e| e == "js") {
                out.push(path);
            }
        }
    }

    #[test]
    fn static_js_has_no_cdn_or_nf_api_v1() {
        let js_root = static_root().join("assets/js");
        let mut files = Vec::new();
        walk_js(&js_root, &mut files);
        assert!(!files.is_empty(), "expected static product JS modules");
        for path in files {
            let src = fs::read_to_string(&path).expect("read js");
            let rel = path.strip_prefix(static_root()).unwrap_or(&path);
            assert!(
                !src.contains("jsdelivr"),
                "{} must not load CDN scripts",
                rel.display()
            );
            assert!(
                !src.contains("/api/v1"),
                "{} must not call NF /api/v1",
                rel.display()
            );
            assert!(
                !src.contains("http://") && !src.contains("https://"),
                "{} must stay same-origin",
                rel.display()
            );
        }
    }

    #[tokio::test]
    async fn serves_vendored_echarts_with_csp() {
        let _lock = crate::test_env_lock::lock_env();
        let _guard = EnvGuard::set(ENV_ENABLE, "1");
        let app = router();
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/app/assets/vendor/echarts.esm.min.js")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let csp = response
            .headers()
            .get(header::CONTENT_SECURITY_POLICY)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        assert_eq!(csp, CONTENT_SECURITY_POLICY);
    }

    #[tokio::test]
    async fn index_html_served_with_csp() {
        let _lock = crate::test_env_lock::lock_env();
        let _guard = EnvGuard::set(ENV_ENABLE, "1");
        let app = router();
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/app/")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        assert!(response
            .headers()
            .contains_key(header::CONTENT_SECURITY_POLICY));
    }
}
