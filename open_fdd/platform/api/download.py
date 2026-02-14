"""Bulk download API — timeseries and faults.

Supports two primary use cases:
1. Researcher: Excel-friendly CSV (wide format, BOM, ISO timestamps) — open directly in Excel.
2. MSI/Cx firm: REST export for cloud integration — poll /download/faults or /download/csv.
"""

from datetime import date
from io import StringIO
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from open_fdd.platform.database import get_conn
from open_fdd.platform.site_resolver import resolve_site_uuid

router = APIRouter(
    prefix="/download",
    tags=["download"],
)

_EXCEL_BOM = "\ufeff"


def _to_excel_csv(df: pd.DataFrame) -> str:
    """CSV with UTF-8 BOM and ISO timestamps — opens cleanly in Excel."""
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d %H:%M:%S")
    buf = StringIO()
    df.to_csv(buf, index=False)
    return _EXCEL_BOM + buf.getvalue()


class DownloadRequest(BaseModel):
    """Bulk download timeseries as CSV."""

    site_id: str = Field(..., min_length=1, description="Site name or UUID")
    start_date: date = Field(..., description="Start of date range")
    end_date: date = Field(..., description="End of date range")
    format: str = Field(
        "wide",
        pattern="^(wide|long)$",
        description="wide = timestamp + point columns (Excel-friendly); long = ts, point_key, value",
    )
    point_ids: Optional[list[str]] = Field(
        None,
        description="Limit to these point UUIDs; omit for all points in site",
    )


def _fetch_timeseries(
    site_uuid,
    start_date: date,
    end_date: date,
    point_ids: Optional[list[str]] = None,
) -> list:
    """Fetch timeseries rows from DB."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if point_ids and len(point_ids) > 0:
                cur.execute(
                    """
                    SELECT id FROM points
                    WHERE site_id = %s AND id::text = ANY(%s)
                    """,
                    (str(site_uuid), point_ids),
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
                      AND tr.ts::date >= %s AND tr.ts::date <= %s
                    ORDER BY tr.ts, p.external_id
                    """,
                    (str(site_uuid), valid_ids, start_date, end_date),
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
                    (str(site_uuid), start_date, end_date),
                )
            return cur.fetchall()


def _timeseries_to_csv(
    rows: list,
    fmt: str,
) -> str:
    """Convert timeseries rows to CSV string."""
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])
    if fmt == "wide":
        out = df.pivot_table(
            index="ts", columns="external_id", values="value"
        ).reset_index()
        out = out.rename(columns={"ts": "timestamp"})
    else:
        out = df.rename(columns={"ts": "timestamp", "external_id": "point_key"})
    return _to_excel_csv(out)


@router.get(
    "/csv",
    summary="GET timeseries CSV (researcher-friendly)",
)
def get_download_csv(
    site_id: str = Query(..., description="Site name or UUID"),
    start_date: date = Query(..., description="Start of date range"),
    end_date: date = Query(..., description="End of date range"),
    format: Literal["wide", "long"] = Query(
        "wide",
        description="wide = timestamp + point columns (Excel); long = ts, point_key, value",
    ),
):
    """
    **Researcher use case:** Download timeseries as Excel-friendly CSV.
    Wide format = timestamp column on left, one column per point. Open directly in Excel.
    Use GET for bookmarking or simple curl; use POST for point filter.
    """
    site_uuid = resolve_site_uuid(site_id, create_if_empty=False)
    if site_uuid is None:
        raise HTTPException(404, f"No site found for: {site_id!r}")
    rows = _fetch_timeseries(site_uuid, start_date, end_date)
    if not rows:
        raise HTTPException(404, "No data for the given criteria")
    csv_body = _timeseries_to_csv(rows, format)
    return StreamingResponse(
        iter([csv_body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=openfdd_timeseries_{start_date}_{end_date}.csv"
        },
    )


@router.post(
    "/csv",
    summary="POST timeseries CSV (with point filter)",
)
def post_download_csv(body: DownloadRequest):
    """
    Bulk download timeseries. Same as GET but supports point_ids filter.
    Returns Excel-friendly CSV (UTF-8 BOM, ISO timestamps).
    """
    site_uuid = resolve_site_uuid(body.site_id, create_if_empty=False)
    if site_uuid is None:
        raise HTTPException(404, f"No site found for: {body.site_id!r}")
    rows = _fetch_timeseries(site_uuid, body.start_date, body.end_date, body.point_ids)
    if not rows:
        raise HTTPException(404, "No data for the given criteria")
    csv_body = _timeseries_to_csv(rows, body.format)
    return StreamingResponse(
        iter([csv_body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=openfdd_timeseries_{body.start_date}_{body.end_date}.csv"
        },
    )


@router.get(
    "/faults",
    summary="Export fault results (MSI/cloud integration)",
)
def get_download_faults(
    site_id: Optional[str] = Query(
        None,
        description="Site name or UUID; omit for all sites",
    ),
    start_date: date = Query(..., description="Start of date range"),
    end_date: date = Query(..., description="End of date range"),
    format: Literal["csv", "json"] = Query(
        "csv",
        description="csv = Excel-friendly; json = for API/cloud integration",
    ),
):
    """
    **MSI/Cx use case:** Export fault results for cloud integration.
    Poll this endpoint (e.g. cron, scheduler) to sync faults into your platform.
    CSV = Excel-friendly; JSON = for REST/ETL pipelines.
    """
    conditions = ["ts::date >= %s", "ts::date <= %s"]
    params: list = [start_date, end_date]
    if site_id:
        if resolve_site_uuid(site_id, create_if_empty=False) is None:
            raise HTTPException(404, f"No site found for: {site_id!r}")
        conditions.append("site_id = %s")
        params.append(site_id)  # match as stored (name or uuid string)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ts, site_id, equipment_id, fault_id, flag_value, evidence
                FROM fault_results
                WHERE {" AND ".join(conditions)}
                ORDER BY ts, site_id, fault_id
                """,
                params,
            )
            rows = cur.fetchall()

    if format == "json":
        from fastapi.responses import JSONResponse

        data = []
        for r in rows:
            row = dict(r)
            if "ts" in row and hasattr(row["ts"], "isoformat"):
                row["ts"] = row["ts"].isoformat()
            data.append(row)
        return JSONResponse(
            content={"faults": data, "count": len(data)},
            headers={
                "Content-Disposition": f"attachment; filename=openfdd_faults_{start_date}_{end_date}.json"
            },
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
    csv_body = _to_excel_csv(df)
    return StreamingResponse(
        iter([csv_body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=openfdd_faults_{start_date}_{end_date}.csv"
        },
    )
