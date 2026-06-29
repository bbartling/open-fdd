//! Minimal MCP (Model Context Protocol) stdio server for Open-FDD bridge REST.
//! Read-first tools only — see docs/agent/openfdd-mcp-tool-contract.md

mod auth;
mod bridge;
mod gate;
mod protocol;

use protocol::Server;

fn main() {
    if let Err(e) = Server::new(bridge::BridgeClient::from_env()).run_stdio() {
        eprintln!("openfdd-mcp error: {e}");
        std::process::exit(1);
    }
}
