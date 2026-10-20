//! Typed provider failures. Display and health only carry a stable code,
//! optional HTTP status, and a request id — never vendor or token bodies.

use std::fmt;

use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProviderErrorCode {
    AuthNotConfigured,
    AuthFailed,
    Forbidden,
    Throttled,
    RedirectRejected,
    Transport,
    DeadlineExceeded,
    BodyTooLarge,
    Contract,
    InvalidSample,
    Persistence,
    Config,
    NotImplemented,
    #[expect(
        dead_code,
        reason = "hourly partial pages use FetchError; the code stays on the provider contract"
    )]
    HistoryIncomplete,
}

impl ProviderErrorCode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AuthNotConfigured => "auth_not_configured",
            Self::AuthFailed => "auth_failed",
            Self::Forbidden => "forbidden",
            Self::Throttled => "throttled",
            Self::RedirectRejected => "redirect_rejected",
            Self::Transport => "transport",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::BodyTooLarge => "body_too_large",
            Self::Contract => "contract",
            Self::InvalidSample => "invalid_sample",
            Self::Persistence => "persistence",
            Self::Config => "config_invalid",
            Self::NotImplemented => "not_implemented",
            Self::HistoryIncomplete => "history_incomplete",
        }
    }

    pub fn retryable(self) -> bool {
        matches!(
            self,
            Self::Throttled | Self::Transport | Self::DeadlineExceeded | Self::Persistence
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderError {
    pub code: ProviderErrorCode,
    pub http_status: Option<u16>,
    pub request_id: String,
    pub retry_after_secs: Option<u64>,
}

impl ProviderError {
    pub fn new(code: ProviderErrorCode) -> Self {
        Self {
            code,
            http_status: None,
            request_id: Uuid::new_v4().to_string(),
            retry_after_secs: None,
        }
    }

    pub fn with_status(mut self, status: u16) -> Self {
        self.http_status = Some(status);
        self
    }

    pub fn with_retry_after(mut self, secs: u64) -> Self {
        self.retry_after_secs = Some(secs);
        self
    }

    pub fn auth_not_configured() -> Self {
        Self::new(ProviderErrorCode::AuthNotConfigured)
    }

    pub fn contract() -> Self {
        Self::new(ProviderErrorCode::Contract)
    }

    pub fn transport() -> Self {
        Self::new(ProviderErrorCode::Transport)
    }

    pub fn persistence() -> Self {
        Self::new(ProviderErrorCode::Persistence)
    }

    pub fn config() -> Self {
        Self::new(ProviderErrorCode::Config)
    }
}

impl fmt::Display for ProviderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} request_id={}", self.code.as_str(), self.request_id)?;
        if let Some(status) = self.http_status {
            write!(f, " http_status={status}")?;
        }
        if let Some(secs) = self.retry_after_secs {
            write!(f, " retry_after_secs={secs}")?;
        }
        if self.code.retryable() {
            write!(f, " retryable=true")?;
        }
        Ok(())
    }
}

/// First token of an operator message, restricted to a safe code alphabet.
pub fn safe_operator_code(message: &str) -> String {
    let token = message
        .split_whitespace()
        .next()
        .unwrap_or("provider_error");
    if token.len() <= 64
        && !token.is_empty()
        && token.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
    {
        token.to_string()
    } else {
        "provider_error".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn display_omits_vendor_body() {
        let err = ProviderError::new(ProviderErrorCode::AuthFailed).with_status(401);
        let text = err.to_string();
        assert!(text.contains("auth_failed"));
        assert!(text.contains("http_status=401"));
        assert!(!text.contains("secret"));
        assert!(!text.contains('{'));
    }

    #[test]
    fn unsafe_message_collapses_to_generic_code() {
        let canary = "CANARY-TOKEN-VALUE leaked body";
        assert_eq!(safe_operator_code(canary), "provider_error");
        assert_eq!(
            safe_operator_code("auth_not_configured request_id=abc"),
            "auth_not_configured"
        );
    }
}
