"""The pandas reference: run ``open_fdd.rules`` over a parity dataset and return contract-shaped results.

Needs pandas (``pip install open-fdd[oracle]``). Nothing here converts units: the dataset is SI and so are the rules.

``reference(dataset)`` returns ``{rule_id: {equipment_id: {"pandas": fault_hours | None, "status": str, ...}}}`` for
every SQL rule that has a pandas twin (same rule id, ``PANDAS_ID`` where they differ). Per-sensor sweep rules also carry
``pandas_sensor_fault_hours`` / ``pandas_sensor_silence_hours`` keyed by SQL column name. Feed it to
``open_fdd.parity.compare``.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Iterable

from open_fdd.parity.dataset import Dataset, role_map

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: SQL rule id -> pandas rule id where they differ
PANDAS_ID = {"FC13-SAT-HIGH": "FC13"}


def _confirm_min() -> dict[str, float]:
    return json.loads((DATA_DIR / "parity_contract.json").read_text(encoding="utf-8"))["confirm_min"]


def sql_rule_ids() -> list[str]:
    """Every SQL rule of the pack (sorted)."""
    return sorted(_confirm_min())


def twin_rule_ids() -> tuple[list[str], list[str]]:
    """``(rules with a pandas twin, SQL-only rules)``."""
    from open_fdd.rules import RULES_BY_ID

    ids = sql_rule_ids()
    return ([r for r in ids if PANDAS_ID.get(r, r) in RULES_BY_ID], [r for r in ids if PANDAS_ID.get(r, r) not in RULES_BY_ID])


def _rows_by_equip(ds: Dataset) -> dict[str, list[dict]]:
    cached = getattr(ds, "_rows_by_equip", None)
    if cached is None:
        cached = {}
        for r in ds.history:
            cached.setdefault(r["equipment_id"], []).append(r)
        ds._rows_by_equip = cached
    return cached


def equip_frame(ds: Dataset, equip: str, ingest: str = "sorted"):
    """One equipment's history as a UTC-indexed frame with Haystack role columns.

    ``ingest``: ``as_is`` keeps the rows as delivered; ``sorted`` (default) sorts by time and drops duplicate
    timestamps (keeping the last row), which is a no-op on the ``basic`` profile.
    """
    import pandas as pd

    rows = _rows_by_equip(ds).get(equip, [])
    idx = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in rows], unit="ms", utc=True), name="timestamp_utc")
    rmap = {**role_map()}
    cols = {}
    for c in ds.history_columns:
        name = c["name"]
        s = pd.Series([r.get(name) for r in rows], index=idx)
        cols[rmap.get(name, name)] = pd.to_numeric(s, errors="coerce") if c["type"] != "text" else s
    df = pd.DataFrame(cols, index=idx)
    if ingest not in ("as_is", "sorted"):
        raise ValueError(f"unknown ingest {ingest!r}")
    if ingest == "sorted":
        df = df.sort_index(kind="stable")
        df = df[~df.index.duplicated(keep="last")]
    # an all-NULL column is a missing role (SQL carries it as typed NULL); weather may then supply web_* roles
    df = df.loc[:, df.notna().any()]
    df.attrs["equipment_id"] = equip
    df.attrs["role_units"] = {rmap.get(k, k): u for k, u in ds.units.items() if u}
    return df


def weather_frame(ds: Dataset):
    """Weather as the SQL join sees it: the last sample carried forward up to cadence + margin (25 min) on the grid."""
    import pandas as pd

    rows = ds.weather
    if not rows:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in rows], unit="ms", utc=True))
    out = pd.DataFrame({"web-outside-air-temp": [r.get("web_oa_t") for r in rows],
                        "web-outside-air-dewpoint": [r.get("web_oa_dp") for r in rows]}, index=idx)
    step = pd.Timedelta(seconds=ds.step_seconds)
    grid = pd.date_range(out.index[0], out.index[-1], freq=step)
    return out.reindex(out.index.union(grid)).ffill(limit=int(25 * 60 / ds.step_seconds)).reindex(grid)


def pandas_rule_result(rule_id: str, df, weather, poll_seconds: float = 300.0):
    """``(fault_hours | None, status, RuleResult)`` of one rule on one equipment frame."""
    from open_fdd.rules import RULES_BY_ID
    from open_fdd.rules.base import hours_true
    from open_fdd.rules.runner import run_cookbook_rule

    rule = RULES_BY_ID[PANDAS_ID.get(rule_id, rule_id)]
    kind = rule.equipment_kinds[0] if rule.equipment_kinds else "ahu"
    df.attrs["equipment_type"] = kind.upper()  # type-dispatched proofs (mechanical cooling, ...) need it
    params = {"confirm_min": _confirm_min().get(rule_id, 0.0)}
    res = run_cookbook_rule(rule, df.copy(), equipment_id=df.attrs["equipment_id"], equipment_kind=kind,
                            poll_seconds=poll_seconds, params_by_rule={rule.id: params},
                            weather=None if weather is None else weather.copy(), require_operational_gates=True)
    if res.status == "PASS":
        return 0.0, "PASS", res
    if res.confirmed_fault is not None and res.status == "FAULT":
        # full precision: RuleResult.fault_hours is rounded to 2 decimals for display
        return hours_true(res.confirmed_fault, poll_seconds), "FAULT", res
    return res.fault_hours, str(res.status), res


def reference(ds: Dataset, rules: Iterable[str] | None = None, ingest: str = "sorted") -> dict[str, dict[str, dict]]:
    """Run the pandas twin of every (or each given) SQL rule on every equipment of ``ds``."""
    twins, _ = twin_rule_ids()
    wanted = set(rules) if rules is not None else None
    hs_to_sql = {v: k for k, v in role_map().items()}
    weather = weather_frame(ds)
    frames = {e["equipment_id"]: equip_frame(ds, e["equipment_id"], ingest) for e in ds.equipment}
    equips = [e["equipment_id"] for e in ds.equipment]
    out: dict[str, dict[str, dict]] = {}
    for rule in twins:
        if wanted is not None and rule not in wanted:
            continue
        per: dict[str, dict] = {}
        for e in equips:
            try:
                # fresh copy per run: rules stash evidence/units in df.attrs and must not leak into each other
                df = frames[e].copy()
                df.attrs = copy.deepcopy(frames[e].attrs)
                ph, status, res = pandas_rule_result(rule, df, weather, float(ds.step_seconds))
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                ph, status, res = None, f"ERROR {type(exc).__name__}: {exc}", None
            item = {"pandas": None if ph is None else float(ph), "status": status}
            evidence = (res.metrics.get("sv_sweep_evidence") or []) if res is not None and rule.startswith("SV-") else None
            if evidence is not None:
                roles = {hs_to_sql.get(r["role"], r["role"]): float(r["fault_hours"])
                         for r in evidence if r.get("role") is not None and r.get("fault_hours") is not None}
                silence = {hs_to_sql.get(r["role"], r["role"]): float(r["silence_hours"])
                           for r in evidence if r.get("role") is not None and r.get("silence_hours") is not None}
                item["pandas_sensor_fault_hours"] = roles
                item["pandas_sensor_silence_hours"] = silence
                # equipment-level convention is the worst sensor, not the union of faulted time
                item["pandas"] = max(roles.values()) if roles else 0.0
            per[e] = item
        out[rule] = per
    return out
