"""Lab-seed decisions. Product startup does not import this module.

A reseed deletes rows only when the operator sets both ``OPENFDD_SEED_FORCE``
and ``OPENFDD_ALLOW_DESTRUCTIVE_DB``. Existing sample rows are left in place
otherwise.
"""

from __future__ import annotations

COPY_ONLY = "copy_only"
REGISTRY_ONLY = "registry_only"
DELETE_THEN_COPY = "delete_then_copy"
REFUSE = "refuse"
PRESERVE = "preserve"
RESET = "reset"
ALREADY_CONSUMED = "already_consumed"
CONSUME_EMPTY = "consume_empty"

_RESET_OFF = {"0", "false", "no", "off"}


def env_flag_on(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def reset_token(value: str | None) -> str | None:
    """One-shot purge token. Empty and false-like values do not request a purge."""

    if value is None:
        return None
    raw = value.strip()
    if not raw or raw.lower() in _RESET_OFF:
        return None
    return raw


def purge_decision(
    token: str | None,
    allow_destructive: bool,
    consumed_token: str | None,
    existing: bool,
) -> str:
    """Decide a full-historian purge.

    The allow flag alone does nothing. The same token does not purge twice.
    """

    if token is None:
        return PRESERVE
    if not allow_destructive:
        return REFUSE
    if consumed_token is not None and consumed_token == token:
        return ALREADY_CONSUMED
    if existing:
        return RESET
    return CONSUME_EMPTY


def seed_action(
    already_seeded: bool,
    existing_rows: int,
    force: bool,
    allow_destructive: bool,
) -> str:
    """Return the seed action for one site.

    ``force`` alone, or ``allow_destructive`` alone, does not delete rows.
    """

    if already_seeded and not force:
        return REGISTRY_ONLY
    if existing_rows > 0 or (force and already_seeded):
        if force and allow_destructive:
            return DELETE_THEN_COPY
        return REFUSE
    return COPY_ONLY


def refuse_message(building_id: str, existing_rows: int, force: bool) -> str:
    return (
        f"REFUSING reseed of {building_id}: existing_rows={existing_rows} "
        f"force={int(bool(force))}. Historian rows were not deleted. "
        "Reload requires OPENFDD_SEED_FORCE=1 and OPENFDD_ALLOW_DESTRUCTIVE_DB=1."
    )
