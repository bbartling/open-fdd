//! T1406: overlay cadence validation and portal history_mode resolution.

use open_fdd_edge_prototype::csv_ingest::model_overlay::EngineerPointOverlayEntry;

use super::committed_model::resolve_point_map_binding;

fn overlay(cadence_secs: Option<u64>) -> EngineerPointOverlayEntry {
    EngineerPointOverlayEntry {
        unit: None,
        quantity: None,
        cadence_secs,
        primary_reference: None,
    }
}

#[test]
fn t1406_overlay_cadence_out_of_range_is_an_error() {
    for bad in [0_u64, 86_401] {
        let err = resolve_point_map_binding(None, None, Some(&overlay(Some(bad))))
            .expect_err("cadence out of range");
        assert!(err.contains("cadence_secs"), "unexpected message: {err}");
    }
}

#[test]
fn t1406_portal_interval_without_overlay_cadence_keeps_history_mode() {
    let binding = resolve_point_map_binding(None, Some("interval"), None).expect("resolve");
    assert_eq!(binding.history_mode.as_deref(), Some("interval"));
    assert!(binding.cadence_secs.is_none());
}

#[test]
fn t1406_overlay_cadence_overrides_portal_interval() {
    let binding = resolve_point_map_binding(None, Some("interval"), Some(&overlay(Some(300))))
        .expect("resolve");
    assert_eq!(binding.history_mode.as_deref(), Some("interval"));
    assert_eq!(binding.cadence_secs, Some(300));
}
