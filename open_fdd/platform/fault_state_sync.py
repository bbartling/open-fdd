"""
Sync fault state from FDD run results: update fault_state table and emit fault.raised/fault.cleared.
Called after _write_fault_results in run_fdd_loop.
"""

from datetime import datetime, timezone
from typing import Any

from open_fdd.platform.database import get_conn
from open_fdd.schema import FDDResult


def _ts_now() -> datetime:
    return datetime.now(timezone.utc)


def sync_fault_state_from_results(results: list[FDDResult]) -> None:
    """
    Compute current active set from results (flag_value=1), compare to fault_state,
    upsert fault_state, and emit fault.raised / fault.cleared events.
    """
    from open_fdd.platform.realtime import emit, TOPIC_FAULT_RAISED, TOPIC_FAULT_CLEARED

    now = _ts_now()
    # Current active: (site_id, equipment_id, fault_id) where we have flag_value=1 in results
    current_active = set()
    for r in results:
        if r.flag_value:
            current_active.add((r.site_id, r.equipment_id, r.fault_id))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT site_id, equipment_id, fault_id, active
                FROM fault_state
                WHERE active = true
                """)
            rows = cur.fetchall()

    previously_active = {(r["site_id"], r["equipment_id"], r["fault_id"]) for r in rows}
    raised = current_active - previously_active
    cleared = previously_active - current_active

    with get_conn() as conn:
        with conn.cursor() as cur:
            for site_id, equipment_id, fault_id in raised:
                cur.execute(
                    """
                    INSERT INTO fault_state (site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context)
                    VALUES (%s, %s, %s, true, %s, %s, NULL)
                    ON CONFLICT (site_id, equipment_id, fault_id)
                    DO UPDATE SET active = true, last_changed_ts = %s, last_evaluated_ts = %s
                    """,
                    (site_id, equipment_id, fault_id, now, now, now, now),
                )
                emit(
                    TOPIC_FAULT_RAISED,
                    {
                        "site_id": site_id,
                        "equipment_id": equipment_id,
                        "fault_id": fault_id,
                        "last_changed_ts": now.isoformat(),
                    },
                )
            for site_id, equipment_id, fault_id in cleared:
                cur.execute(
                    """
                    INSERT INTO fault_state (site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context)
                    VALUES (%s, %s, %s, false, %s, %s, NULL)
                    ON CONFLICT (site_id, equipment_id, fault_id)
                    DO UPDATE SET active = false, last_changed_ts = %s, last_evaluated_ts = %s
                    """,
                    (site_id, equipment_id, fault_id, now, now, now, now),
                )
                emit(
                    TOPIC_FAULT_CLEARED,
                    {
                        "site_id": site_id,
                        "equipment_id": equipment_id,
                        "fault_id": fault_id,
                        "last_changed_ts": now.isoformat(),
                    },
                )
            # Mark all current_active as last_evaluated (even if unchanged)
            for site_id, equipment_id, fault_id in current_active:
                cur.execute(
                    """
                    UPDATE fault_state
                    SET last_evaluated_ts = %s
                    WHERE site_id = %s AND equipment_id = %s AND fault_id = %s
                    """,
                    (now, site_id, equipment_id, fault_id),
                )
        conn.commit()
