//! Portable resource discovery and process-wide compute admission (#1127 P1).
//!
//! Independent of tenant identity and storage credentials. Central and CLI may
//! share this crate without an edge/central dependency cycle.

pub mod admission;
pub mod budget;
pub mod cgroup;
pub mod pressure;

pub use admission::{
    acquire_compute, try_acquire_compute, ComputeClass, ComputePermit, DEFAULT_COMPUTE_MAX_INFLIGHT,
};
pub use budget::{ComputeBudget, ReserveEnvelopes};
pub use cgroup::{discover_capacity, CapacityDiscovery, CpuDiscovery, MemoryDiscovery};
pub use pressure::{evaluate_pressure, sample_pressure, PressureSnapshot, PressureState};
