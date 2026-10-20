//! Central startup hook for the Timescale historian.
//!
//! Forward-only DDL runs when `OPENFDD_DATABASE_URL` is set. Existing rows are
//! not dropped, truncated, or reseeded, including when
//! `OPENFDD_ALLOW_DESTRUCTIVE_DB` is set. That variable only unlocks explicit
//! wipe commands outside this path.

use tracing::{info, warn};

pub async fn bootstrap_on_startup() {
    match fdd_tsdb::bootstrap_historian_from_env().await {
        Ok(report) if report.skipped => {
            info!("timescale schema bootstrap skipped (OPENFDD_DATABASE_URL unset)");
        }
        Ok(report) => {
            info!(
                disposition = report.disposition_label(),
                applied = report.applied,
                failed = report.failed,
                refused = report.refused,
                has_sample_row = report.has_sample_row(),
                "timescale schema bootstrap finished; existing rows were not deleted"
            );
        }
        Err(err) => {
            warn!(
                %err,
                "timescale schema bootstrap did not run; database contents were not modified"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use fdd_tsdb::{
        decide_bootstrap, destructive_db_opt_in, plan_bundled_schema, reset_permitted,
        BootstrapDisposition, HistorianProbe, SqlClass,
    };

    #[test]
    fn startup_default_preserves_existing_historian() {
        let existing = decide_bootstrap(HistorianProbe {
            known_relations: true,
            has_sample_row: true,
        });
        assert_eq!(
            existing,
            BootstrapDisposition::ExistingPreserve {
                has_sample_row: true
            }
        );
        assert!(reset_permitted(existing, false).is_err());
        assert!(reset_permitted(existing, destructive_db_opt_in(None)).is_err());
        assert!(reset_permitted(existing, destructive_db_opt_in(Some("1"))).is_ok());

        let plan = plan_bundled_schema(existing);
        assert!(plan.refused.is_empty());
        assert!(plan
            .apply
            .iter()
            .all(|stmt| { fdd_tsdb::classify_sql(stmt) == SqlClass::Forward }));
    }

    #[test]
    fn zero_row_initialized_database_is_not_reseeded() {
        let existing = decide_bootstrap(HistorianProbe {
            known_relations: true,
            has_sample_row: false,
        });
        assert!(reset_permitted(existing, false).is_err());
        let fresh = decide_bootstrap(HistorianProbe {
            known_relations: false,
            has_sample_row: false,
        });
        assert_eq!(fresh, BootstrapDisposition::NewDatabase);
        assert!(reset_permitted(fresh, false).is_ok());
    }
}
