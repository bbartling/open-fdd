//! Open-FDD edge CLI — auth bootstrap, TLS certs, security setup.

use clap::{Parser, Subcommand};
use open_fdd_edge_prototype::auth::env_file::{
    default_auth_env_path, generate_auth_env, print_env_summary, print_generated_credentials,
    rotate_auth_env, write_bootstrap_credentials_once, GenerateOptions, RotateOptions,
};
use open_fdd_edge_prototype::auth::password::hash_password;
use open_fdd_edge_prototype::tls::{default_cert_dir, generate_self_signed, TlsGenerateOptions};
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "openfdd-edge", about = "Open-FDD Rust edge utilities")]
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
    /// TLS certificate utilities
    Tls {
        #[command(subcommand)]
        command: TlsCommands,
    },
    /// One-shot security bootstrap (auth env + optional TLS certs)
    Bootstrap {
        #[command(subcommand)]
        command: BootstrapCommands,
    },
}

#[derive(Subcommand)]
enum AuthCommands {
    /// Generate workspace/auth.env.local (alias: init)
    Generate {
        #[arg(long)]
        force: bool,
        #[arg(long)]
        show_secrets: bool,
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// Alias for generate
    Init {
        #[arg(long)]
        force: bool,
        #[arg(long)]
        show_secrets: bool,
        #[arg(long)]
        path: Option<PathBuf>,
    },
    /// Rotate passwords and/or auth secret
    Rotate {
        #[arg(long)]
        all: bool,
        #[arg(long)]
        role: Option<String>,
        #[arg(long)]
        show_secrets: bool,
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// Print bcrypt hash for IT-managed password setup
    HashPassword { password: String },
}

#[derive(Subcommand)]
enum TlsCommands {
    /// Generate self-signed cert.pem/key.pem for Caddy TLS mode
    Generate {
        #[arg(long, default_value = "openfdd.local")]
        cn: String,
        #[arg(long)]
        out: Option<PathBuf>,
        #[arg(long)]
        lan_ip: Option<String>,
    },
}

#[derive(Subcommand)]
enum BootstrapCommands {
    /// Generate auth env + TLS certs
    Security {
        #[arg(long)]
        force: bool,
        #[arg(long)]
        show_secrets: bool,
        #[arg(long)]
        auth_out: Option<PathBuf>,
        #[arg(long)]
        cert_out: Option<PathBuf>,
        #[arg(long, default_value = "openfdd.local")]
        cn: String,
        #[arg(long)]
        lan_ip: Option<String>,
        #[arg(long)]
        skip_tls: bool,
    },
}

fn auth_path(out: Option<PathBuf>) -> PathBuf {
    out.unwrap_or_else(default_auth_env_path)
}

fn run_generate(path: PathBuf, force: bool, show_secrets: bool) -> std::io::Result<()> {
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
    print_generated_credentials(&result.plaintext_passwords, show_secrets);
    if show_secrets {
        if let Some(handoff) =
            write_bootstrap_credentials_once(&path, &result.plaintext_passwords)?
        {
            eprintln!(
                "wrote one-time credential handoff {} (delete after saving passwords)",
                handoff.display()
            );
        }
    }
    Ok(())
}

fn main() -> std::io::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Auth { command } => match command {
            AuthCommands::Generate {
                force,
                show_secrets,
                out,
            }
            | AuthCommands::Init {
                force,
                show_secrets,
                path: out,
            } => run_generate(auth_path(out), force, show_secrets),
            AuthCommands::Rotate {
                all,
                role,
                show_secrets,
                out,
            } => {
                let path = auth_path(out);
                let result = rotate_auth_env(&RotateOptions {
                    path: path.clone(),
                    all,
                    role,
                    show_secrets,
                })?;
                eprintln!("rotated {}", path.display());
                print_env_summary(&result.contents, show_secrets);
                print_generated_credentials(&result.plaintext_passwords, show_secrets);
                if show_secrets {
                    if let Some(handoff) = write_bootstrap_credentials_once(
                        &path,
                        &result.plaintext_passwords,
                    )? {
                        eprintln!(
                            "wrote one-time credential handoff {} (delete after saving passwords)",
                            handoff.display()
                        );
                    }
                }
                Ok(())
            }
            AuthCommands::HashPassword { password } => {
                let hashed = hash_password(&password)
                    .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;
                println!("{hashed}");
                Ok(())
            }
        },
        Commands::Tls { command } => match command {
            TlsCommands::Generate { cn, out, lan_ip } => {
                let out_dir = out.unwrap_or_else(default_cert_dir);
                let result = generate_self_signed(&TlsGenerateOptions {
                    cn,
                    out_dir,
                    lan_ip,
                })
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
                eprintln!("wrote {}", result.cert_path.display());
                eprintln!("wrote {}", result.key_path.display());
                Ok(())
            }
        },
        Commands::Bootstrap { command } => match command {
            BootstrapCommands::Security {
                force,
                show_secrets,
                auth_out,
                cert_out,
                cn,
                lan_ip,
                skip_tls,
            } => {
                let auth = auth_path(auth_out);
                run_generate(auth, force, show_secrets)?;
                if !skip_tls {
                    let out_dir = cert_out.unwrap_or_else(default_cert_dir);
                    let result = generate_self_signed(&TlsGenerateOptions {
                        cn,
                        out_dir,
                        lan_ip,
                    })
                    .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
                    eprintln!("TLS cert: {}", result.cert_path.display());
                    eprintln!("TLS key:  {}", result.key_path.display());
                }
                Ok(())
            }
        },
    }
}
