//! CLI: openfdd-provision — generate MQTTS edge kits.

use std::path::PathBuf;

use clap::{Parser, Subcommand};
use openfdd_mqtt::{provision_edge_kit, ProvisionRequest};

#[derive(Parser, Debug)]
#[command(
    name = "openfdd-provision",
    about = "Provision Open-FDD MQTTS edge kits"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Emit a downloadable edge kit (ca.pem + cert + key + edge.json). Never includes CA private key.
    Edge {
        #[arg(long)]
        site_id: String,
        #[arg(long)]
        edge_id: String,
        #[arg(long, default_value = "127.0.0.1")]
        broker_host: String,
        #[arg(long, default_value_t = 8883)]
        broker_port: u16,
        #[arg(long, default_value = "./deploy/mqtt")]
        out_dir: PathBuf,
        #[arg(long)]
        ca_dir: Option<PathBuf>,
    },
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Commands::Edge {
            site_id,
            edge_id,
            broker_host,
            broker_port,
            out_dir,
            ca_dir,
        } => {
            let result = provision_edge_kit(&ProvisionRequest {
                out_dir,
                site_id,
                edge_id,
                broker_host,
                broker_port,
                ca_dir,
            })?;
            println!("kit_dir={}", result.kit_dir.display());
            println!("edge_config={}", result.edge_config.display());
            println!("mosquitto_acl={}", result.mosquitto_acl.display());
            println!("ca_pem={}", result.ca_pem.display());
            Ok(())
        }
    }
}
