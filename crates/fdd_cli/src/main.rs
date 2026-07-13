mod inventory;

use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use fdd_bench::{compare_results, run_benchmark, run_parity, write_compare_markdown};
use fdd_core::validate_building;
use fdd_rules::{load_registry, run_all_rules};
use fdd_sql::{register_parquet_tree, run_sql_file};
use fdd_store::ingest_building;
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
    /// Compare Vibe19 oracle golden CSVs vs Open-FDD SQL rule result JSONs
    Parity {
        #[arg(long)]
        oracle_dir: PathBuf,
        #[arg(long)]
        sql_results: PathBuf,
        #[arg(long, default_value = ".cache/parity")]
        output: PathBuf,
        #[arg(long, default_value_t = 0.5)]
        tolerance: f64,
        #[arg(long, default_value = "unknown")]
        openfdd_sha: String,
        #[arg(long, default_value = "unknown")]
        vibe19_sha: String,
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
            let ctx = datafusion::prelude::SessionContext::new();
            register_parquet_tree(&ctx, &parquet).await?;
            let result = run_sql_file(&ctx, &sql_file).await?;
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        Commands::RunRules {
            parquet,
            rules_dir,
            out,
        } => {
            let registry = load_registry(&rules_dir)?;
            let report = run_all_rules(&parquet, &registry, &out).await?;
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
        Commands::Parity {
            oracle_dir,
            sql_results,
            output,
            tolerance,
            openfdd_sha,
            vibe19_sha,
        } => {
            let summary = run_parity(
                &oracle_dir,
                &sql_results,
                &output,
                tolerance,
                &openfdd_sha,
                &vibe19_sha,
            )?;
            println!("{}", serde_json::to_string_pretty(&summary)?);
            println!("report: {}", output.join("parity_report.md").display());
            if !summary.pass {
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
            let bench =
                run_benchmark(&data_root, &building, &parquet_out, &rules_dir, &rule_out).await?;
            let md = format_benchmark_md(&bench);
            if let Some(parent) = report.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&report, &md)?;
            println!("{}", serde_json::to_string_pretty(&bench)?);
            println!("report: {}", report.display());
        }
    }
    Ok(())
}

fn format_benchmark_md(b: &fdd_bench::BenchmarkReport) -> String {
    format!(
        "# Rust + DataFusion parity benchmark\n\n\
         - building: {}\n\
         - data_available: {}\n\
         - validate_ms: {}\n\
         - equipment_count: {}\n\
         - csv_scan_ms: {}\n\
         - ingest_ms: {} (rows: {})\n\
         - rules_ms: {} (rules: {}, ok: {}, failed: {})\n\n\
         ## Notes\n{}\n",
        b.building_id,
        b.data_available,
        b.validate_ms,
        b.equipment_count,
        b.csv_scan_ms,
        b.ingest_ms,
        b.ingest_rows,
        b.rules_ms,
        b.rules_run,
        b.rules_succeeded,
        b.rules_failed,
        b.notes
            .iter()
            .map(|n| format!("- {n}"))
            .collect::<Vec<_>>()
            .join("\n")
    )
}
