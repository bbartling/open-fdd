//! Dev-only local validation harness CLI.

use clap::Parser;
use open_fdd_edge_prototype::dev_validation::{run, HarnessOptions};
use std::path::PathBuf;
use std::process::ExitCode;

#[derive(Parser, Debug)]
#[command(
    name = "openfdd_dev_validation",
    about = "Dev-only profile-driven RCx validation harness (no bench hardcoding)"
)]
struct Cli {
    #[arg(long)]
    base_url: String,
    #[arg(long)]
    profile: PathBuf,
    #[arg(long, default_value_t = 60)]
    duration_minutes: u64,
    #[arg(long, default_value_t = 60)]
    bacnet_interval_seconds: u64,
    #[arg(long, default_value_t = 300)]
    driver_interval_seconds: u64,
    #[arg(long)]
    report: bool,
    #[arg(long)]
    dry_run: bool,
    #[arg(long)]
    skip_browser: bool,
    #[arg(long)]
    skip_haystack_if_not_configured: bool,
    #[arg(long)]
    skip_modbus_if_not_configured: bool,
    #[arg(long)]
    output_dir: Option<PathBuf>,
    #[arg(long, default_value = "workspace/auth.env.local")]
    auth_env: PathBuf,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let opts = HarnessOptions {
        base_url: cli.base_url,
        profile_path: cli.profile,
        auth_env: cli.auth_env,
        duration_minutes: cli.duration_minutes,
        bacnet_interval_seconds: cli.bacnet_interval_seconds,
        driver_interval_seconds: cli.driver_interval_seconds,
        output_dir: cli.output_dir.unwrap_or_default(),
        dry_run: cli.dry_run,
        skip_browser: cli.skip_browser,
        skip_haystack_if_not_configured: cli.skip_haystack_if_not_configured,
        skip_modbus_if_not_configured: cli.skip_modbus_if_not_configured,
        generate_report: cli.report,
    };
    match run(opts) {
        Ok(result) => {
            println!("OVERALL: {}", if result.pass { "PASS" } else { "FAIL" });
            println!("artifact_dir={}", result.artifact_dir);
            if let Some(pdf) = result.pdf_path {
                println!("pdf_path={pdf}");
            }
            if let Some(rid) = result.report_id {
                println!("report_id={rid}");
            }
            if result.pass {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(1)
            }
        }
        Err(err) => {
            eprintln!("ERROR: {err}");
            ExitCode::from(2)
        }
    }
}
