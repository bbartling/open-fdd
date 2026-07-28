//! RCx AHU / VAV analytics — schema stubs (full port in progress).

use super::{
    empty_stub, resolve_query_version, AnalyticsEnvelope, AnalyticsRequest, QV_RCX_AHU, QV_RCX_VAV,
};

pub fn handle_ahu(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_RCX_AHU);
    let mut env = empty_stub(&qv, &req.query, "rcx/ahu");
    warnings.extend(env.warnings.drain(..));
    env.warnings = warnings;
    env
}

pub fn handle_vav(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_RCX_VAV);
    let mut env = empty_stub(&qv, &req.query, "rcx/vav");
    warnings.extend(env.warnings.drain(..));
    env.warnings = warnings;
    env
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analytics::AnalyticsQuery;

    #[test]
    fn ahu_and_vav_query_versions() {
        let req = AnalyticsRequest {
            query: AnalyticsQuery::default(),
            ..Default::default()
        };
        assert_eq!(handle_ahu(&req).query_version, QV_RCX_AHU);
        assert_eq!(handle_vav(&req).query_version, QV_RCX_VAV);
    }
}
