//! Simulated bench 5007 DataFusion smoke integration test (CI).

use open_fdd_edge_prototype::bench::run_simulated_ci_smoke;

#[test]
fn simulated_bench5007_datafusion_smoke_passes() {
    let outcome = run_simulated_ci_smoke().expect("smoke run");
    assert!(
        outcome.report.bacnet_proof.simulated,
        "CI run must be labeled simulated"
    );
    assert!(
        outcome
            .report
            .datafusion_meta
            .as_ref()
            .map(|m| m.execution_path.contains("DataFusion"))
            .unwrap_or(false),
        "DataFusion execution path must be recorded"
    );
    if !outcome.pass {
        panic!("smoke failed: {:?}", outcome.failure_reasons);
    }
}
