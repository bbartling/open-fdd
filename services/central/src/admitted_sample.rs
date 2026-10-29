//! Historian pivot reads stored SI values (`s.val`). Ingest converts once (W2b).

use sqlx::postgres::PgArguments;
use sqlx::query::Query;
use sqlx::Postgres;

/// Legacy placeholder so pivot call sites keep a stable builder type.
pub(crate) struct AdmitBuilder;

impl AdmitBuilder {
    pub(crate) fn after_occupied(_occupied: usize) -> Self {
        Self
    }

    pub(crate) fn admitted_on_sample(&mut self, _role: &str) -> String {
        "s.val".to_string()
    }

    pub(crate) fn binds(&self) -> &[()] {
        &[]
    }
}

type PgQuery<'q> = Query<'q, Postgres, PgArguments>;

pub(crate) fn apply_binds<'q>(query: PgQuery<'q>, _binds: &[()]) -> PgQuery<'q> {
    query
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pivot_reads_stored_si_values() {
        let mut builder = AdmitBuilder::after_occupied(3);
        assert_eq!(builder.admitted_on_sample("sat"), "s.val");
        assert_eq!(builder.admitted_on_sample("duct_static"), "s.val");
        assert!(builder.binds().is_empty());
    }
}
