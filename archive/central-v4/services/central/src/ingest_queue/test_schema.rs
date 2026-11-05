//! Shared Postgres schema setup for ingest-queue tests.

use sqlx::PgPool;

/// Shared ingest-queue fixture schema.
///
/// `ingest_queue::postgres::apply_schema` skips its DDL (and so takes no table
/// locks) only once its fingerprint is recorded in `seed_meta`. A database
/// that has never run the forward schema has no `seed_meta`, so every test
/// re-ran `ALTER TABLE ... IF NOT EXISTS` under ACCESS EXCLUSIVE while other
/// tests held queue row locks: `40P01`. Create the canonical `site`, `sample`,
/// and `seed_meta` tables (ingest writes samples) first, under the schema lock, so the fingerprint path
/// applies to every ingest-queue test.
pub(crate) async fn apply_ingest_queue_schema(
    pool: &PgPool,
) -> Result<(), super::model::QueueError> {
    const PREREQUISITES: [&str; 3] = [
        "CREATE TABLE IF NOT EXISTS site (",
        "CREATE TABLE IF NOT EXISTS sample (",
        "CREATE TABLE IF NOT EXISTS seed_meta (",
    ];
    let statements: Vec<&str> =
        fdd_tsdb::schema_statements(include_str!("../../../../sql/schema/01_bps_core.sql"))
            .chain(fdd_tsdb::schema_statements(include_str!(
                "../../../../sql/schema/02_openfdd_dims.sql"
            )))
            .filter(|stmt| PREREQUISITES.iter().any(|head| stmt.contains(head)))
            .collect();
    if statements.len() != PREREQUISITES.len() {
        panic!(
            "canonical schema must define site, sample, and seed_meta once each, found {}",
            statements.len()
        );
    }
    for statement in statements {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
    super::postgres::apply_schema(pool).await
}
