//! Canonical MQTT topic helpers.
//!
//! Wave L L3 topic shapes (feature-flagged):
//! - Mode OFF / no tenant: `openfdd/v1/sites/{site}/edges/{edge}/…` (today)
//! - Mode ON: `openfdd/v1/tenants/{tid}/buildings/{bid}/edges/{eid}/…`
//!
//! Identity provenance: clients must not invent building/tenant labels that
//! disagree with the authenticated topic path (central ingest already rejects
//! envelope site/edge ≠ topic).

use crate::envelope::Protocol;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TopicKind {
    Telemetry,
    Metadata,
    Discovery,
    Status,
    Commands,
    Acks,
}

/// Parsed Open-FDD MQTT topic identity (legacy site or tenant/building).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TopicIdentity {
    /// Present only for the multi-tenant namespace.
    pub tenant_id: Option<String>,
    /// Legacy `site_id`, or building id under `tenants/{tid}/buildings/{bid}`.
    pub building_id: String,
    pub edge_id: String,
    pub kind: TopicKind,
    pub protocol: Option<String>,
}

impl TopicIdentity {
    /// Alias for building_id (legacy callers used `site_id`).
    pub fn site_id(&self) -> &str {
        &self.building_id
    }

    /// True when the topic uses the Wave L tenant namespace.
    pub fn is_tenant_scoped(&self) -> bool {
        self.tenant_id.is_some()
    }
}

#[derive(Debug, Clone)]
pub struct TopicBuilder {
    pub site_id: String,
    pub edge_id: String,
    /// When set, emit `openfdd/v1/tenants/{tid}/buildings/{site}/edges/{edge}/…`.
    pub tenant_id: Option<String>,
}

impl TopicBuilder {
    pub fn new(site_id: impl Into<String>, edge_id: impl Into<String>) -> Self {
        Self {
            site_id: site_id.into(),
            edge_id: edge_id.into(),
            tenant_id: None,
        }
    }

    /// Multi-tenant topic builder (`OPENFDD_MULTI_TENANT` ON paths).
    pub fn with_tenant(
        tenant_id: impl Into<String>,
        building_id: impl Into<String>,
        edge_id: impl Into<String>,
    ) -> Self {
        Self {
            site_id: building_id.into(),
            edge_id: edge_id.into(),
            tenant_id: Some(tenant_id.into()),
        }
    }

    pub fn base(&self) -> String {
        match self.tenant_id.as_deref() {
            Some(tid) => format!(
                "openfdd/v1/tenants/{tid}/buildings/{}/edges/{}",
                self.site_id, self.edge_id
            ),
            None => format!("openfdd/v1/sites/{}/edges/{}", self.site_id, self.edge_id),
        }
    }

    pub fn topic(&self, kind: TopicKind, protocol: Option<Protocol>) -> String {
        let base = self.base();
        match kind {
            TopicKind::Status => format!("{base}/status"),
            TopicKind::Telemetry => {
                let p = protocol_slug(protocol.expect("protocol required"));
                format!("{base}/telemetry/{p}")
            }
            TopicKind::Metadata => {
                let p = protocol_slug(protocol.expect("protocol required"));
                format!("{base}/metadata/{p}")
            }
            TopicKind::Discovery => {
                let p = protocol_slug(protocol.expect("protocol required"));
                format!("{base}/discovery/{p}")
            }
            TopicKind::Commands => {
                let p = protocol_slug(protocol.expect("protocol required"));
                format!("{base}/commands/{p}")
            }
            TopicKind::Acks => {
                let p = protocol_slug(protocol.expect("protocol required"));
                format!("{base}/acks/{p}")
            }
        }
    }

    /// ACL pattern for an edge certificate (publish telemetry/status/acks, subscribe commands).
    pub fn edge_acl_patterns(&self) -> (Vec<String>, Vec<String>) {
        let base = self.base();
        let publish = vec![
            format!("{base}/telemetry/#"),
            format!("{base}/metadata/#"),
            format!("{base}/discovery/#"),
            format!("{base}/status"),
            format!("{base}/acks/#"),
        ];
        let subscribe = vec![format!("{base}/commands/#")];
        (publish, subscribe)
    }

    /// ACL pattern for central subscriber (subscribe all for site/tenant, publish commands).
    pub fn central_acl_patterns(&self) -> (Vec<String>, Vec<String>) {
        let subscribe = match self.tenant_id.as_deref() {
            Some(tid) => format!("openfdd/v1/tenants/{tid}/buildings/{}/#", self.site_id),
            None => format!("openfdd/v1/sites/{}/#", self.site_id),
        };
        let publish = format!("{}/commands/#", self.base());
        (vec![publish], vec![subscribe])
    }
}

/// Parse legacy or tenant-scoped Open-FDD topics.
pub fn parse_topic(topic: &str) -> Option<TopicIdentity> {
    let parts: Vec<&str> = topic.split('/').collect();
    if parts.len() < 6 || parts[0] != "openfdd" || parts[1] != "v1" {
        return None;
    }

    let (tenant_id, building_id, edge_id, rest) = match parts[2] {
        "sites" if parts.len() >= 6 && parts[4] == "edges" => (
            None,
            parts[3].to_string(),
            parts[5].to_string(),
            &parts[6..],
        ),
        "tenants" if parts.len() >= 8 && parts[4] == "buildings" && parts[6] == "edges" => (
            Some(parts[3].to_string()),
            parts[5].to_string(),
            parts[7].to_string(),
            &parts[8..],
        ),
        _ => return None,
    };

    let kind = match rest.first().copied() {
        Some("telemetry") => TopicKind::Telemetry,
        Some("metadata") => TopicKind::Metadata,
        Some("discovery") => TopicKind::Discovery,
        Some("status") if rest.len() == 1 => TopicKind::Status,
        Some("acks") => TopicKind::Acks,
        Some("commands") => TopicKind::Commands,
        _ => return None,
    };
    let protocol = rest.get(1).map(|s| (*s).to_string());
    Some(TopicIdentity {
        tenant_id,
        building_id,
        edge_id,
        kind,
        protocol,
    })
}

/// Reject payload labels that disagree with the authenticated topic path.
pub fn payload_matches_topic(topic: &TopicIdentity, site_id: &str, edge_id: &str) -> bool {
    topic.building_id == site_id && topic.edge_id == edge_id
}

fn protocol_slug(p: Protocol) -> &'static str {
    match p {
        Protocol::Bacnet => "bacnet",
        Protocol::Modbus => "modbus",
        Protocol::Haystack => "haystack",
        Protocol::Rest => "rest",
        Protocol::JsonApi => "json_api",
        Protocol::Weather => "weather",
        Protocol::Mixed => "mixed",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn telemetry_topic_shape_legacy() {
        let t = TopicBuilder::new("lab", "pi-1");
        assert_eq!(
            t.topic(TopicKind::Telemetry, Some(Protocol::Bacnet)),
            "openfdd/v1/sites/lab/edges/pi-1/telemetry/bacnet"
        );
    }

    #[test]
    fn telemetry_topic_shape_tenant() {
        let t = TopicBuilder::with_tenant("acme", "bldg2", "pi-1");
        assert_eq!(
            t.base(),
            "openfdd/v1/tenants/acme/buildings/bldg2/edges/pi-1"
        );
        assert_eq!(
            t.topic(TopicKind::Telemetry, Some(Protocol::Bacnet)),
            "openfdd/v1/tenants/acme/buildings/bldg2/edges/pi-1/telemetry/bacnet"
        );
        let (pub_p, sub_p) = t.edge_acl_patterns();
        assert!(pub_p[0].starts_with("openfdd/v1/tenants/acme/buildings/bldg2/edges/pi-1/"));
        assert_eq!(
            sub_p[0],
            "openfdd/v1/tenants/acme/buildings/bldg2/edges/pi-1/commands/#"
        );
    }

    #[test]
    fn parse_legacy_and_tenant() {
        let legacy = parse_topic("openfdd/v1/sites/lab/edges/pi-1/telemetry/bacnet").unwrap();
        assert_eq!(legacy.tenant_id, None);
        assert_eq!(legacy.building_id, "lab");
        assert_eq!(legacy.edge_id, "pi-1");
        assert_eq!(legacy.kind, TopicKind::Telemetry);

        let scoped =
            parse_topic("openfdd/v1/tenants/acme/buildings/bldg2/edges/pi-1/status").unwrap();
        assert_eq!(scoped.tenant_id.as_deref(), Some("acme"));
        assert_eq!(scoped.building_id, "bldg2");
        assert!(scoped.is_tenant_scoped());
        assert_eq!(scoped.kind, TopicKind::Status);
    }

    #[test]
    fn identity_provenance_helper() {
        let id = parse_topic("openfdd/v1/sites/bldg2/edges/pi-1/telemetry/json_api").unwrap();
        assert!(payload_matches_topic(&id, "bldg2", "pi-1"));
        assert!(!payload_matches_topic(&id, "other", "pi-1"));
        assert!(!payload_matches_topic(&id, "bldg2", "other"));
    }
}
