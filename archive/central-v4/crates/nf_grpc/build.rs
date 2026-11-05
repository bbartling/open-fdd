//! Compile the pinned PointManager proto. Fail closed if a vendored file
//! does not match the sha256 lines in `proto/CONTRACT.md`.

use std::fs;
use std::path::Path;

use sha2::{Digest, Sha256};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let proto_root = manifest.join("proto");
    let contract = fs::read_to_string(proto_root.join("CONTRACT.md"))?;
    verify_pin(&proto_root, &contract)?;

    let protoc = protoc_bin_vendored::protoc_bin_path()?;
    std::env::set_var("PROTOC", protoc);

    let point = proto_root.join("normalgw/hpl/v1/point.proto");
    let point_src = fs::read_to_string(&point)?;
    // Pinned proto comments are not valid rustdoc (markdown lists without
    // indentation). Omit them instead of editing the pinned bytes.
    let mut builder = tonic_build::configure()
        .build_client(true)
        .build_server(true)
        .disable_comments("normalgw.hpl.v1.PointManager");
    let mut rpc_count = 0usize;
    for name in rpc_identifiers(&point_src) {
        builder = builder.disable_comments(format!("normalgw.hpl.v1.PointManager.{name}"));
        rpc_count += 1;
    }
    if rpc_count == 0 {
        return Err("pinned point.proto has no rpc declarations".into());
    }
    let mut prost_config = tonic_build::Config::new();
    prost_config.disable_comments(["."]);
    // These two messages are not referenced by any PointManager RPC. The
    // pinned bytes stay unmodified, so the generated structs are expected dead.
    prost_config.type_attribute(
        "normalgw.hpl.v1.Data",
        "#[expect(dead_code, reason = \"not referenced by a PointManager RPC\")]",
    );
    prost_config.type_attribute(
        "normalgw.hpl.v1.LayerMigration",
        "#[expect(dead_code, reason = \"not referenced by a PointManager RPC\")]",
    );
    // Pinned `Units` variants repeat the enum name (`NO_UNITS`, `*_UNITS`).
    prost_config.enum_attribute(
        "normalgw.hpl.v1.Units",
        "#[expect(clippy::enum_variant_names, reason = \"pinned proto enum is named Units\")]",
    );
    builder.compile_protos_with_config(prost_config, &[point], &[proto_root])?;

    println!("cargo:rerun-if-changed=proto/CONTRACT.md");
    println!("cargo:rerun-if-changed=proto/normalgw/hpl/v1/point.proto");
    println!("cargo:rerun-if-changed=proto/normalgw/hpl/v1/unit.proto");
    println!("cargo:rerun-if-changed=proto/normalgw/hpl/v1/timeseries.proto");
    println!("cargo:rerun-if-changed=proto/normalgw/annotations/auth.proto");
    println!("cargo:rerun-if-changed=proto/google/api/annotations.proto");
    println!("cargo:rerun-if-changed=proto/google/api/http.proto");
    Ok(())
}

fn verify_pin(proto_root: &Path, contract: &str) -> Result<(), Box<dyn std::error::Error>> {
    let mut checked = 0usize;
    for line in contract.lines() {
        let Some(rest) = line.strip_prefix("file-sha256: ") else {
            continue;
        };
        let mut parts = rest.split_whitespace();
        let expected = parts.next().ok_or("file-sha256 line missing digest")?;
        let rel = parts.next().ok_or("file-sha256 line missing path")?;
        if parts.next().is_some() {
            return Err("file-sha256 line has extra fields".into());
        }
        if expected.len() != 64 || !expected.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("file-sha256 digest is not 64 hex chars".into());
        }
        if !is_relative_proto_path(rel) {
            return Err(format!("file-sha256 path is not a relative proto path: {rel}").into());
        }
        let bytes = fs::read(proto_root.join(rel))?;
        let actual = hex_encode(Sha256::digest(&bytes).as_slice());
        if actual != expected {
            return Err(format!("pin mismatch for {rel}: {actual} != {expected}").into());
        }
        checked += 1;
    }
    if checked != 6 {
        return Err(format!("expected 6 pinned proto files, hashed {checked}").into());
    }
    Ok(())
}

fn is_relative_proto_path(rel: &str) -> bool {
    if rel.is_empty() || rel.starts_with('/') || rel.contains('\\') {
        return false;
    }
    rel.split('/')
        .all(|part| !part.is_empty() && part != "." && part != "..")
}

fn rpc_identifiers(proto: &str) -> Vec<&str> {
    let mut names = Vec::new();
    for line in proto.lines() {
        let Some(rest) = line.trim().strip_prefix("rpc ") else {
            continue;
        };
        let Some(name) = rest.split(|c: char| c.is_whitespace() || c == '(').next() else {
            continue;
        };
        if !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            names.push(name);
        }
    }
    names
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}
