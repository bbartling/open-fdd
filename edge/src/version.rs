//! Edge release version surfaced on /api/health and host stats.

pub fn edge_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Public liveness payload — no secrets, OT hostnames, or internal topology.
pub fn health_json(auth_required: bool) -> serde_json::Value {
    let image_tag =
        std::env::var("OPENFDD_IMAGE_TAG").unwrap_or_else(|_| edge_version().to_string());
    serde_json::json!({
        "ok": true,
        "version": edge_version(),
        "image_tag": image_tag,
        "auth_required": auth_required,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_health_has_no_sensitive_keys() {
        let body = health_json(true);
        let obj = body.as_object().expect("object");
        for forbidden in [
            "services",
            "mode",
            "bacnet_bind",
            "password",
            "token",
            "username",
            "secret",
            "stack",
        ] {
            assert!(
                !obj.contains_key(forbidden),
                "public health must not include {forbidden}"
            );
        }
        assert_eq!(obj.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(obj.get("version").and_then(|v| v.as_str()).is_some());
    }
}
