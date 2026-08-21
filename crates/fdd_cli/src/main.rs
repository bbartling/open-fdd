mod inventory;

use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use fdd_bench::{compare_results, run_benchmark, write_compare_markdown};
use fdd_core::validate_building;
use fdd_rules::{load_registry, run_all_rules_with_overrides};
use fdd_sql::{
    new_historian_session, register_parquet_tree, run_sql_file_bounded,
    DEFAULT_INTERACTIVE_MAX_ROWS,
};
use fdd_store::{ingest_building, HistorianConfig};
use inventory::write_inventory;

#[derive(Parser)]
#[command(
    name = "fdd_cli",
    about = "Open-FDD CLI — validate, ingest, query, run-rules, compare, benchmark"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Scan Python codebase for pandas FDD analytics inventory
    Inventory {
        #[arg(long, default_value = "fdd_app")]
        app_root: PathBuf,
        #[arg(long, default_value = "vibe19_agent_spec/docs/PYTHON_INVENTORY_CLI.md")]
        out: PathBuf,
    },
    /// Validate building CSV tree
    Validate {
        #[arg(long)]
        data_root: PathBuf,
        #[arg(long)]
        building: String,
    },
    /// Ingest CSV histories to Parquet sidecars
    Ingest {
        #[arg(long)]
        data_root: PathBuf,
        #[arg(long)]
        building: String,
        #[arg(long, default_value = ".cache/parquet")]
        out: PathBuf,
    },
    /// Run a DataFusion SQL file against Parquet
    Query {
        #[arg(long)]
        parquet: PathBuf,
        #[arg(long)]
        sql_file: PathBuf,
    },
    /// Run all SQL rules from registry
    RunRules {
        #[arg(long)]
        parquet: PathBuf,
        #[arg(long, default_value = "sql_rules")]
        rules_dir: PathBuf,
        #[arg(long, default_value = ".cache/rule_results")]
        out: PathBuf,
        /// Stored CSV units: imperial (°F) or metric/si (°C converted at query).
        #[arg(long, default_value = "imperial")]
        unit_system: String,
        /// Override every rule confirm window (seconds). Use 0 to match synthetic
        /// soak `confirm_min=0` / exact-equation isolation.
        #[arg(long)]
        confirm_seconds: Option<f64>,
    },
    /// Compare pandas oracle JSON vs SQL results JSON
    Compare {
        #[arg(long)]
        python_results: PathBuf,
        #[arg(long)]
        sql_results: PathBuf,
        #[arg(long, default_value_t = 0.5)]
        tolerance: f64,
        #[arg(long, default_value = "docs/BUILDING_100_BENCHMARK.md")]
        report: PathBuf,
    },
    /// End-to-end benchmark (validate → scan → ingest → rules)
    Benchmark {
        #[arg(long)]
        data_root: PathBuf,
        #[arg(long)]
        building: String,
        #[arg(long, default_value = ".cache/parquet")]
        parquet_out: PathBuf,
        #[arg(long, default_value = "sql_rules")]
        rules_dir: PathBuf,
        #[arg(long, default_value = ".cache/rule_results")]
        rule_out: PathBuf,
        #[arg(long, default_value = "docs/BUILDING_100_BENCHMARK.md")]
        report: PathBuf,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Inventory { app_root, out } => {
            write_inventory(&app_root, &out)?;
            println!("inventory written to {}", out.display());
        }
        Commands::Validate {
            data_root,
            building,
        } => {
            let report = validate_building(&data_root, &building)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
            if !report.errors.is_empty() {
                std::process::exit(1);
            }
        }
        Commands::Ingest {
            data_root,
            building,
            out,
        } => {
            let report = ingest_building(&data_root, &building, &out)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Commands::Query { parquet, sql_file } => {
            let historian = HistorianConfig::from_env()?;
            let ctx = new_historian_session(&historian)?;
            register_parquet_tree(&ctx, &parquet).await?;
            let result =
                run_sql_file_bounded(&ctx, &sql_file, DEFAULT_INTERACTIVE_MAX_ROWS).await?;
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        Commands::RunRules {
            parquet,
            rules_dir,
            out,
            unit_system,
            confirm_seconds,
        } => {
            let registry = load_registry(&rules_dir)?;
            let mut overrides = std::collections::HashMap::new();
            if let Some(cs) = confirm_seconds {
                for rule in &registry.rules {
                    overrides.insert(
                        rule.rule_id.clone(),
                        std::collections::HashMap::from([("confirm_seconds".into(), cs)]),
                    );
                }
            }
            let report = run_all_rules_with_overrides(
                &parquet,
                &registry,
                &out,
                &overrides,
                None,
                None,
                Some(unit_system.as_str()),
            )
            .await?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Commands::Compare {
            python_results,
            sql_results,
            tolerance,
            report,
        } => {
            let cmp = compare_results(&python_results, &sql_results, tolerance)?;
            write_compare_markdown(&cmp, &report)?;
            println!("{}", serde_json::to_string_pretty(&cmp)?);
            println!("report: {}", report.display());
            if cmp.material_failure {
                std::process::exit(1);
            }
        }
        Commands::Benchmark {
            data_root,
            building,
            parquet_out,
            rules_dir,
            rule_out,
            report,
        } => {
            let bench = run_benchmark(
                &data_root,
                &building,
                &parquet_out,
                &rules_dir,
                &rule_out,
                &report,
            )
            .await?;
            println!("{}", serde_json::to_string_pretty(&bench)?);
            println!("report: {}", report.display());
        }
    }
    Ok(())
}
