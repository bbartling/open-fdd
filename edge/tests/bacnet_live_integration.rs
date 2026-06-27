//! Opt-in live BACnet integration — device instance from env only (no bench defaults).
//!
//! ```bash
//! OPENFDD_BACNET_INTEGRATION=1 \
//! OPENFDD_BACNET_INTEGRATION_DEVICE=<device_instance> \
//! OPENFDD_BACNET_BIND=<ip/mask:47808> \
//! OPENFDD_BACNET_DISCOVER_LOW=<device_instance> \
//! OPENFDD_BACNET_DISCOVER_HIGH=<device_instance> \
//! cargo test -p open_fdd_edge_prototype --test bacnet_live_integration -- --ignored --nocapture
//! ```

use open_fdd_edge_prototype::drivers::bacnet;
use serde_json::json;
use std::env;

fn integration_device_instance() -> Option<u32> {
    env::var("OPENFDD_BACNET_INTEGRATION_DEVICE")
        .ok()
        .and_then(|v| v.parse().ok())
        .or_else(|| {
            env::var("OPENFDD_BACNET_DISCOVER_LOW")
                .ok()
                .and_then(|v| v.parse().ok())
        })
        .filter(|&inst| inst > 0)
}

fn integration_enabled() -> bool {
    env::var("OPENFDD_BACNET_INTEGRATION")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
        && integration_device_instance().is_some()
        && env::var("OPENFDD_BACNET_BIND")
            .map(|v| !v.trim().is_empty())
            .unwrap_or(false)
}

#[test]
#[ignore = "requires OPENFDD_BACNET_INTEGRATION=1, OPENFDD_BACNET_INTEGRATION_DEVICE, and OPENFDD_BACNET_BIND"]
fn discover_configured_device_object_list() {
    if !integration_enabled() {
        return;
    }
    env::set_var("OPENFDD_BACNET_MODE", "live");
    let device = integration_device_instance().expect("integration device");

    let out = bacnet::point_discovery_value(&json!({ "device_instance": device }));
    assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true), "{out}");
    let points = out
        .get("points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    assert!(
        !points.is_empty(),
        "expected object-list points from configured device {device}"
    );
}

#[test]
#[ignore = "requires OPENFDD_BACNET_INTEGRATION=1, OPENFDD_BACNET_INTEGRATION_DEVICE, and OPENFDD_BACNET_BIND"]
fn rpm_poll_present_values_on_configured_device() {
    if !integration_enabled() {
        return;
    }
    env::set_var("OPENFDD_BACNET_MODE", "live");
    let device = integration_device_instance().expect("integration device");

    let discovery = bacnet::point_discovery_value(&json!({ "device_instance": device }));
    assert_eq!(
        discovery.get("ok").and_then(|v| v.as_bool()),
        Some(true),
        "{discovery}"
    );

    let poll = bacnet::poll_cycle_value();
    assert_eq!(poll.get("ok").and_then(|v| v.as_bool()), Some(true), "{poll}");
}
