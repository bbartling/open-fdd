//! Local BACnet server runtime removed from central.
//! Device 599999 is hosted by openfdd-fieldbus only.

use std::sync::atomic::{AtomicBool, Ordering};

static OPT: AtomicBool = AtomicBool::new(false);

pub fn optimization_enabled() -> bool {
    OPT.load(Ordering::Relaxed)
}

pub fn set_optimization_enabled(enabled: bool) -> bool {
    OPT.store(enabled, Ordering::Relaxed);
    enabled
}

pub fn start_background() {
    // no-op: UDP 47808 owned by openfdd-fieldbus
}
