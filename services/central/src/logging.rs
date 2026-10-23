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
            *s
        } else if let Some(s) = info.payload().downcast_ref::<String>() {
            s.as_str()
        } else {
            "non-string panic payload"
        };
        let line = format_panic_line(&loc, payload);
        let mut stderr = std::io::stderr().lock();
        // A failed stderr write inside a panic hook has nowhere else to go.
        let _ = writeln!(stderr, "{line}");
        let _ = stderr.flush();
        previous(info);
    }));
}

/// Budget for the panic payload. Location is bounded separately.
const MAX_PANIC_PAYLOAD_CHARS: usize = 2048;
const MAX_PANIC_LOCATION_CHARS: usize = 256;

/// One sanitized stderr line: secrets scrubbed, control characters escaped,
/// payload and location cut to fixed budgets with a truncation marker.
fn format_panic_line(location: &str, payload: &str) -> String {
    use open_fdd_edge_prototype::auth::redact::bounded;
    format!(
        "FATAL openfdd-central panic at {}: {}",
        bounded(location, MAX_PANIC_LOCATION_CHARS),
        bounded(payload, MAX_PANIC_PAYLOAD_CHARS)
    )
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

#[cfg(test)]
mod tests {
    use super::*;
    use open_fdd_edge_prototype::auth::redact::TRUNCATION_MARKER;

    #[test]
    fn panic_line_scrubs_secrets_controls_and_size() {
        let payload = format!(
            "called unwrap on Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln password=hunter2-canary \
             https://h.example/x?token=q-canary\n\u{1b}[2Jforged {}",
            "p".repeat(100 * 1024)
        );
        let line = format_panic_line("src/routes.rs:1:1", &payload);
        for leaked in ["eyJhbGci", "hunter2-canary", "q-canary"] {
            assert!(!line.contains(leaked), "{leaked} leaked");
        }
        assert!(!line.chars().any(char::is_control));
        assert!(line.ends_with(TRUNCATION_MARKER));
        assert!(line.chars().count() < MAX_PANIC_PAYLOAD_CHARS + MAX_PANIC_LOCATION_CHARS + 64);
    }
}
