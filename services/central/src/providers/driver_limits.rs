//! Provider history driver limits advertised to the ingest queue planner.

use chrono::Duration;

use super::http_policy::{
    MAX_HISTORY_WINDOW, MAX_SAMPLES_PER_RESPONSE, MAX_UUIDS_PER_REQUEST, MAX_UUIDS_TOTAL,
};

/// Bounded history read contract for one provider transport.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HistoryDriverLimits {
    pub max_history_span: Duration,
    pub max_points_per_request: usize,
    pub max_points_total: usize,
    pub max_samples_per_response: usize,
    pub supports_paging: bool,
}

impl HistoryDriverLimits {
    pub const fn nf_portal() -> Self {
        Self {
            max_history_span: MAX_HISTORY_WINDOW,
            max_points_per_request: MAX_UUIDS_PER_REQUEST,
            max_points_total: MAX_UUIDS_TOTAL,
            max_samples_per_response: MAX_SAMPLES_PER_RESPONSE,
            supports_paging: true,
        }
    }
}
