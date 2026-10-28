//! Current authorized series binding.
//!
//! Policy `retroactive-current-binding-v1` (see
//! `sql/schema/07_opaque_series_binding.sql`):
//! sample rows stay on `(site_id, openfdd_key)`. Readers apply the current
//! `point_map` and `role_map` binding to every sample of that key. A role
//! edit or reparent changes how the whole series is read, including samples
//! stored before the edit. Effective-time intervals are not stored.

#[cfg(test)]
use sqlx::PgPool;

/// Recorded on Inspect, RCx, FDD, and export payloads.
pub const ROLE_BINDING_POLICY: &str = "retroactive-current-binding-v1";

/// Quote a PostgreSQL identifier. The value is data, not a trusted token.
pub fn quote_ident(name: &str) -> String {
    format!("\"{}\"", name.replace('"', "\"\""))
}

/// Idempotent maps and view for fixtures that build a database by hand.
/// Startup uses `sql/schema/07_opaque_series_binding.sql` instead.
#[cfg(test)]
pub async fn ensure_authorized_series(pool: &PgPool) {
    for statement in [
        "CREATE TABLE IF NOT EXISTS site (
            site_id text PRIMARY KEY,
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS point_map (
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            haystack_id text NOT NULL,
            role text,
            unit text,
            equipment_id text,
            PRIMARY KEY (site_id, openfdd_key)
        )",
        "CREATE TABLE IF NOT EXISTS role_map (
            building_id text NOT NULL,
            equipment_id text NOT NULL,
            openfdd_key text NOT NULL,
            role text NOT NULL,
            unit text,
            PRIMARY KEY (building_id, equipment_id, openfdd_key)
        )",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS portal_point_id text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS referenced boolean NOT NULL DEFAULT true",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS provider_instance_id text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS source_unit text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS quantity text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS cadence_secs bigint",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS history_mode text",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
    let view = include_str!("../../../sql/schema/07_opaque_series_binding.sql");
    for statement in crate::db_lifecycle::statements(view) {
        crate::test_ddl::execute_idempotent_ddl(pool, &statement).await;
    }
}

/// Record the current binding for one opaque key.
///
/// Other equipment rows for the same key are removed from `role_map` so the
/// key has one current parent. Sample rows are not touched.
#[cfg(test)]
pub async fn bind_series(
    pool: &PgPool,
    site_id: &str,
    equipment_id: &str,
    role: &str,
    openfdd_key: &str,
) {
    ensure_authorized_series(pool).await;
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING")
        .bind(site_id)
        .execute(pool)
        .await
        .expect("site");
    sqlx::query(
        "INSERT INTO point_map (
            site_id, openfdd_key, haystack_id, role, equipment_id, referenced
         ) VALUES ($1, $2, $2, $3, $4, true)
         ON CONFLICT (site_id, openfdd_key) DO UPDATE
           SET role = EXCLUDED.role,
               equipment_id = EXCLUDED.equipment_id,
               referenced = true",
    )
    .bind(site_id)
    .bind(openfdd_key)
    .bind(role)
    .bind(equipment_id)
    .execute(pool)
    .await
    .expect("point_map");
    sqlx::query(
        "DELETE FROM role_map
         WHERE building_id = $1 AND openfdd_key = $2 AND equipment_id <> $3",
    )
    .bind(site_id)
    .bind(openfdd_key)
    .bind(equipment_id)
    .execute(pool)
    .await
    .expect("reparent role_map");
    sqlx::query(
        "INSERT INTO role_map (building_id, equipment_id, openfdd_key, role)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
           SET role = EXCLUDED.role",
    )
    .bind(site_id)
    .bind(equipment_id)
    .bind(openfdd_key)
    .bind(role)
    .execute(pool)
    .await
    .expect("role_map");
}

/// Fixture keys are `{equipment}.{role}` with the role after the final dot.
/// The split lives only in this test helper. Product readers join the maps.
#[cfg(test)]
pub async fn bind_conventional_key(pool: &PgPool, site_id: &str, openfdd_key: &str) {
    let Some((equipment_id, role)) = openfdd_key.rsplit_once('.') else {
        return;
    };
    if equipment_id.is_empty() || role.is_empty() {
        return;
    }
    bind_series(pool, site_id, equipment_id, role, openfdd_key).await;
}
