//! Mechanical cooling analytics — schema stub (full port in progress).
//!
//! Evidence hierarchy (pump/valve alone ≠ compressor) will be enforced in the
//! DataFusion port — see MILESTONE_C_ANALYTICS_MATRIX.md.

use super::{
    empty_stub, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_MECHANICAL_COOLING,
};

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_MECHANICAL_COOLING);
    let mut env = empty_stub(&qv, &req.query, "mechanical_cooling");
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
        assert_eq!(env.query_version, QV_MECHANICAL_COOLING);
        assert!(env.rows.is_empty());
        assert!(env.warnings.iter().any(|w| w.contains("in progress")));
    }
}
