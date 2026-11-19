"""One operating-activity policy for ``open-fdd-anomaly screen`` and ``open-fdd-ml detect`` (#1656).

A row is in one of four states:

- ``on``: operating proof says the unit runs (and it is occupied when an occupancy role has data);
- ``off``: operating proof says the unit is off;
- ``unoccupied``: the unit runs but the occupancy role says unoccupied;
- ``unknown``: no proof is available for the row (no proof role at all, or the proof value is missing).

Only ``on`` rows are assessed under the default ``proof`` policy. ``ungated`` assesses every row on
purpose, for an exploratory screen, and still reports the proof counts so a reader can see the choice.

The proof source is the canonical run-proof contract (``sql/fdd/run_proof.json``) through
:func:`open_fdd.run_proof.derive_run_proof`, the same resolver the rules use, chosen per frame:

1. a resolved ``run-proof`` column (own or feeding equipment, from the binding layer);
2. an own status role, in the contract's ``own.status`` order (``fan-status`` first);
3. an own command role, in the contract's ``own.command`` order (``fan-cmd`` first).

Every source is running when it is above the contract threshold (``> 0.05``). A frame stamped
``attrs["run_proof_resolved"] = True`` counts only its ``run-proof`` column, so "no proof bound" stays
no proof. A role counts as present when it has at least one finite value. When the chosen source has a
missing value on a row, the row is ``unknown``; the policy does not fall back to another source on that
row, so a proof outage is reported instead of being covered. This module adds only the ``unknown``
state and the occupancy gate on top of the contract. Site and weather series (outdoor air temperature,
humidity and the like) are not tied to one unit's operation and are always assessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

ACTIVITY_POLICIES: tuple[str, ...] = ("proof", "ungated")
DEFAULT_POLICY = "proof"
STATES: tuple[str, ...] = ("on", "off", "unoccupied", "unknown")
SKIP_NO_PROOF = "no_run_proof"
SKIP_NO_ACTIVE = "no_active_rows"
SKIP_NO_KNOWN_PROOF = "no_known_proof"

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
    raw = str(role).strip().lower()
    name = raw.replace("_", "-")
    return raw in SITE_ROLES or name in SITE_ROLES or name.startswith("weather") or name.startswith("web-oa")


def _proof_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """The frame's proof columns under the contract's column names (``fan-status``, ``run-proof`` ...).

    Short and underscore spellings (``fan_status``, ``run_proof``) are accepted. Returns the frame and the
    contract column -> kind map (``run_proof`` / ``status`` / ``command``).
    """
    from open_fdd.nf.model import column_for

    c = _spec()
    kinds: dict[str, str] = {c.get("column", "run-proof"): "run_proof"}
    for group in ("status", "command"):
        for role in c["own"][group]:
            kinds.setdefault(column_for(role), group)
    out = pd.DataFrame(index=frame.index)
    for column in kinds:
        names = [column, column.replace("-", "_")] + [a for a, t in _PROOF_ALIASES.items() if t == column]
        for name in dict.fromkeys(names):
            if name in frame.columns and pd.to_numeric(frame[name], errors="coerce").notna().any():
                out[column] = pd.to_numeric(frame[name], errors="coerce").to_numpy()
                break
    out.attrs = dict(frame.attrs)
    return out, kinds


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

    def skip_reason(self) -> str:
        """Why an equipment point has nothing to assess: no proof role, a proof role with no known value, or never on."""
        if self.source == "none":
            return SKIP_NO_PROOF
        if int(self.counts.get("unknown", 0)) == int(len(self.state)):
            return SKIP_NO_KNOWN_PROOF
        return SKIP_NO_ACTIVE

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
            "assessed_fraction": round(assessed / total, 6) if total else None,
        }


def activity(frame: pd.DataFrame, *, policy: str = DEFAULT_POLICY) -> Activity:
    """Decide on / off / unoccupied / unknown for every row of a role frame."""
    if policy not in ACTIVITY_POLICIES:
        raise ValueError(f"unknown activity policy {policy!r}; choose from {', '.join(ACTIVITY_POLICIES)}")
    from open_fdd.run_proof import derive_run_proof

    spec_threshold = float(_spec()["threshold"])
    proof_frame, kinds = _proof_frame(frame)
    values, column = derive_run_proof(proof_frame)

    state = pd.Series("unknown", index=frame.index, dtype=object)
    source, kind, threshold = "none", "none", None
    if values is not None:
        source, kind, threshold = column, kinds.get(column, "status"), spec_threshold
        values = pd.to_numeric(values, errors="coerce")
        state[values.gt(spec_threshold).to_numpy()] = "on"
        state[values.le(spec_threshold).to_numpy()] = "off"

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
