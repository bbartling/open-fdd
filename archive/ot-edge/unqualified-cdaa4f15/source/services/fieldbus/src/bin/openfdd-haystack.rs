//! Standalone outbound Haystack connector process.

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    openfdd_fieldbus::split::run_haystack().await
}
