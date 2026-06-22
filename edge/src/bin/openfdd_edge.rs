//! Open-FDD edge CLI (auth init, future ops commands).

use clap::{Parser, Subcommand};
use open_fdd_edge_prototype::auth::env_file::{
    default_auth_env_path, generate_auth_env, print_env_summary, GenerateOptions,
};

#[derive(Parser)]
#[command(name = "openfdd_edge", about = "Open-FDD Rust edge utilities")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Authentication utilities
    Auth {
        #[command(subcommand)]
        command: AuthCommands,
    },
}

#[derive(Subcommand)]
enum AuthCommands {
    /// Generate workspace/auth.env.local if missing
    Init {
        #[arg(long)]
        force: bool,
        #[arg(long)]
        show_secrets: bool,
        #[arg(long)]
        path: Option<std::path::PathBuf>,
    },
}

fn main() -> std::io::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Auth { command } => match command {
            AuthCommands::Init {
                force,
                show_secrets,
                path,
            } => {
                let path = path.unwrap_or_else(default_auth_env_path);
                let result = generate_auth_env(&GenerateOptions {
                    path: path.clone(),
                    force,
                    show_secrets,
                })?;
                if result.created {
                    eprintln!("created {}", path.display());
                } else {
                    eprintln!("kept existing {}", path.display());
                }
                print_env_summary(&result.contents, show_secrets);
                Ok(())
            }
        },
    }
}
