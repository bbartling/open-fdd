//! Schedule / occupancy analytics — schema stub (full port in progress).

use super::{empty_stub, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_SCHEDULE};

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_SCHEDULE);
    let mut env = empty_stub(&qv, &req.query, "schedule");
    warnings.extend(env.warnings.drain(..));
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
        assert_eq!(env.query_version, QV_SCHEDULE);
        assert!(env.equipment.is_empty());
        assert!(env.warnings.iter().any(|w| w.contains("in progress")));
    }
}
