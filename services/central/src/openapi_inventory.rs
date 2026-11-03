//! Router ↔ OpenAPI inventory for product `/api/*` routes (#1490).
//!
//! Parses `.route("/api/…")` registrations from the central routers merged in
//! `main.rs` and compares them to the generated OpenAPI document.

use std::collections::BTreeSet;
use std::path::PathBuf;

use serde::Deserialize;
use utoipa::openapi::path::{HttpMethod, Operation, PathItem};
use utoipa::openapi::{OpenApi, RefOr, Response, Responses};
use utoipa::Modify;

/// Product central route modules (must stay aligned with `main.rs` merges).
const ROUTE_SOURCE_FILES: &[&str] = &[
    "routes.rs",
    "afdd_scheduler.rs",
    "product_schedules.rs",
    "sql_anomaly.rs",
    "cutover.rs",
    "vibe21.rs",
];

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RouteKey {
    pub method: String,
    pub path: String,
}

impl RouteKey {
    pub fn new(method: &str, path: &str) -> Self {
        Self {
            method: method.to_ascii_uppercase(),
            path: normalize_openapi_path(path),
        }
    }
}

/// Axum `{param}` segments already match OpenAPI path keys.
pub fn normalize_openapi_path(path: &str) -> String {
    path.to_string()
}

pub fn product_version() -> &'static str {
    include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/../../VERSION")).trim()
}

pub fn central_src_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src")
}

pub fn collect_router_routes() -> BTreeSet<RouteKey> {
    let mut routes = BTreeSet::new();
    for file in ROUTE_SOURCE_FILES {
        let path = central_src_dir().join(file);
        let text = std::fs::read_to_string(&path).unwrap_or_else(|e| {
            panic!("read route source {}: {e}", path.display());
        });
        let production = strip_cfg_test_modules(&text);
        routes.extend(parse_routes_from_source(&production));
    }
    routes
}

/// Drop `#[cfg(test)] mod … { … }` blocks so unit-test routers are not inventoried.
fn strip_cfg_test_modules(text: &str) -> String {
    let mut out = String::new();
    let mut cursor = 0usize;
    while cursor < text.len() {
        let Some(rel) = text[cursor..].find("#[cfg(test)]") else {
            out.push_str(&text[cursor..]);
            break;
        };
        let cfg_start = cursor + rel;
        out.push_str(&text[cursor..cfg_start]);
        let after = cfg_start + "#[cfg(test)]".len();
        let mod_start = text[after..]
            .find("mod ")
            .map(|i| after + i)
            .filter(|&i| {
                text[after..i]
                    .chars()
                    .all(|c| c.is_whitespace())
            });
        let Some(mod_start) = mod_start else {
            out.push_str("#[cfg(test)]");
            cursor = after;
            continue;
        };
        let Some(brace) = text[mod_start..].find('{') else {
            out.push_str(&text[cfg_start..after]);
            cursor = after;
            continue;
        };
        let block_start = mod_start + brace;
        let Some(block_end) = matching_brace_end(text, block_start) else {
            out.push_str(&text[cfg_start..=block_start]);
            cursor = block_start + 1;
            continue;
        };
        cursor = block_end + 1;
    }
    out
}

fn matching_brace_end(text: &str, open_brace: usize) -> Option<usize> {
    let mut depth = 0usize;
    for (offset, ch) in text[open_brace..].char_indices() {
        match ch {
            '{' => depth += 1,
            '}' => {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    return Some(open_brace + offset);
                }
            }
            _ => {}
        }
    }
    None
}

/// Walk `.route(` registrations and infer HTTP methods from the handler chain.
pub fn parse_routes_from_source(text: &str) -> BTreeSet<RouteKey> {
    let mut routes = BTreeSet::new();
    let mut search_from = 0;
    while let Some(rel) = text[search_from..].find(".route(") {
        let start = search_from + rel + ".route(".len();
        let Some((api_path, handler_end)) = parse_route_call(&text[start..]) else {
            search_from = start;
            continue;
        };
        if api_path.starts_with("/api") {
            let handler = &text[start + handler_start_offset(&text[start..])..handler_end];
            for method in infer_methods(handler) {
                routes.insert(RouteKey::new(method, api_path));
            }
        }
        search_from = start + handler_end;
    }
    routes
}

fn handler_start_offset(after_path: &str) -> usize {
    let mut i = 0;
    let bytes = after_path.as_bytes();
    while i < bytes.len() && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    if i < bytes.len() && bytes[i] == b',' {
        i += 1;
    }
    while i < bytes.len() && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    i
}

fn parse_route_call(text: &str) -> Option<(&str, usize)> {
    let mut i = 0;
    let bytes = text.as_bytes();
    while i < bytes.len() && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    if bytes.get(i) != Some(&b'"') {
        return None;
    }
    i += 1;
    let path_start = i;
    while i < bytes.len() && bytes[i] != b'"' {
        i += 1;
    }
    if i >= bytes.len() {
        return None;
    }
    let path = &text[path_start..i];
    i += 1;
    let mut depth = 1usize;
    while i < bytes.len() && depth > 0 {
        match bytes[i] {
            b'(' => depth += 1,
            b')' => depth -= 1,
            _ => {}
        }
        i += 1;
    }
    Some((path, i))
}

fn infer_methods(handler: &str) -> Vec<&'static str> {
    const METHODS: &[&str] = &["get", "post", "put", "patch", "delete"];
    let mut found = Vec::new();
    for method in METHODS {
        if handler.contains(&format!("{method}("))
            || handler.contains(&format!("routing::{method}("))
        {
            found.push(*method);
        }
    }
    found
}

pub fn collect_openapi_routes(doc: &OpenApi) -> BTreeSet<RouteKey> {
    let mut routes = BTreeSet::new();
    for (path, item) in &doc.paths.paths {
        push_operation(&mut routes, "GET", path, item.get.as_ref());
        push_operation(&mut routes, "POST", path, item.post.as_ref());
        push_operation(&mut routes, "PUT", path, item.put.as_ref());
        push_operation(&mut routes, "PATCH", path, item.patch.as_ref());
        push_operation(&mut routes, "DELETE", path, item.delete.as_ref());
        push_operation(&mut routes, "HEAD", path, item.head.as_ref());
        push_operation(&mut routes, "OPTIONS", path, item.options.as_ref());
        push_operation(&mut routes, "TRACE", path, item.trace.as_ref());
    }
    routes
}

fn push_operation(
    routes: &mut BTreeSet<RouteKey>,
    method: &str,
    path: &str,
    op: Option<&Operation>,
) {
    if op.is_some() {
        routes.insert(RouteKey::new(method, path));
    }
}

#[derive(Debug, Deserialize)]
pub struct AllowlistFile {
    pub schema_version: String,
    pub entries: Vec<AllowlistEntry>,
}

#[derive(Debug, Deserialize, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct AllowlistEntry {
    pub method: String,
    pub path: String,
    pub reason: String,
}

impl AllowlistEntry {
    pub fn route_key(&self) -> RouteKey {
        RouteKey::new(&self.method, &self.path)
    }
}

pub fn load_allowlist() -> AllowlistFile {
    let raw = include_str!("../openapi_route_allowlist.json");
    serde_json::from_str(raw).unwrap_or_else(|e| panic!("openapi_route_allowlist.json: {e}"))
}

pub fn allowlist_route_keys(entries: &[AllowlistEntry]) -> BTreeSet<RouteKey> {
    entries.iter().map(AllowlistEntry::route_key).collect()
}

pub fn compare_router_and_openapi(
    router: &BTreeSet<RouteKey>,
    openapi: &BTreeSet<RouteKey>,
    allowlist: &BTreeSet<RouteKey>,
) -> Result<(), String> {
    for key in router {
        if openapi.contains(key) || allowlist.contains(key) {
            continue;
        }
        return Err(format!(
            "router route {} {} missing from OpenAPI and allowlist",
            key.method, key.path
        ));
    }
    for key in openapi {
        if router.contains(key) || allowlist.contains(key) {
            continue;
        }
        return Err(format!(
            "OpenAPI path {} {} has no matching router registration",
            key.method, key.path
        ));
    }
    Ok(())
}

pub fn assert_allowlist_shrink_only(
    openapi: &BTreeSet<RouteKey>,
    entries: &[AllowlistEntry],
) -> Result<(), String> {
    for entry in entries {
        let key = entry.route_key();
        if openapi.contains(&key) {
            return Err(format!(
                "allowlist entry {} {} is now documented in OpenAPI — remove it ({})",
                key.method, key.path, entry.reason
            ));
        }
    }
    Ok(())
}

pub fn route_is_public_bearer_exempt(method: HttpMethod, path: &str) -> bool {
    matches!(
        (method, path),
        (HttpMethod::Get, "/api/health")
            | (HttpMethod::Get, "/api/auth/status")
            | (HttpMethod::Post, "/api/auth/login")
    )
}

fn stub_operation(method: &str, path: &str) -> Operation {
    let summary = format!("{method} {path}");
    let mut responses = Responses::new();
    responses.responses.insert(
        "200".into(),
        RefOr::T(Response::new(Some("JSON response envelope"))),
    );
    Operation {
        tags: Some(vec![tag_for_path(path)]),
        summary: Some(summary),
        responses,
        ..Operation::new()
    }
}

fn tag_for_path(path: &str) -> String {
    if path.starts_with("/api/jobs") {
        "jobs".into()
    } else if path.starts_with("/api/analytics") {
        "analytics".into()
    } else if path.starts_with("/api/datasets") || path.starts_with("/api/csv/") {
        "datasets".into()
    } else if path.starts_with("/api/fdd") || path.starts_with("/api/afdd") {
        "fdd".into()
    } else if path.starts_with("/api/reports") {
        "reports".into()
    } else if path.starts_with("/api/ingest") {
        "ingest".into()
    } else if path.starts_with("/api/fuel") {
        "fuel".into()
    } else {
        "central".into()
    }
}

fn http_method_from_str(method: &str) -> Option<HttpMethod> {
    match method.to_ascii_uppercase().as_str() {
        "GET" => Some(HttpMethod::Get),
        "POST" => Some(HttpMethod::Post),
        "PUT" => Some(HttpMethod::Put),
        "PATCH" => Some(HttpMethod::Patch),
        "DELETE" => Some(HttpMethod::Delete),
        "HEAD" => Some(HttpMethod::Head),
        "OPTIONS" => Some(HttpMethod::Options),
        "TRACE" => Some(HttpMethod::Trace),
        _ => None,
    }
}

fn operation_slot<'a>(item: &'a mut PathItem, method: HttpMethod) -> &'a mut Option<Operation> {
    match method {
        HttpMethod::Get => &mut item.get,
        HttpMethod::Post => &mut item.post,
        HttpMethod::Put => &mut item.put,
        HttpMethod::Patch => &mut item.patch,
        HttpMethod::Delete => &mut item.delete,
        HttpMethod::Head => &mut item.head,
        HttpMethod::Options => &mut item.options,
        HttpMethod::Trace => &mut item.trace,
        HttpMethod::Query => &mut item.query,
    }
}

fn operation_ref(item: &PathItem, method: HttpMethod) -> Option<&Operation> {
    match method {
        HttpMethod::Get => item.get.as_ref(),
        HttpMethod::Post => item.post.as_ref(),
        HttpMethod::Put => item.put.as_ref(),
        HttpMethod::Patch => item.patch.as_ref(),
        HttpMethod::Delete => item.delete.as_ref(),
        HttpMethod::Head => item.head.as_ref(),
        HttpMethod::Options => item.options.as_ref(),
        HttpMethod::Trace => item.trace.as_ref(),
        HttpMethod::Query => item.query.as_ref(),
    }
}

/// Ensures every live router `/api/*` method+path appears in the OpenAPI path map.
pub struct RouteInventoryAddon;

impl Modify for RouteInventoryAddon {
    fn modify(&self, openapi: &mut OpenApi) {
        let router = collect_router_routes();
        for key in router {
            let Some(http_method) = http_method_from_str(&key.method) else {
                continue;
            };
            let entry = openapi
                .paths
                .paths
                .entry(key.path.clone())
                .or_insert_with(PathItem::default);
            let slot = operation_slot(entry, http_method);
            if slot.is_none() {
                *slot = Some(stub_operation(&key.method, &key.path));
            }
        }
    }
}

/// Sets info.version from repo `VERSION` and applies bearer security on operations.
pub struct OpenApiPolicyAddon;

impl Modify for OpenApiPolicyAddon {
    fn modify(&self, openapi: &mut OpenApi) {
        openapi.info.version = product_version().to_string();

        use utoipa::openapi::security::{Http, HttpAuthScheme, SecurityRequirement, SecurityScheme};
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "bearerAuth",
                SecurityScheme::Http(
                    Http::builder()
                        .scheme(HttpAuthScheme::Bearer)
                        .bearer_format("JWT")
                        .description(Some(
                            "Operator or admin JWT from POST /api/auth/login or POST /api/auth/agent-token.",
                        ))
                        .build(),
                ),
            );
        }

        let bearer = SecurityRequirement::new("bearerAuth", Vec::<String>::new());
        let paths: Vec<String> = openapi.paths.paths.keys().cloned().collect();
        for path in paths {
            let Some(item) = openapi.paths.paths.get_mut(&path) else {
                continue;
            };
            for method in [
                HttpMethod::Get,
                HttpMethod::Post,
                HttpMethod::Put,
                HttpMethod::Patch,
                HttpMethod::Delete,
                HttpMethod::Head,
                HttpMethod::Options,
                HttpMethod::Trace,
            ] {
                if operation_ref(item, method).is_none() {
                    continue;
                }
                let exempt = route_is_public_bearer_exempt(method, &path);
                if let Some(op) = operation_slot(item, method).as_mut() {
                    if exempt {
                        op.security = None;
                    } else {
                        op.security = Some(vec![bearer.clone()]);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_route_call_finds_chained_methods() {
        let src = r#"
        .route(
            "/api/csv/import/sessions/{session_id}",
            get(csv_get_session).delete(csv_delete_session),
        )
        "#;
        let routes = parse_routes_from_source(src);
        assert!(routes.contains(&RouteKey::new("GET", "/api/csv/import/sessions/{session_id}")));
        assert!(routes.contains(&RouteKey::new(
            "DELETE",
            "/api/csv/import/sessions/{session_id}"
        )));
    }

    #[test]
    fn strip_cfg_test_modules_drops_test_routers() {
        let src = r#"
        pub fn router() -> Router {
            Router::new().route("/api/live", get(ok))
        }
        #[cfg(test)]
        mod tests {
            fn t() {
                Router::new().route("/api/test-only", get(t));
            }
        }
        "#;
        let prod = strip_cfg_test_modules(src);
        let routes = parse_routes_from_source(&prod);
        assert!(routes.contains(&RouteKey::new("GET", "/api/live")));
        assert!(!routes.contains(&RouteKey::new("GET", "/api/test-only")));
    }

    #[test]
    fn parse_cutover_axum_routing_methods() {
        let src = r#"
        .route(
            "/api/ui/generation",
            axum::routing::get(get_generation).put(put_generation),
        )
        "#;
        let routes = parse_routes_from_source(src);
        assert!(routes.contains(&RouteKey::new("GET", "/api/ui/generation")));
        assert!(routes.contains(&RouteKey::new("PUT", "/api/ui/generation")));
    }
}
