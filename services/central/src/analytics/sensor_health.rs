//! Sensor health analytics — schema stub (full port in progress).

use super::{
    empty_stub, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_SENSOR_HEALTH,
};

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_SENSOR_HEALTH);
    let mut env = empty_stub(&qv, &req.query, "sensor_health");
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
        assert_eq!(env.query_version, QV_SENSOR_HEALTH);
        assert!(env.rows.is_empty());
        assert!(env.warnings.iter().any(|w| w.contains("in progress")));
    }
}
