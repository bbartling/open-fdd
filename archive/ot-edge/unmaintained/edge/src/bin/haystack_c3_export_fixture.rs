//! Export synthetic C3 fixture Turtle for independent RDFLib/SPARQL KATs.
//!
//! ```bash
//! cargo run -p open_fdd_edge_prototype --bin haystack_c3_export_fixture
//! ```

use std::path::PathBuf;

fn main() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let meta = root.join("scripts/fixtures/haystack_rdf/synthetic_point_metadata_v1.json");
    let inv = root.join("scripts/fixtures/haystack_rdf/synthetic_mapping_inventory.json");
    let out_dir = root.join("scripts/fixtures/haystack_rdf/generated");
    let ttl = out_dir.join("c3_projection.ttl");
    let report = out_dir.join("c3_projection_report.json");
    open_fdd_edge_prototype::csv_ingest::haystack_projection::export_fixture_projection(
        &meta,
        Some(&inv),
        &ttl,
        &report,
    )
    .unwrap_or_else(|e| {
        eprintln!("haystack_c3_export_fixture failed: {e}");
        std::process::exit(1);
    });
    println!("wrote {}", ttl.display());
    println!("wrote {}", report.display());
}
