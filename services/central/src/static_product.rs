//! Optional static product UI (Wave B shell) served from central when enabled.
//!
//! Browser talks to same-origin `/api` only; assets are self-hosted under `/app/`.

use std::path::PathBuf;

use axum::response::Redirect;
use axum::routing::get;
use axum::Router;
use tower_http::services::ServeDir;

const ENV_ENABLE: &str = "OPENFDD_STATIC_PRODUCT_UI";
const ENV_ROOT: &str = "OPENFDD_STATIC_PRODUCT_DIR";

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
            "/app",
            ServeDir::new(root).append_index_html_on_directories(true),
        )
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

fn static_root() -> PathBuf {
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
    use super::*;

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
}
