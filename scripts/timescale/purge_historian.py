#!/usr/bin/env python3
"""One-shot purge of the Timescale historian.

Image updates do not run this script. It is the explicit local-stack
opt-in for wiping every historian row once, before a Building 50 demo seed.

Refuses unless both of these are set:

- ``OPENFDD_RESET_DB=<token>`` or ``--reset-db <token>``
- ``OPENFDD_ALLOW_DESTRUCTIVE_DB=1`` or ``--i-understand-data-loss``

The token is stored in ``seed_meta``. The same token does not purge again.
A later purge needs a new token. NF portal history reads stay GET-only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from data_safe import (  # noqa: E402
    ALREADY_CONSUMED,
    CONSUME_EMPTY,
    PRESERVE,
    REFUSE,
    RESET,
    env_flag_on,
    purge_decision,
    reset_token,
)

# Keep aligned with services/central/src/db_lifecycle.rs RESET_TABLES.
RESET_TABLES = (
    "sample",
    "sample_changed_range",
    "data_revision",
    "fdd_interval_result",
    "fdd_incremental_checkpoint",
    "fdd_run",
    "analytics_result",
    "point_map",
    "role_map",
    "equipment",
    "building",
    "batch_job",
    "ingest_audit",
    "ingest_idempotency",
    "ingest_receipt",
    "ingest_job",
    "ingest_scheduler_lease",
    "ingest_portal_budget",
    "provider_hourly_gap",
    "provider_hourly_receipt",
    "provider_hourly_checkpoint",
    "provider_hourly_job",
    "seed_meta",
    "site",
)
RESET_TOKEN_KEY = "destructive_reset_token"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-db", default=None, help="One-shot purge token")
    parser.add_argument(
        "--i-understand-data-loss",
        action="store_true",
        help="Required together with the reset token",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the decision and do not connect",
    )
    return parser


def _redact(exc: BaseException) -> str:
    text = str(exc)
    if "://" in text or "password" in text.lower():
        return "database error (details redacted)"
    return text[:300]


def _existing(conn, names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    with conn.cursor() as cur:
        for name in names:
            if _IDENT.fullmatch(name) is None:
                raise RuntimeError("unsafe table identifier")
            cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
            row = cur.fetchone()
            if row and row[0] is not None:
                found.append(name)
    return found


def _consumed_token(conn) -> str | None:
    if "seed_meta" not in _existing(conn, ("seed_meta",)):
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM seed_meta WHERE key = %s", (RESET_TOKEN_KEY,))
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0])


def _purge(conn, token: str) -> str:
    present = _existing(conn, RESET_TABLES)
    if "seed_meta" not in present:
        raise RuntimeError(
            "seed_meta is missing; start central once so forward schema exists, then retry"
        )
    existing = any(name != "seed_meta" for name in present)
    action = purge_decision(token, True, _consumed_token(conn), existing)
    if action in {ALREADY_CONSUMED, PRESERVE}:
        return action
    with conn.cursor() as cur:
        if present:
            sql = "TRUNCATE TABLE " + ", ".join(present) + " RESTART IDENTITY CASCADE"
            cur.execute(sql)
        cur.execute(
            """
            INSERT INTO seed_meta(key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            (RESET_TOKEN_KEY, token),
        )
    conn.commit()
    return action


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = reset_token(args.reset_db) or reset_token(os.environ.get("OPENFDD_RESET_DB"))
    allow = bool(args.i_understand_data_loss) or env_flag_on(
        os.environ.get("OPENFDD_ALLOW_DESTRUCTIVE_DB")
    )
    if args.dry_run:
        action = purge_decision(token, allow, None, True)
        print(f"data_safe_action={action}")
        if action == REFUSE:
            print(
                "REFUSING historian purge. Pass --i-understand-data-loss "
                "or set OPENFDD_ALLOW_DESTRUCTIVE_DB=1 with the reset token. "
                "Rows were not deleted.",
                file=sys.stderr,
            )
            return 2
        return 0
    action = purge_decision(token, allow, None, True)
    if action == PRESERVE:
        print("data_safe_action=preserve")
        print("Historian purge not requested. Rows were not deleted.")
        return 0
    if action == REFUSE or token is None:
        print(
            "REFUSING historian purge. Set OPENFDD_RESET_DB to a one-shot token "
            "and OPENFDD_ALLOW_DESTRUCTIVE_DB=1. Rows were not deleted.",
            file=sys.stderr,
        )
        print("data_safe_action=refuse", file=sys.stderr)
        return 2
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        print("REFUSING historian purge: OPENFDD_DATABASE_URL is unset.", file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError:
        print("REFUSING historian purge: psycopg is not installed.", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url) as conn:
            done = _purge(conn, token)
    except Exception as exc:  # noqa: BLE001 — redact connection strings
        print(f"REFUSING historian purge: {_redact(exc)}", file=sys.stderr)
        return 1
    print(f"data_safe_action={done}")
    if done == RESET:
        print(
            "WARNING: Timescale historian rows were truncated. "
            "This reset token will not purge again.",
            file=sys.stderr,
        )
    elif done == CONSUME_EMPTY:
        print("Historian had no rows. Reset token recorded. Nothing was deleted.")
    elif done == ALREADY_CONSUMED:
        print("Reset token already used. Historian rows were not deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
