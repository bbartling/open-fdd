//! Bench 5007 DataFusion smoke CLI (100% Rust, no Python).

use open_fdd_edge_prototype::bench::{run_smoke, SmokeConfig};
use std::process::ExitCode;

fn main() -> ExitCode {
    let cfg = SmokeConfig::from_env_and_cli();
    match run_smoke(cfg) {
        Ok(outcome) => {
            eprintln!(
                "bench 5007 smoke {} -> {}",
                if outcome.pass { "PASS" } else { "FAIL" },
                outcome.report.config.report_dir
            );
            if outcome.pass {
                ExitCode::SUCCESS
            } else {
                for reason in &outcome.failure_reasons {
                    eprintln!("  - {reason}");
                }
                ExitCode::FAILURE
            }
        }
        Err(err) => {
            eprintln!("bench 5007 smoke error: {err}");
            ExitCode::FAILURE
        }
    }
}
