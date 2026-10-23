//! Mapping response provenance.
//!
//! Sample inventory and a saved column map are not a semantic model check.
//! Checks that did not run stay `not_evaluated`. A stored active-ingest
//! revision is reported separately from the saved column map.

use serde_json::{json, Map, Value};

use crate::providers::committed_model::CommittedModelStore;

pub const PROVENANCE: &str = "mapping_revision_v1";

struct Check {
    id: &'static str,
    label: &'static str,
    status: &'static str,
    detail: String,
}

impl Check {
    fn json(&self) -> Value {
        json!({
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
        })
    }
}

/// Copy the active ingest revision without holding the model lock across an await.
pub fn copy_active_ingest_revision(
    models: &std::sync::Mutex<CommittedModelStore>,
    tenant_id: Option<&str>,
    site_id: &str,
) -> Option<String> {
    let tenant = tenant_id.map(str::trim).filter(|id| !id.is_empty())?;
    let site = site_id.trim();
    if site.is_empty() {
        return None;
    }
    let guard = models.lock().unwrap_or_else(|err| err.into_inner());
    guard.active_revision(tenant, site).map(str::to_string)
}

/// Attach check provenance to a mapping inventory. Idempotent.
pub fn annotate_mapping_response(body: &mut Value, active_ingest_revision: Option<&str>) {
    let Some(obj) = body.as_object_mut() else {
        return;
    };
    if obj.get("ok").and_then(Value::as_bool) != Some(true) {
        return;
    }
    if obj
        .get("validation")
        .and_then(|value| value.get("provenance"))
        .and_then(Value::as_str)
        == Some(PROVENANCE)
    {
        return;
    }
    let source = classify_source(obj);
    let (blockers, warnings, equipment_count) = validation_counts(obj);
    let revision = active_ingest_revision
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    let checks = build_checks(obj, source, blockers, warnings, revision.as_deref());
    let status = rollup(&checks);
    let source_label = source_label(&checks);
    let mut validation = obj
        .get("validation")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    validation.insert("blocker_count".into(), json!(blockers));
    validation.insert("warning_count".into(), json!(warnings));
    validation.insert("equipment_count".into(), json!(equipment_count));
    validation.insert("status".into(), json!(status));
    validation.insert("source_label".into(), json!(source_label));
    validation.insert("provenance".into(), json!(PROVENANCE));
    validation.insert(
        "checks".into(),
        Value::Array(checks.iter().map(Check::json).collect()),
    );
    obj.insert("validation".into(), Value::Object(validation));
    obj.insert(
        "revisions".into(),
        json!({
            "saved": {
                "authority": source,
                "label": saved_label(source),
            },
            "active_ingest": {
                "revision_id": revision,
                "activated_by_mapping_save": false,
            },
        }),
    );
}

/// A column-map save does not activate the ingest plan unless the handler already said so.
pub fn annotate_role_save(body: &mut Value) {
    let Some(obj) = body.as_object_mut() else {
        return;
    };
    if obj.get("ok").and_then(Value::as_bool) != Some(true) {
        return;
    }
    if !obj.contains_key("ingest_plan_activated") {
        obj.insert("ingest_plan_activated".into(), json!(false));
    }
    if !obj.contains_key("saved_authority") {
        obj.insert("saved_authority".into(), json!("csv_column_map"));
    }
}

fn classify_source(obj: &Map<String, Value>) -> &'static str {
    if obj.get("source").and_then(Value::as_str) == Some("timescale_sample") {
        return "timescale_sample";
    }
    let historian = obj
        .get("warnings")
        .and_then(Value::as_array)
        .is_some_and(|warnings| {
            warnings.iter().any(|warning| {
                warning
                    .as_str()
                    .is_some_and(|text| text.contains("historian-backed"))
            })
        });
    if historian {
        "historian_inventory"
    } else {
        "csv_column_map"
    }
}

fn saved_label(source: &str) -> &'static str {
    match source {
        "timescale_sample" => "Saved sample role keys",
        "historian_inventory" => "Saved historian inventory",
        _ => "Saved column map",
    }
}

fn validation_counts(obj: &Map<String, Value>) -> (u64, u64, u64) {
    let validation = obj.get("validation");
    let blockers = json_count(validation, "blocker_count");
    let warnings = json_count(validation, "warning_count");
    let mut equipment = json_count(validation, "equipment_count");
    if equipment == 0 {
        equipment = obj
            .get("equipment")
            .and_then(Value::as_array)
            .map(|rows| rows.len() as u64)
            .unwrap_or(0);
    }
    (blockers, warnings, equipment)
}

fn json_count(value: Option<&Value>, key: &str) -> u64 {
    let Some(value) = value.and_then(|item| item.get(key)) else {
        return 0;
    };
    if let Some(count) = value.as_u64() {
        return count;
    }
    value
        .as_i64()
        .filter(|count| *count >= 0)
        .map(|count| count as u64)
        .unwrap_or(0)
}

fn build_checks(
    obj: &Map<String, Value>,
    source: &str,
    blockers: u64,
    warnings: u64,
    revision: Option<&str>,
) -> Vec<Check> {
    let sample = if source == "timescale_sample" {
        Check {
            id: "sample_role_keys",
            label: "Sample role keys",
            status: "pass",
            detail: "Listed from historian sample keys.".into(),
        }
    } else {
        Check {
            id: "sample_role_keys",
            label: "Sample role keys",
            status: "not_evaluated",
            detail: "Historian sample keys were not the mapping source.".into(),
        }
    };
    let column = column_check(source, blockers, warnings);
    let stamp = if any_unclassified(obj) {
        Check {
            id: "equipment_stamp",
            label: "Equipment stamp",
            status: "incomplete",
            detail: "Type is unclassified.".into(),
        }
    } else {
        Check {
            id: "equipment_stamp",
            label: "Equipment stamp",
            status: "not_evaluated",
            detail: "A stored type string was not checked against a semantic model.".into(),
        }
    };
    let active_detail = match revision {
        Some(revision) => format!(
            "Active ingest revision {revision} is loaded. This response did not compare the mapping to that plan."
        ),
        None => "No active ingest revision is loaded for this request.".into(),
    };
    vec![
        sample,
        column,
        stamp,
        Check {
            id: "semantic_tags",
            label: "Semantic tags",
            status: "not_evaluated",
            detail: "No semantic model was checked.".into(),
        },
        Check {
            id: "kind_unit",
            label: "Kind and unit",
            status: "not_evaluated",
            detail: "Kind and unit were not checked.".into(),
        },
        Check {
            id: "provider_bindings",
            label: "Provider bindings",
            status: "not_evaluated",
            detail: "Provider bindings were not checked.".into(),
        },
        Check {
            id: "active_ingest_plan",
            label: "Active ingest plan",
            status: "not_evaluated",
            detail: active_detail,
        },
    ]
}

fn column_check(source: &str, blockers: u64, warnings: u64) -> Check {
    if source == "timescale_sample" {
        return Check {
            id: "column_role_map",
            label: "Column role map",
            status: "not_evaluated",
            detail: "CSV column map was not read.".into(),
        };
    }
    if source == "historian_inventory" && blockers == 0 && warnings == 0 {
        return Check {
            id: "column_role_map",
            label: "Column role map",
            status: "not_evaluated",
            detail: "Historian inventory did not report a column-role result.".into(),
        };
    }
    let (status, detail) = if blockers > 0 {
        ("fail", column_detail(blockers, warnings))
    } else if warnings > 0 {
        ("warning", column_detail(blockers, warnings))
    } else {
        ("pass", "Column roles were checked.".into())
    };
    Check {
        id: "column_role_map",
        label: "Column role map",
        status,
        detail,
    }
}

fn column_detail(blockers: u64, warnings: u64) -> String {
    if blockers > 0 && warnings > 0 {
        format!("{blockers} blocker(s), {warnings} warning(s)")
    } else if blockers > 0 {
        format!("{blockers} blocker(s)")
    } else if warnings > 0 {
        format!("{warnings} warning(s)")
    } else {
        "Column roles were checked.".into()
    }
}

fn any_unclassified(obj: &Map<String, Value>) -> bool {
    obj.get("equipment")
        .and_then(Value::as_array)
        .is_some_and(|rows| {
            rows.iter().any(|row| {
                let type_name = row
                    .get("equipment_type")
                    .and_then(Value::as_str)
                    .unwrap_or("unclassified")
                    .trim();
                type_name.is_empty() || type_name.eq_ignore_ascii_case("unclassified")
            })
        })
}

fn rollup(checks: &[Check]) -> &'static str {
    let failed = checks
        .iter()
        .any(|check| matches!(check.status, "fail" | "incomplete" | "warning"));
    if failed {
        return "incomplete";
    }
    if checks.is_empty() || checks.iter().any(|check| check.status == "not_evaluated") {
        return "not_evaluated";
    }
    if checks.iter().all(|check| check.status == "pass") {
        "validated"
    } else {
        "not_evaluated"
    }
}

fn source_label(checks: &[Check]) -> String {
    let evaluated = checks
        .iter()
        .filter(|check| check.status != "not_evaluated")
        .map(|check| check.label)
        .collect::<Vec<_>>()
        .join(", ");
    let skipped = checks
        .iter()
        .filter(|check| check.status == "not_evaluated")
        .map(|check| check.label)
        .collect::<Vec<_>>()
        .join(", ");
    let evaluated = if evaluated.is_empty() {
        "nothing".to_string()
    } else {
        evaluated
    };
    let skipped = if skipped.is_empty() {
        "nothing".to_string()
    } else {
        skipped
    };
    format!("Evaluated: {evaluated}. Not evaluated: {skipped}.")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn check_status(body: &Value, id: &str) -> String {
        body["validation"]["checks"]
            .as_array()
            .and_then(|checks| checks.iter().find(|check| check["id"].as_str() == Some(id)))
            .and_then(|check| check["status"].as_str())
            .unwrap_or("")
            .to_string()
    }

    fn sample_inventory() -> Value {
        json!({
            "ok": true,
            "building_id": "w5bunit",
            "source": "timescale_sample",
            "equipment_ids": ["EQ1"],
            "equipment": [{
                "equipment_id": "EQ1",
                "equipment_type": "unclassified",
                "ok": true,
                "columns": [{"column": "sat", "role": "sat", "status": "mapped"}],
                "roles": {"sat": "sat"},
                "blockers": [],
                "warnings": []
            }],
            "validation": {
                "blocker_count": 0,
                "warning_count": 0,
                "equipment_count": 1
            }
        })
    }

    #[test]
    fn sample_inventory_keeps_unevaluated_checks_out_of_a_pass() {
        let mut body = sample_inventory();
        annotate_mapping_response(&mut body, None);
        assert_ne!(body["validation"]["status"], json!("validated"));
        assert_eq!(body["validation"]["status"], json!("incomplete"));
        assert_eq!(body["validation"]["blocker_count"], json!(0));
        assert_eq!(check_status(&body, "sample_role_keys"), "pass");
        assert_eq!(check_status(&body, "column_role_map"), "not_evaluated");
        assert_eq!(check_status(&body, "equipment_stamp"), "incomplete");
        assert_eq!(check_status(&body, "semantic_tags"), "not_evaluated");
        assert_eq!(check_status(&body, "kind_unit"), "not_evaluated");
        assert_eq!(check_status(&body, "provider_bindings"), "not_evaluated");
        assert_eq!(check_status(&body, "active_ingest_plan"), "not_evaluated");
        let label = body["validation"]["source_label"].as_str().unwrap_or("");
        assert!(label.contains("Not evaluated:"), "{label}");
        assert!(!label.contains("0 blocker"), "{label}");
        assert_eq!(
            body["revisions"]["active_ingest"]["revision_id"],
            Value::Null
        );
        assert_eq!(
            body["revisions"]["active_ingest"]["activated_by_mapping_save"],
            json!(false)
        );
        assert_eq!(
            body["revisions"]["saved"]["label"],
            json!("Saved sample role keys")
        );

        let again = body.clone();
        annotate_mapping_response(&mut body, Some("rev-ignored"));
        assert_eq!(body, again);
    }

    #[test]
    fn active_ingest_revision_is_labeled_without_claiming_the_map_was_checked() {
        let mut body = sample_inventory();
        annotate_mapping_response(&mut body, Some("rev-ingest-1"));
        assert_eq!(
            body["revisions"]["active_ingest"]["revision_id"],
            json!("rev-ingest-1")
        );
        assert_eq!(check_status(&body, "active_ingest_plan"), "not_evaluated");
        let detail = body["validation"]["checks"]
            .as_array()
            .and_then(|checks| {
                checks
                    .iter()
                    .find(|check| check["id"].as_str() == Some("active_ingest_plan"))
            })
            .and_then(|check| check["detail"].as_str())
            .unwrap_or("");
        assert!(detail.contains("rev-ingest-1"), "{detail}");
        assert!(detail.contains("did not compare"), "{detail}");
    }

    #[test]
    fn clean_column_map_is_not_a_semantic_pass() {
        let mut body = json!({
            "ok": true,
            "building_id": "w5bcsv",
            "equipment": [{
                "equipment_id": "AHU_1",
                "equipment_type": "ahu",
                "roles": {"DA_T": "sat"},
                "blockers": [],
                "warnings": []
            }],
            "validation": {"blocker_count": 0, "warning_count": 0, "equipment_count": 1}
        });
        annotate_mapping_response(&mut body, None);
        assert_eq!(body["validation"]["status"], json!("not_evaluated"));
        assert_eq!(check_status(&body, "column_role_map"), "pass");
        assert_eq!(check_status(&body, "semantic_tags"), "not_evaluated");
        assert_eq!(
            body["revisions"]["saved"]["label"],
            json!("Saved column map")
        );
    }

    #[test]
    fn role_save_does_not_claim_ingest_activation() {
        let mut body = json!({"ok": true, "roles": {"SF_SPD": "fan_status"}});
        annotate_role_save(&mut body);
        assert_eq!(body["ingest_plan_activated"], json!(false));
        assert_eq!(body["saved_authority"], json!("csv_column_map"));
        annotate_role_save(&mut body);
        assert_eq!(body["ingest_plan_activated"], json!(false));
    }

    #[test]
    fn copy_revision_reads_the_active_plan_only() {
        let models = std::sync::Mutex::new(CommittedModelStore::default());
        assert_eq!(
            copy_active_ingest_revision(&models, Some("tenant-a"), "site-a"),
            None
        );
        assert_eq!(copy_active_ingest_revision(&models, None, "site-a"), None);
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_* env is process-global while this mapping fixture is connected"
    )]
    async fn sample_mapping_handler_reports_not_evaluated_checks() {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        let url = explicit
            .clone()
            .unwrap_or_else(|| "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".into());
        let pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
        {
            Ok(pool) => pool,
            Err(err) if explicit.is_some() => {
                panic!("OPENFDD_TEST_DATABASE_URL connect failed: {err}")
            }
            Err(err) => {
                eprintln!("skip: postgres fixture unavailable: {err}");
                return;
            }
        };

        let _lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("workspace");
        let _workspace_env = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let _env = EnvRestore::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_STORAGE_URL",
            "OPENFDD_PARQUET_ROOT",
            "OPENFDD_MULTI_TENANT",
        ]);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::set_var("OPENFDD_PARQUET_ROOT", workspace.path());
        std::env::remove_var("OPENFDD_STORAGE_URL");
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        fdd_tsdb::clear_shared_pool();

        ensure_schema(&pool).await;
        let token = uuid::Uuid::new_v4().simple().to_string();
        let site = format!("w5b{}", &token[..8]);
        delete_site(&pool, &site).await;
        seed_unclassified_sample(&pool, &site).await;

        let state = std::sync::Arc::new(crate::state::AppState::new());
        let response = crate::routes::csv_import_package_mapping(
            axum::extract::State(state),
            axum::http::HeaderMap::new(),
            axum::extract::Query(crate::routes::PackageMappingQuery::for_test(&site)),
        )
        .await
        .expect("mapping handler");
        let body = response.0;
        assert_eq!(body["ok"], json!(true), "{body}");
        assert_eq!(body["source"], json!("timescale_sample"), "{body}");
        assert_eq!(
            body["equipment"][0]["equipment_type"],
            json!("unclassified"),
            "{body}"
        );
        assert_ne!(body["validation"]["status"], json!("validated"), "{body}");
        assert_eq!(check_status(&body, "semantic_tags"), "not_evaluated");
        assert_eq!(check_status(&body, "column_role_map"), "not_evaluated");
        assert_eq!(check_status(&body, "equipment_stamp"), "incomplete");
        assert_eq!(check_status(&body, "kind_unit"), "not_evaluated");
        assert_eq!(body["validation"]["provenance"], json!(PROVENANCE));
        let label = body["validation"]["source_label"].as_str().unwrap_or("");
        assert!(label.contains("Not evaluated:"), "{label}");
        assert_eq!(
            body["revisions"]["active_ingest"]["activated_by_mapping_save"],
            json!(false)
        );
        delete_site(&pool, &site).await;
    }

    async fn ensure_schema(pool: &sqlx::PgPool) {
        for statement in [
            "CREATE TABLE IF NOT EXISTS site (
                site_id text PRIMARY KEY,
                dis text,
                timezone text NOT NULL DEFAULT 'UTC',
                enabled boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now()
            )",
            "CREATE TABLE IF NOT EXISTS building (
                building_id text PRIMARY KEY,
                site_id text REFERENCES site(site_id),
                dis text,
                timezone text NOT NULL DEFAULT 'UTC',
                created_at timestamptz NOT NULL DEFAULT now()
            )",
            "CREATE TABLE IF NOT EXISTS equipment (
                building_id text NOT NULL REFERENCES building(building_id),
                equipment_id text NOT NULL,
                equip_type text,
                parent_equipment_id text,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (building_id, equipment_id)
            )",
            "CREATE TABLE IF NOT EXISTS sample (
                ts timestamptz NOT NULL,
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                haystack_id text,
                val double precision,
                unit text,
                quality text,
                PRIMARY KEY (site_id, openfdd_key, ts)
            )",
        ] {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
        for statement in [
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
        ] {
            crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
        }
    }

    async fn seed_unclassified_sample(pool: &sqlx::PgPool, site: &str) {
        sqlx::query(
            "INSERT INTO site(site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
        sqlx::query(
            "INSERT INTO building(building_id, site_id, dis) VALUES ($1, $1, $1) ON CONFLICT (building_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("building");
        sqlx::query(
            "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES ($1, $2, NULL)
             ON CONFLICT (building_id, equipment_id) DO UPDATE SET equip_type = NULL",
        )
        .bind(site)
        .bind("EQ1")
        .execute(pool)
        .await
        .expect("equipment");
        sqlx::query(
            "INSERT INTO sample(ts, site_id, openfdd_key, val, unit)
             VALUES ('2026-06-01T00:00:00Z'::timestamptz, $1, 'EQ1.sat', 70.0, 'degF')
             ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET val = EXCLUDED.val",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("sample");
    }

    async fn delete_site(pool: &sqlx::PgPool, site: &str) {
        let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM equipment WHERE building_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM building WHERE building_id = $1")
            .bind(site)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM site WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await;
    }

    struct EnvRestore {
        saved: Vec<(String, Option<String>)>,
    }

    impl EnvRestore {
        fn capture(keys: &[&str]) -> Self {
            let saved = keys
                .iter()
                .map(|key| (key.to_string(), std::env::var(key).ok()))
                .collect();
            Self { saved }
        }
    }

    impl Drop for EnvRestore {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
            fdd_tsdb::clear_shared_pool();
        }
    }
}
