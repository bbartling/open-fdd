"""Sites CRUD API."""

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException

from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import sync_ttl_to_file
from open_fdd.platform.api.models import SiteCreate, SiteRead, SiteUpdate

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=list[SiteRead])
def list_sites():
    """List all sites."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, metadata, created_at FROM sites ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    return [SiteRead.model_validate(dict(r)) for r in rows]


@router.post("", response_model=SiteRead)
def create_site(body: SiteCreate):
    """Create a site. Returns 409 if a site with this name already exists."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sites WHERE name = %s", (body.name.strip(),))
            if cur.fetchone():
                raise HTTPException(409, "Site with this name already exists")
            cur.execute(
                "INSERT INTO sites (name, description, metadata) VALUES (%s, %s, %s::jsonb) RETURNING id, name, description, metadata, created_at",
                (body.name, body.description, json.dumps(body.metadata_ or {})),
            )
            row = cur.fetchone()
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass  # CRUD succeeds even if TTL sync fails (e.g. read-only filesystem)
    return SiteRead.model_validate(dict(row))


@router.get("/{site_id}", response_model=SiteRead)
def get_site(site_id: UUID):
    """Get a site by ID."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, metadata, created_at FROM sites WHERE id = %s",
                (str(site_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Site not found")
    return SiteRead.model_validate(dict(row))


@router.patch("/{site_id}", response_model=SiteRead)
def update_site(site_id: UUID, body: SiteUpdate):
    """Update a site."""
    updates, params = [], []
    if body.name is not None:
        updates.append("name = %s")
        params.append(body.name)
    if body.description is not None:
        updates.append("description = %s")
        params.append(body.description)
    if body.metadata_ is not None:
        updates.append("metadata = %s::jsonb")
        params.append(json.dumps(body.metadata_))
    if not updates:
        return get_site(site_id)
    if body.name is not None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM sites WHERE name = %s AND id != %s",
                    (body.name.strip(), str(site_id)),
                )
                if cur.fetchone():
                    raise HTTPException(409, "Another site with this name already exists")
    params.append(str(site_id))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE sites SET {', '.join(updates)} WHERE id = %s RETURNING id, name, description, metadata, created_at",
                params,
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "Site not found")
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return SiteRead.model_validate(dict(row))


@router.delete("/{site_id}")
def delete_site(site_id: UUID):
    """Delete a site and all its equipment, points, timeseries, fault_results, fault_events (cascade)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM sites WHERE id = %s",
                (str(site_id),),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Site not found")
            site_id_str = str(row["id"])
            site_name = row["name"] or site_id_str
            # fault_results/fault_events use text site_id (name or uuid)
            cur.execute(
                "DELETE FROM fault_results WHERE site_id IN (%s, %s)",
                (site_id_str, site_name),
            )
            cur.execute(
                "DELETE FROM fault_events WHERE site_id IN (%s, %s)",
                (site_id_str, site_name),
            )
            cur.execute("DELETE FROM sites WHERE id = %s RETURNING id", (site_id_str,))
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {"status": "deleted"}
