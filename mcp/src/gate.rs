//! Write-tool gating — requires env flag + explicit confirm:true per call.

use serde_json::Value;
use std::env;

pub fn require_write_confirm(args: &Value, tool: &str) -> Result<(), String> {
    if env::var("OPENFDD_MCP_ALLOW_WRITES").ok().as_deref() != Some("1") {
        return Err(format!(
            "{tool} is a write tool — set OPENFDD_MCP_ALLOW_WRITES=1 on the MCP server"
        ));
    }
    if args.get("confirm").and_then(|v| v.as_bool()) != Some(true) {
        return Err(format!("{tool} requires confirm:true in tool arguments"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn write_gate_requires_env_and_confirm() {
        env::remove_var("OPENFDD_MCP_ALLOW_WRITES");
        let args = json!({"confirm": true});
        assert!(require_write_confirm(&args, "test_tool").is_err());
        env::set_var("OPENFDD_MCP_ALLOW_WRITES", "1");
        assert!(require_write_confirm(&args, "test_tool").is_ok());
        assert!(require_write_confirm(&json!({}), "test_tool").is_err());
        env::remove_var("OPENFDD_MCP_ALLOW_WRITES");
    }
}
