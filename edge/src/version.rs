//! Edge release version surfaced on /api/health and host stats.

pub fn edge_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn git_sha_short(full: &str) -> String {
    let trimmed = full.trim();
    if trimmed.len() <= 7 || trimmed == "unknown" {
        trimmed.to_string()
    } else {
        trimmed.chars().take(7).collect()
    }
}

/// Public liveness payload — no secrets, OT hostnames, or internal topology.
pub fn health_json(auth_required: bool) -> serde_json::Value {
    let image_tag = env_or("OPENFDD_IMAGE_TAG", edge_version());
    let git_sha = env_or("OPENFDD_GIT_SHA", "unknown");
    let git_sha_short = git_sha_short(&git_sha);
    let image_name = env_or("OPENFDD_IMAGE_NAME", "ghcr.io/bbartling/openfdd-central");
    let image_ref =
        std::env::var("OPENFDD_IMAGE_REF").unwrap_or_else(|_| format!("{image_name}:{image_tag}"));
    serde_json::json!({
        "ok": true,
        "version": edge_version(),
        "image_tag": image_tag,
        "image_ref": image_ref,
        "git_sha": git_sha,
        "git_sha_short": git_sha_short,
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
        assert!(obj.get("git_sha").and_then(|v| v.as_str()).is_some());
        assert!(obj.get("git_sha_short").and_then(|v| v.as_str()).is_some());
        assert!(obj.get("image_ref").and_then(|v| v.as_str()).is_some());
    }

    #[test]
    fn git_sha_short_truncates() {
        assert_eq!(git_sha_short("7165b492abc"), "7165b49");
        assert_eq!(git_sha_short("unknown"), "unknown");
    }
}
