//! Versioned service identity and deployment vocabulary shared by connector
//! processes and Central's capability hello.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::capabilities::ServiceVersion;

pub const SERVICE_IDENTITY_CONTRACT_V1: &str = "openfdd.connector.service-identity.v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum ConnectorServiceProfile {
    /// The process profile allowed to own BACnet UDP, configured Modbus/TCP,
    /// polling, and the read-only priority scanner.
    BacnetModbus,
    /// Outbound authenticated Haystack HTTP only. It never owns BACnet UDP.
    Haystack,
}

impl ConnectorServiceProfile {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BacnetModbus => "bacnet_modbus",
            Self::Haystack => "haystack",
        }
    }

    pub const fn service_name(self) -> &'static str {
        match self {
            Self::BacnetModbus => "openfdd-bacnet-modbus",
            Self::Haystack => "openfdd-haystack",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum RecipeKind {
    CloudHub,
    EdgeBacnetModbus,
    EdgeHaystack,
    StandaloneBacnetModbus,
    StandaloneHaystack,
}

impl RecipeKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CloudHub => "cloud_hub",
            Self::EdgeBacnetModbus => "edge_bacnet_modbus",
            Self::EdgeHaystack => "edge_haystack",
            Self::StandaloneBacnetModbus => "standalone_bacnet_modbus",
            Self::StandaloneHaystack => "standalone_haystack",
        }
    }

    pub fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "cloud" | "cloud_hub" | "central" => Ok(Self::CloudHub),
            "edge" | "edge_bacnet_modbus" | "bacnet_modbus" => Ok(Self::EdgeBacnetModbus),
            "edge_haystack" | "haystack" => Ok(Self::EdgeHaystack),
            "standalone" | "standalone_bacnet_modbus" => Ok(Self::StandaloneBacnetModbus),
            "standalone_haystack" => Ok(Self::StandaloneHaystack),
            other => Err(format!(
                "invalid recipe '{other}' (expected cloud_hub | edge_bacnet_modbus | edge_haystack | standalone_bacnet_modbus | standalone_haystack)"
            )),
        }
    }

    pub fn from_env() -> Result<Self, String> {
        std::env::var("OPENFDD_RECIPE")
            .or_else(|_| std::env::var("OPENFDD_BUILD_RECIPE"))
            .map(|value| Self::parse(&value))
            .unwrap_or(Ok(Self::CloudHub))
    }

    pub const fn permits_profile(self, profile: ConnectorServiceProfile) -> bool {
        matches!(
            (self, profile),
            (
                Self::EdgeBacnetModbus,
                ConnectorServiceProfile::BacnetModbus
            ) | (Self::EdgeHaystack, ConnectorServiceProfile::Haystack)
                | (
                    Self::StandaloneBacnetModbus,
                    ConnectorServiceProfile::BacnetModbus
                )
                | (Self::StandaloneHaystack, ConnectorServiceProfile::Haystack)
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ServiceIdentity {
    pub schema: String,
    pub service: String,
    pub profile: ConnectorServiceProfile,
    pub version: ServiceVersion,
    pub process_id: u32,
    pub started_at: DateTime<Utc>,
    pub recipe: RecipeKind,
}

impl ServiceIdentity {
    pub fn new(
        profile: ConnectorServiceProfile,
        build: impl Into<String>,
        recipe: RecipeKind,
    ) -> Self {
        Self {
            schema: SERVICE_IDENTITY_CONTRACT_V1.into(),
            service: profile.service_name().into(),
            profile,
            version: ServiceVersion {
                service: profile.service_name().into(),
                build: build.into(),
                contract: SERVICE_IDENTITY_CONTRACT_V1.into(),
            },
            process_id: std::process::id(),
            started_at: Utc::now(),
            recipe,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema != SERVICE_IDENTITY_CONTRACT_V1
            || self.version.contract != SERVICE_IDENTITY_CONTRACT_V1
        {
            return Err("unsupported service identity contract".into());
        }
        if self.service != self.profile.service_name()
            || self.version.service != self.profile.service_name()
        {
            return Err("service identity/profile mismatch".into());
        }
        if self.version.build.trim().is_empty() || self.version.build.len() > 128 {
            return Err("service identity build is required and bounded".into());
        }
        if !self
            .version
            .build
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-' | '+'))
        {
            return Err("service identity build contains unsafe characters".into());
        }
        if !self.recipe.permits_profile(self.profile) {
            return Err("recipe does not permit this connector profile".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profiles_have_separate_process_names() {
        assert_ne!(
            ConnectorServiceProfile::BacnetModbus.service_name(),
            ConnectorServiceProfile::Haystack.service_name()
        );
        assert!(RecipeKind::EdgeBacnetModbus.permits_profile(ConnectorServiceProfile::BacnetModbus));
        assert!(!RecipeKind::EdgeBacnetModbus.permits_profile(ConnectorServiceProfile::Haystack));
    }

    #[test]
    fn identity_is_versioned_and_profile_bound() {
        let identity = ServiceIdentity::new(
            ConnectorServiceProfile::Haystack,
            "3.5.60+test",
            RecipeKind::EdgeHaystack,
        );
        identity.validate().unwrap();
        let json = serde_json::to_value(identity).unwrap();
        assert_eq!(json["profile"], "haystack");
        assert_eq!(json["schema"], SERVICE_IDENTITY_CONTRACT_V1);
    }

    #[test]
    fn cloud_recipe_rejects_connector_identity() {
        let identity = ServiceIdentity::new(
            ConnectorServiceProfile::BacnetModbus,
            "3.5.60+test",
            RecipeKind::CloudHub,
        );
        assert!(identity.validate().is_err());
    }
}
