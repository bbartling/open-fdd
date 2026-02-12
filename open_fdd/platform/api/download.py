"""Bulk CSV download API."""

from datetime import date
from io import StringIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from open_fdd.platform.database import get_conn
from open_fdd.platform.site_resolver import resolve_site_uuid

router = APIRouter(prefix="/download", tags=["download"])


class DownloadRequest(BaseModel):
    """Bulk download timeseries as CSV."""

    site_id: str = Field(..., min_length=1, description="Site name or UUID")
    start_date: date = Field(..., description="Start of date range")
    end_date: date = Field(..., description="End of date range")
    format: str = Field(
        "wide",
        pattern="^(wide|long)$",
        description="wide = pivot by point, long = ts, point_key, value",
    )
    point_ids: Optional[list[str]] = Field(
        None,
        description="Limit to these point UUIDs; omit for all points in site",
    )


@router.post("/csv")
def bulk_download_csv(body: DownloadRequest):
    """
    Bulk download timeseries as CSV. Specify site, date range, and optional point filter.
    Returns wide (pivot) or long (ts, point_key, value) format.
    """
    site_uuid = resolve_site_uuid(body.site_id, create_if_empty=False)
    if site_uuid is None:
        raise HTTPException(404, f"No site found for: {body.site_id!r}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            if body.point_ids and len(body.point_ids) > 0:
                cur.execute(
                    """
                    SELECT id FROM points
                    WHERE site_id = %s AND id::text = ANY(%s)
                    """,
                    (str(site_uuid), body.point_ids),
                )
                valid_ids = [str(r["id"]) for r in cur.fetchall()]
                if not valid_ids:
                    raise HTTPException(
                        404, "No matching points for the given criteria"
                    )
                cur.execute(
                    """
                    SELECT tr.ts, p.external_id, tr.value
                    FROM timeseries_readings tr
                    JOIN points p ON tr.point_id = p.id
                    WHERE p.site_id = %s
                      AND tr.point_id = ANY(%s::uuid[])
                      AND tr.ts::date >= %s AND tr.ts::date <= %s
                    ORDER BY tr.ts, p.external_id
                    """,
                    (str(site_uuid), valid_ids, body.start_date, body.end_date),
                )
            else:
                cur.execute(
                    """
                    SELECT tr.ts, p.external_id, tr.value
                    FROM timeseries_readings tr
                    JOIN points p ON tr.point_id = p.id
                    WHERE p.site_id = %s
                      AND tr.ts::date >= %s AND tr.ts::date <= %s
                    ORDER BY tr.ts, p.external_id
                    """,
                    (str(site_uuid), body.start_date, body.end_date),
                )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(404, "No data for the given criteria")

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])

    if body.format == "wide":
        out = df.pivot_table(
            index="ts", columns="external_id", values="value"
        ).reset_index()
        out = out.rename(columns={"ts": "timestamp"})
    else:
        out = df.rename(columns={"ts": "timestamp", "external_id": "point_key"})

    buf = StringIO()
    out.to_csv(buf, index=False)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=openfdd_export_{body.start_date}_{body.end_date}.csv"
        },
    )
