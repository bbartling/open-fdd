//! Shared process logging init for Central / Fieldbus containers.
//!
//! - Default: human text on stdout (local laptop)
//! - `OPENFDD_LOG_FORMAT=json` — structured JSON (Railway / AWS / pen-test scrapers)
//! - Always attach `request_id` / security_audit targets when present
//!
//! Container log volume is capped by the compose/runtime log driver
//! (`max-size` / `max-file`), not by the process itself.

use tracing_subscriber::{fmt, prelude::*, EnvFilter};

pub fn init_tracing(default_filter: &str) {
    let filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(default_filter));
    let json = matches!(
        std::env::var("OPENFDD_LOG_FORMAT")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "json" | "jsonl" | "structured"
    );

    if json {
        tracing_subscriber::registry()
            .with(filter)
            .with(
                fmt::layer()
                    .json()
                    .with_current_span(true)
                    .with_span_list(false),
            )
            .init();
    } else {
        tracing_subscriber::registry()
            .with(filter)
            .with(fmt::layer())
            .init();
    }
}
