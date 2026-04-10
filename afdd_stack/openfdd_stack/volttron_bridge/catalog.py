"""Resolve Open-F-DD points for a VOLTTRON driver device name (Brick equipment row)."""

from __future__ import annotations

from typing import Any, List
from uuid import UUID

from openfdd_stack.platform.database import get_conn


def list_points_for_volttron_device(site_id: str, device_name: str) -> List[Any]:
    """
    Return point rows for equipment whose ``name`` matches ``device_name`` on ``site_id``.

    Uses the same ``sites`` / ``equipment`` / ``points`` schema as the FastAPI CRUD layer.
    Rows are ``RealDictRow``-like mappings with at least ``id``, ``external_id``, ``equipment_name``.
    """
    try:
        UUID(str(site_id))
    except ValueError as e:
        raise ValueError(f"site_id must be a UUID string, got {site_id!r}") from e
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.external_id, e.name AS equipment_name
                FROM points p
                INNER JOIN equipment e ON e.id = p.equipment_id
                WHERE p.site_id = %s::uuid AND e.name = %s
                ORDER BY p.external_id
                """,
                (site_id, device_name),
            )
            return list(cur.fetchall())
