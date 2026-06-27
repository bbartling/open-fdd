//! Walk production Rust sources and fail if bench/demo IDs appear outside allowed paths.

use open_fdd_edge_prototype::validation::audit;
use std::fs;
use std::path::{Path, PathBuf};

fn edge_crate_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn rel_for_audit(path: &Path) -> String {
    edge_crate_root()
        .parent()
        .and_then(|repo| path.strip_prefix(repo).ok())
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn should_scan(rel: &str) -> bool {
    if !rel.starts_with("edge/src/") {
        return false;
    }
    if rel.contains("/bench/") {
        return false;
    }
    if rel.ends_with("/drivers/haystack/fixture.rs")
        || rel.ends_with("/historian/arrow_table.rs")
        || rel.ends_with("/fdd/datafusion_sql.rs")
        || rel.ends_with("/validation/audit.rs")
    {
        return false;
    }
    true
}

fn collect_rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_rust_files(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            let rel = rel_for_audit(&path);
            if should_scan(&rel) {
                out.push(path);
            }
        }
    }
}

#[test]
fn production_sources_have_no_forbidden_demo_or_bench_ids() {
    let src = edge_crate_root().join("src");
    let mut files = Vec::new();
    collect_rust_files(&src, &mut files);
    assert!(
        !files.is_empty(),
        "expected Rust sources under {}",
        src.display()
    );

    let mut violations = Vec::new();
    for path in files {
        let rel = rel_for_audit(&path);
        let text = fs::read_to_string(&path).expect("read source");
        violations.extend(audit::audit_text_file(&rel, &text));
    }

    if !violations.is_empty() {
        let summary: Vec<String> = violations
            .iter()
            .take(20)
            .map(|v| {
                format!(
                    "{}:{} [{}] {}",
                    v.path.display(),
                    v.line,
                    v.pattern,
                    v.snippet
                )
            })
            .collect();
        panic!(
            "forbidden hardcoded bench/demo identifiers in production Rust:\n{}",
            summary.join("\n")
        );
    }
}
