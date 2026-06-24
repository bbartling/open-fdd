//! Role-based access control helpers.

use super::config::Principal;

pub fn role_allowed(principal: &Principal, allowed: &[&str]) -> bool {
    allowed.contains(&principal.role.as_str())
}

pub fn is_read_only_role(role: &str) -> bool {
    role == "operator"
}

/// Integrator-tier roles may run commissioning mutations; operator is read-only browse/export.
pub fn is_integrator_tier(role: &str) -> bool {
    matches!(role, "integrator" | "agent" | "admin")
}

pub fn is_mutation_role(role: &str) -> bool {
    is_integrator_tier(role)
}

pub fn can_write_field_bus(role: &str, approved: bool) -> bool {
    is_integrator_tier(role) && approved
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn operator_cannot_write_field_bus() {
        assert!(!can_write_field_bus("operator", true));
        assert!(can_write_field_bus("agent", true));
        assert!(can_write_field_bus("integrator", true));
        assert!(!can_write_field_bus("integrator", false));
    }
}
