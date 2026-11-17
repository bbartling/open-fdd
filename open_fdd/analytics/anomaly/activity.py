"""One operating-activity policy for ``open-fdd-anomaly screen`` and ``open-fdd-ml detect`` (#1656).

A row is in one of four states:

- ``on``: operating proof says the unit runs (and it is occupied when an occupancy role has data);
- ``off``: operating proof says the unit is off;
- ``unoccupied``: the unit runs but the occupancy role says unoccupied;
- ``unknown``: no proof is available for the row (no proof role at all, or the proof value is missing).

Only ``on`` rows are assessed under the default ``proof`` policy. ``ungated`` assesses every row on
purpose, for an exploratory screen, and still reports the proof counts so a reader can see the choice.

The proof source is chosen per frame, not per row, in this order:

1. an own status role (``fan-status`` first for AHUs, then the other status roles of the canonical
   run-proof spec, ``open_fdd/run_proof.json``), compared with ``> 0.5``;
2. a resolved ``run-proof`` column (``open_fdd.run_proof``), compared with the spec threshold;
3. an own command role (``fan-cmd`` first), compared with the spec threshold.

A role counts as present when it has at least one finite value. When the chosen source has a missing
value on a row, the row is ``unknown``. The policy does not fall back to a command on that row, so a
status outage is reported instead of being covered by a command. Site and weather series (outdoor air
temperature, humidity and the like) are not tied to one unit's operation and are always assessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

ACTIVITY_POLICIES: tuple[str, ...] = ("proof", "ungated")
DEFAULT_POLICY = "proof"
STATUS_THRESHOLD = 0.5
STATES: tuple[str, ...] = ("on", "off", "unoccupied", "unknown")
SKIP_NO_PROOF = "no_run_proof"
SKIP_NO_ACTIVE = "no_active_rows"

#: Short role names (``sql/fdd/role_map.json`` keys) and underscore spellings accepted for proof roles.
_PROOF_ALIASES: dict[str, str] = {
    "fan_status": "fan-status",
    "fan_cmd": "fan-cmd",
    "occ_mode": "occupied",
    "run_proof": "run-proof",
}

#: Site and weather roles: assessed under every policy.
SITE_ROLES: frozenset[str] = frozenset(
    {
        "outside-air-temp",
        "outside-air-humidity",
        "outside-air-enthalpy",
        "outside-air-dewpoint-temp",
        "outside-air-wetbulb-temp",
        "oa_t",
        "oa_h",
        "oat",
    }
)


def _spec() -> dict:
    from open_fdd.run_proof import spec

    return spec()


def _hyphen(role: str) -> str:
    return _PROOF_ALIASES.get(role, role.replace("_", "-"))


def is_site_role(role: str) -> bool:
    """True for outdoor-air and weather roles, which are not gated by one unit's operation."""
    name = str(role).strip().lower()
    return name in SITE_ROLES or name.startswith("weather") or name.startswith("web-oa") or name.startswith("web_oa")


def _status_roles() -> list[str]:
    roles = ["fan-status"]
    for role in _spec()["own"]["status"]:
        if _hyphen(role) not in roles:
            roles.append(_hyphen(role))
    return roles


def _command_roles() -> list[str]:
    roles = ["fan-cmd"]
    for role in _spec()["own"]["command"]:
        if _hyphen(role) not in roles:
            roles.append(_hyphen(role))
    return roles


def _numeric_role(frame: pd.DataFrame, role: str) -> pd.Series | None:
    """The role as a numeric series when it exists with at least one finite value (alias spellings too)."""
    names = [role] + [alias for alias, target in _PROOF_ALIASES.items() if target == role]
    names.append(role.replace("-", "_"))
    for name in dict.fromkeys(names):
        if name in frame.columns:
            values = pd.to_numeric(frame[name], errors="coerce")
            if values.notna().any():
                return values
    return None


@dataclass
class Activity:
    """Per-row activity state plus the receipt that says how it was decided."""

    state: pd.Series
    policy: str = DEFAULT_POLICY
    source: str = "none"
    source_kind: str = "none"
    threshold: float | None = None
    occupancy_source: str = "none"
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def assessed(self) -> pd.Series:
        """Rows the policy assesses: ``on`` rows under ``proof``, every row under ``ungated``."""
        if self.policy == "ungated":
            return pd.Series(True, index=self.state.index)
        return self.state.eq("on")

    def receipt(self) -> dict[str, object]:
        total = int(len(self.state))
        assessed = int(self.assessed.sum())
        return {
            "policy": self.policy,
            "proof_source": self.source,
            "proof_kind": self.source_kind,
            "threshold": self.threshold,
            "occupancy_source": self.occupancy_source,
            "rows": total,
            **{f"{name}_rows": int(self.counts.get(name, 0)) for name in STATES},
            "assessed_rows": assessed,
            "assessed_fraction": round(assessed / total, 6) if total else 0.0,
        }


def activity(frame: pd.DataFrame, *, policy: str = DEFAULT_POLICY) -> Activity:
    """Decide on / off / unoccupied / unknown for every row of a role frame."""
    if policy not in ACTIVITY_POLICIES:
        raise ValueError(f"unknown activity policy {policy!r}; choose from {', '.join(ACTIVITY_POLICIES)}")
    spec_threshold = float(_spec()["threshold"])
    candidates: list[tuple[str, str, float]] = [(role, "status", STATUS_THRESHOLD) for role in _status_roles()]
    candidates.append(("run-proof", "run_proof", spec_threshold))
    candidates += [(role, "command", spec_threshold) for role in _command_roles()]

    state = pd.Series("unknown", index=frame.index, dtype=object)
    source, kind, threshold = "none", "none", None
    for role, role_kind, cut in candidates:
        values = _numeric_role(frame, role)
        if values is None:
            continue
        source, kind, threshold = role, role_kind, cut
        state = pd.Series("unknown", index=frame.index, dtype=object)
        state[values.gt(cut).to_numpy()] = "on"
        state[values.le(cut).to_numpy()] = "off"
        break

    occupancy_source = "none"
    occ = _numeric_role(frame, "occupied")
    if occ is not None:
        occupancy_source = "occupied"
        running = state.eq("on").to_numpy()
        state[running & occ.le(0.5).to_numpy()] = "unoccupied"
        state[running & occ.isna().to_numpy()] = "unknown"

    counts = {name: int(state.eq(name).sum()) for name in STATES}
    return Activity(
        state=state,
        policy=policy,
        source=source,
        source_kind=kind,
        threshold=threshold,
        occupancy_source=occupancy_source,
        counts=counts,
    )


def activity_mask(frame: pd.DataFrame, *, policy: str = DEFAULT_POLICY) -> pd.Series:
    """Boolean mask of the rows the policy assesses."""
    return activity(frame, policy=policy).assessed.astype(bool)
