//! Edge release version surfaced on /api/health and host stats.

pub fn edge_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

pub fn health_json(auth_required: bool) -> serde_json::Value {
    let image_tag =
        std::env::var("OPENFDD_IMAGE_TAG").unwrap_or_else(|_| edge_version().to_string());
    serde_json::json!({
        "ok": true,
        "version": edge_version(),
        "image_tag": image_tag,
        "auth_required": auth_required,
        "mode": "rust-jwt-edge-auth",
        "services": [
            "bridge-api", "dashboard", "historian", "commission", "bacnet", "modbus",
            "haystack-gateway", "arrow", "datafusion", "control", "json-api", "agent-api"
        ]
    })
}
