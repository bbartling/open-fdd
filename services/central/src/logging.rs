//! Shared process logging init for Central / Fieldbus containers.
//!
//! - Default: human text on stdout (local laptop)
//! - `OPENFDD_LOG_FORMAT=json` — structured JSON (Railway / AWS / pen-test scrapers)
//! - Always attach `request_id` / security_audit targets when present
//! - Panic hook flushes to **stderr** so Railway deploy logs keep death reason
//!
//! Container log volume is capped by the compose/runtime log driver
//! (`max-size` / `max-file`), not by the process itself.
//! This is RCA evidence — not a memory-spike / Node-logger cure.

use std::io::Write;
use std::panic;

use tracing_subscriber::{fmt, prelude::*, EnvFilter};

/// Install a panic hook that writes the panic payload + location to stderr and
/// flushes before unwinding. Railway log slices often start at the next boot;
/// without this, Soft-OPEN restarts lose the death reason (#1127 / Q1a).
pub fn install_panic_hook() {
    let previous = panic::take_hook();
    panic::set_hook(Box::new(move |info| {
        let loc = info
            .location()
            .map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()))
            .unwrap_or_else(|| "unknown".into());
        let payload = if let Some(s) = info.payload().downcast_ref::<&str>() {
            (*s).to_string()
        } else if let Some(s) = info.payload().downcast_ref::<String>() {
            s.clone()
        } else {
            "non-string panic payload".into()
        };
        let mut stderr = std::io::stderr().lock();
        let _ = writeln!(
            stderr,
            "FATAL openfdd-central panic at {loc}: {payload}"
        );
        let _ = stderr.flush();
        previous(info);
    }));
}

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

    // stderr for fatal visibility on platforms that only scrape one stream
    // for crash windows; keep normal tracing on stdout for volume drivers.
    if json {
        tracing_subscriber::registry()
            .with(filter)
            .with(
                fmt::layer()
                    .json()
                    .with_current_span(true)
                    .with_span_list(false)
                    .with_writer(std::io::stdout),
            )
            .init();
    } else {
        tracing_subscriber::registry()
            .with(filter)
            .with(fmt::layer().with_writer(std::io::stdout))
            .init();
    }
}
