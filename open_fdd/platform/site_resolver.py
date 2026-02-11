"""
Resolve site UUID from name or ID; avoid creating duplicate "default" when a site exists.
"""

from uuid import UUID

from open_fdd.platform.database import get_conn


def resolve_site_uuid(site_id: str, create_if_empty: bool = True) -> UUID | None:
    """
    Resolve site name or UUID string to UUID.
    - If site exists by id or name, return it.
    - If not found but other sites exist, return the first site (avoid duplicate "default").
    - Only create a new site if create_if_empty=True and the sites table is empty.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM sites WHERE id::text = %s OR name = %s",
                (site_id, site_id),
            )
            row = cur.fetchone()
            if row:
                return row["id"]

            # Not found: use existing site if any (don't create duplicate "default")
            cur.execute("SELECT id FROM sites ORDER BY created_at LIMIT 1")
            row = cur.fetchone()
            if row:
                return row["id"]

            # No sites exist: create only if allowed
            if not create_if_empty:
                return None

            cur.execute("INSERT INTO sites (name) VALUES (%s) RETURNING id", (site_id,))
            site_uuid = cur.fetchone()["id"]
            conn.commit()
            return site_uuid
