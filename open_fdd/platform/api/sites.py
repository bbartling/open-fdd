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
    """Create a site."""
    with get_conn() as conn:
        with conn.cursor() as cur:
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
    """Delete a site and all its points, timeseries (cascade)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sites WHERE id = %s RETURNING id", (str(site_id),))
            if not cur.fetchone():
                raise HTTPException(404, "Site not found")
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {"status": "deleted"}
