//! Dev-only helpers — quick login and local stack scripts (OPENFDD_ALLOW_INSECURE_AUTH=1).

use crate::auth::config::AuthConfig;
use serde_json::{json, Value};
use std::env;
use std::path::PathBuf;
use std::process::Command;

pub fn insecure_dev_enabled() -> bool {
    env::var("OPENFDD_ALLOW_INSECURE_AUTH")
        .map(|v| matches!(v.as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
}

pub fn quick_login(body: &Value) -> Value {
    if !insecure_dev_enabled() {
        return json!({
            "ok": false,
            "error": "dev quick-login disabled (set OPENFDD_ALLOW_INSECURE_AUTH=1 on edge)"
        });
    }
    let role = body
        .get("role")
        .and_then(|v| v.as_str())
        .unwrap_or("integrator");
    let config = AuthConfig::load();
    for (username, (_, user_role)) in &config.users {
        if *user_role == role {
            let (token, expires_at) = crate::auth::jwt::create_token(&config, username, role);
            return json!({
                "ok": true,
                "token": token,
                "access_token": token,
                "role": role,
                "username": username,
                "expires_at": expires_at.to_rfc3339(),
                "dev": true
            });
        }
    }
    json!({
        "ok": false,
        "error": format!("no configured user for role '{role}' — run scripts/openfdd_auth_init.sh")
    })
}

pub fn run_script(body: &Value) -> Value {
    if !insecure_dev_enabled() {
        return json!({
            "ok": false,
            "error": "dev scripts disabled (set OPENFDD_ALLOW_INSECURE_AUTH=1 on edge)"
        });
    }
    let script_key = body.get("script").and_then(|v| v.as_str()).unwrap_or("");
    let (label, rel, extra): (&str, &str, &str) = match script_key {
        "ui_dev" => ("Vite UI dev server", "scripts/openfdd_ui_dev.sh", "--lan"),
        "codex_setup" => (
            "Codex agent chat relay",
            "scripts/openfdd_agent_chat_setup.sh",
            "",
        ),
        "codex_reset" => (
            "Codex relay reset",
            "scripts/openfdd_agent_chat_reset.sh",
            "",
        ),
        other => {
            return json!({
                "ok": false,
                "error": format!("unknown dev script: {other}"),
                "allowed": ["ui_dev", "codex_setup", "codex_reset"]
            });
        }
    };
    let root = repo_root();
    let script = root.join(rel);
    if !script.is_file() {
        return json!({"ok": false, "error": format!("script not found: {}", script.display())});
    }
    let log = root
        .join("workspace/logs")
        .join(format!("dev-{script_key}.log"));
    let _ = std::fs::create_dir_all(root.join("workspace/logs"));
    let shell_cmd = if extra.is_empty() {
        format!(
            "nohup bash {} >> {} 2>&1 </dev/null &",
            script.display(),
            log.display()
        )
    } else {
        format!(
            "nohup bash {} {} >> {} 2>&1 </dev/null &",
            script.display(),
            extra,
            log.display()
        )
    };
    match Command::new("bash")
        .arg("-c")
        .arg(&shell_cmd)
        .current_dir(&root)
        .env("OPENFDD_WORKSPACE", root.join("workspace"))
        .env("OPENFDD_REPO_ROOT", &root)
        .status()
    {
        Ok(status) if status.success() => json!({
            "ok": true,
            "started": script_key,
            "label": label,
            "log": log.display().to_string(),
            "hint": if script_key == "ui_dev" {
                "Open http://127.0.0.1:5173/ after a few seconds"
            } else {
                "Refresh AI integrations status in ~10s"
            }
        }),
        Ok(status) => json!({"ok": false, "error": format!("script launcher exited {status}")}),
        Err(err) => json!({"ok": false, "error": err.to_string()}),
    }
}

fn repo_root() -> PathBuf {
    if let Ok(root) = env::var("OPENFDD_REPO_ROOT") {
        if !root.is_empty() {
            return PathBuf::from(root);
        }
    }
    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}
