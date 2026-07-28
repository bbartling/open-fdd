//! Metering aggregations — schema stub (full port in progress).
//!
//! No finance / EnergyPlus calibration in central.

use super::{empty_stub, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_METERING};

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_METERING);
    let mut env = empty_stub(&qv, &req.query, "metering");
    warnings.append(&mut env.warnings);
    env.warnings = warnings;
    env
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analytics::AnalyticsQuery;

    #[test]
    fn stub_returns_expected_query_version() {
        let env = handle(&AnalyticsRequest {
            query: AnalyticsQuery::default(),
            ..Default::default()
        });
        assert_eq!(env.query_version, QV_METERING);
        assert!(env.rows.is_empty());
        assert!(env.warnings.iter().any(|w| w.contains("in progress")));
    }
}
