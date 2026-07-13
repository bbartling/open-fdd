//! Registry integrity: every production rule must load, render, and leave no placeholders.

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use crate::params::{rule_params, substitute_sql};
use crate::registry::load_registry;
use crate::runner::derive_window_rows;
use crate::tuning::{assert_sql_placeholders, effective_param_strings, load_tuning_profiles};

fn repo_sql_rules_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../sql_rules")
}

#[test]
fn registry_has_unique_ids_and_matching_sql_files() {
    let dir = repo_sql_rules_dir();
    let reg = load_registry(&dir).expect("load registry");
    assert!(
        reg.rules.len() >= 55,
        "expected >=55 registry rules, got {}",
        reg.rules.len()
    );

    let mut ids = HashSet::new();
    let mut sql_files = HashSet::new();
    for rule in &reg.rules {
        assert!(
            ids.insert(rule.rule_id.clone()),
            "duplicate rule_id {}",
            rule.rule_id
        );
        assert!(
            sql_files.insert(rule.sql_file.clone()),
            "duplicate sql_file {}",
            rule.sql_file
        );
        let path = dir.join(&rule.sql_file);
        assert!(
            path.is_file(),
            "missing SQL file for {}: {}",
            rule.rule_id,
            path.display()
        );
    }

    let on_disk: HashSet<String> = std::fs::read_dir(&dir)
        .expect("read sql_rules")
        .filter_map(|e| e.ok())
        .filter_map(|e| {
            let name = e.file_name().into_string().ok()?;
            if name.ends_with(".sql") {
                Some(name)
            } else {
                None
            }
        })
        .collect();
    let orphans: Vec<_> = on_disk.difference(&sql_files).collect();
    assert!(
        orphans.is_empty(),
        "orphan SQL files not in registry: {orphans:?}"
    );
}

#[test]
fn every_registry_rule_renders_without_placeholders() {
    let dir = repo_sql_rules_dir();
    let reg = load_registry(&dir).expect("load registry");
    let tuning = load_tuning_profiles(&dir).expect("load tuning");
    let poll_seconds = 300.0;

    let mut failures = Vec::new();
    for rule in &reg.rules {
        let sql_path = dir.join(&rule.sql_file);
        let raw = match std::fs::read_to_string(&sql_path) {
            Ok(s) => s,
            Err(e) => {
                failures.push(format!("{}: read sql: {e}", rule.rule_id));
                continue;
            }
        };
        if let Err(e) = assert_sql_placeholders(&raw, rule) {
            failures.push(format!("{}: placeholders: {e}", rule.rule_id));
            continue;
        }
        let mut params = rule_params(poll_seconds, rule.confirm_seconds);
        match effective_param_strings(rule, &tuning, None, None, None) {
            Ok(tuned) => {
                for (k, v) in tuned {
                    params.insert(k, v);
                }
            }
            Err(e) => {
                failures.push(format!("{}: tuning: {e}", rule.rule_id));
                continue;
            }
        }
        if raw.contains("{{WINDOW_ROWS}}") || raw.contains("{{WINDOW_ROWS_MINUS_ONE}}") {
            let window_minutes = params
                .get("WINDOW_MINUTES")
                .and_then(|s| s.parse::<f64>().ok())
                .or_else(|| rule.parameters.get("window_minutes").map(|p| p.default))
                .unwrap_or(60.0);
            let (window_rows, window_rows_minus_one) =
                derive_window_rows(window_minutes, poll_seconds);
            params.insert("WINDOW_ROWS".into(), window_rows.to_string());
            params.insert(
                "WINDOW_ROWS_MINUS_ONE".into(),
                window_rows_minus_one.to_string(),
            );
        }
        let rendered = substitute_sql(&raw, &params);
        if rendered.contains("{{") {
            failures.push(format!(
                "{}: unresolved placeholders remain after render",
                rule.rule_id
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "registry render failures:\n{}",
        failures.join("\n")
    );
}

#[test]
fn registry_parameter_placeholders_are_declared() {
    let dir = repo_sql_rules_dir();
    let reg = load_registry(&dir).expect("load registry");
    let mut failures = Vec::new();
    for rule in &reg.rules {
        let raw = std::fs::read_to_string(dir.join(&rule.sql_file)).unwrap_or_default();
        let mut declared: HashSet<String> = rule
            .parameters
            .values()
            .map(|p| p.sql_placeholder.clone())
            .collect();
        for builtin in [
            "POLL_SECONDS",
            "CONFIRM_ROWS",
            "CONFIRM_SECONDS",
            "WINDOW_ROWS",
            "WINDOW_ROWS_MINUS_ONE",
        ] {
            declared.insert(builtin.into());
        }
        let mut unused = declared.clone();
        let mut idx = 0;
        while let Some(start) = raw[idx..].find("{{") {
            let abs = idx + start + 2;
            if let Some(end) = raw[abs..].find("}}") {
                let key = &raw[abs..abs + end];
                unused.remove(key);
                if !declared.contains(key) {
                    failures.push(format!(
                        "{}: undeclared placeholder {{{{{key}}}}}",
                        rule.rule_id
                    ));
                }
                idx = abs + end + 2;
            } else {
                break;
            }
        }
        // Parameters declared but unused is a warning-class signal — keep as soft check
        // for non-empty parameter maps only when SQL has no matching placeholder.
        let _unused_params: HashMap<String, ()> = unused.into_iter().map(|k| (k, ())).collect();
        let _ = _unused_params;
    }
    assert!(
        failures.is_empty(),
        "placeholder declaration failures:\n{}",
        failures.join("\n")
    );
}
