"""Decide whether a lab Timescale seed may delete or reload existing rows.

Product startup does not call this. The seed scripts do, and they refuse when
any site or sample already exists unless both reload flags are set:

    OPENFDD_SEED_FORCE=1
    OPENFDD_ALLOW_DESTRUCTIVE_DB=1
"""

from __future__ import annotations

import os
from typing import Mapping

Decision = str  # skip_already | proceed_empty | reload | refuse

_TRUE = {"1", "true", "yes"}


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE


def destructive_db_allowed(env: Mapping[str, str] | None = None) -> bool:
    return _flag(os.environ if env is None else env, "OPENFDD_ALLOW_DESTRUCTIVE_DB")


def seed_force(env: Mapping[str, str] | None = None) -> bool:
    return _flag(os.environ if env is None else env, "OPENFDD_SEED_FORCE")


def decide_seed(
    *,
    marker_ok: bool,
    existing_samples: int,
    existing_sites: int,
    env: Mapping[str, str] | None = None,
) -> Decision:
    """Return the only legal next step for a lab seed.

    `existing_samples` and `existing_sites` are counts (zero means absent).
    A missing seed marker does not make an occupied database eligible for reload.
    """
    source = os.environ if env is None else env
    force = seed_force(source)
    allow = destructive_db_allowed(source)
    if marker_ok and not force:
        return "skip_already"
    occupied = existing_samples > 0 or existing_sites > 0
    if occupied and not (force and allow):
        return "refuse"
    if occupied and force and allow:
        return "reload"
    return "proceed_empty"
