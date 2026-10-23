//! Shared Postgres fixtures race on `CREATE TABLE IF NOT EXISTS`.
//!
//! Two sessions can both miss the relation and then collide in `pg_type`
//! (`23505` on `pg_type_typname_nsp_index`). Retry only that catalog race.

use std::time::Duration;

use sqlx::PgPool;

const CATALOG_RACE_CONSTRAINTS: &[&str] =
    &["pg_type_typname_nsp_index", "pg_class_relname_nsp_index"];

pub(crate) async fn execute_idempotent_ddl(pool: &PgPool, statement: &str) {
    let mut pause = Duration::from_millis(20);
    let mut attempt = 0u8;
    loop {
        match sqlx::query(statement).execute(pool).await {
            Ok(_) => return,
            Err(err) if catalog_race(&err) && attempt < 5 => {
                attempt += 1;
                tokio::time::sleep(pause).await;
                pause = pause.saturating_mul(2);
            }
            Err(err) => panic!("ddl failed: {statement}: {err}"),
        }
    }
}

fn catalog_race(err: &sqlx::Error) -> bool {
    let Some(db) = err.as_database_error() else {
        return false;
    };
    db.code().as_deref() == Some("23505")
        && db
            .constraint()
            .is_some_and(|name| CATALOG_RACE_CONSTRAINTS.contains(&name))
}
