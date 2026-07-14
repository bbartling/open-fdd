//! Canonical MQTT topic helpers.

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

#[derive(Debug, Clone)]
pub struct TopicBuilder {
    pub site_id: String,
    pub edge_id: String,
}

impl TopicBuilder {
    pub fn new(site_id: impl Into<String>, edge_id: impl Into<String>) -> Self {
        Self {
            site_id: site_id.into(),
            edge_id: edge_id.into(),
        }
    }

    pub fn base(&self) -> String {
        format!("openfdd/v1/sites/{}/edges/{}", self.site_id, self.edge_id)
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

    /// ACL pattern for central subscriber (subscribe all for site, publish commands).
    pub fn central_acl_patterns(&self) -> (Vec<String>, Vec<String>) {
        let site = format!("openfdd/v1/sites/{}/#", self.site_id);
        let publish = vec![format!(
            "openfdd/v1/sites/{}/edges/{}/commands/#",
            self.site_id, self.edge_id
        )];
        let subscribe = vec![site];
        (publish, subscribe)
    }
}

fn protocol_slug(p: Protocol) -> &'static str {
    match p {
        Protocol::Bacnet => "bacnet",
        Protocol::Modbus => "modbus",
        Protocol::Haystack => "haystack",
        Protocol::JsonApi => "json_api",
        Protocol::Weather => "weather",
        Protocol::Mixed => "mixed",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn telemetry_topic_shape() {
        let t = TopicBuilder::new("lab", "pi-1");
        assert_eq!(
            t.topic(TopicKind::Telemetry, Some(Protocol::Bacnet)),
            "openfdd/v1/sites/lab/edges/pi-1/telemetry/bacnet"
        );
    }
}
