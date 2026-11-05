//! OAT-METEO web as-of bound must come from registry/tuning — no silent defaults.

use super::oat_meteo_web_asof_bound_seconds;

#[test]
fn missing_registry_returns_error_not_default_bound() {
    let _lock = crate::test_env_lock::lock_env();
    let empty = tempfile::tempdir().expect("dir");
    let prev_root = std::env::var("OPENFDD_SQL_ROOT").ok();
    let prev_rules = std::env::var("OPENFDD_SQL_RULES_DIR").ok();
    std::env::set_var("OPENFDD_SQL_ROOT", empty.path());
    std::env::set_var("OPENFDD_SQL_RULES_DIR", empty.path());
    let err = oat_meteo_web_asof_bound_seconds().expect_err("broken registry must fail");
    let msg = err.to_string();
    assert!(!msg.contains("1500"));
    match prev_root {
        Some(v) => std::env::set_var("OPENFDD_SQL_ROOT", v),
        None => std::env::remove_var("OPENFDD_SQL_ROOT"),
    }
    match prev_rules {
        Some(v) => std::env::set_var("OPENFDD_SQL_RULES_DIR", v),
        None => std::env::remove_var("OPENFDD_SQL_RULES_DIR"),
    }
}

#[test]
fn shipped_registry_resolves_finite_bound() {
    let bound = oat_meteo_web_asof_bound_seconds().expect("workspace registry");
    assert!(bound.is_finite());
    assert!(bound > 0.0);
}
