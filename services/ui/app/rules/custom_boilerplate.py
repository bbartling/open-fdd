"""Boilerplate for AI agents authoring **custom** pandas FDD rules.

Location (copy / extend from here)
----------------------------------
| Path | Purpose |
| --- | --- |
| ``app/rules/custom_boilerplate.py`` | **This file** — templates, helpers, worked examples |
| ``app/rules/custom_rules.py`` | **Agent workspace** — put finished ``CookbookRule`` objects in ``CUSTOM_RULES`` |
| ``app/rules/custom_registry.py`` | Merges custom rules into the active catalog |
| ``vibe19_agent_spec/docs/CUSTOM_RULES.md`` | Spec for agents |
| ``vibe19_agent_spec/skills/vibe19-pandas-fdd-rules/SKILL.md`` | Pipeline reminder |

Hard rules
----------
1. Never silently drop the **50 canonical** cookbook rules.
2. Custom rule ids **must** start with ``CUSTOM-`` (e.g. ``CUSTOM-SAT-HIGH``).
3. ``compute(df, params, poll_seconds) -> pd.Series`` of **bool** (raw fault mask), index-aligned.
4. Prefer cookbook roles (``sat``, ``fan_status``, …) after role_map — do not hardcode raw CSV names.
5. Always include ``CONFIRM_PARAM()`` so Streamlit gets a 0–60 min fault-delay slider (default 5).
6. After adding rules: ``python scripts/generate_rule_configs.py`` is **not** required for custom-only
   (configs are canonical). Run ``pytest`` instead. Smoke with agent API or Streamlit.

How an agent adds a rule
------------------------
1. Copy an example below into ``custom_rules.py``.
2. Append the ``CookbookRule`` to ``CUSTOM_RULES``.
3. Optionally add a gate in ``app/rules/operational_gate.py`` ``RULE_GATES``.
4. ``python -m pytest -q tests/test_custom_rules.py``
5. Headless: ``python scripts/agent_afdd.py --package … --out … --run-all``
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from app.rules.cookbook_catalog import CONFIRM_PARAM, CookbookParam, CookbookRule


def _f(params: dict, key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _false(index: pd.Index) -> pd.Series:
    return pd.Series(False, index=index, dtype=bool)


# ---------------------------------------------------------------------------
# Helper: build a CookbookRule without hand-writing the dataclass every time
# ---------------------------------------------------------------------------


def make_custom_rule(
    *,
    rule_id: str,
    title: str,
    compute: Callable[[pd.DataFrame, dict, float], pd.Series],
    required_roles: list[str],
    equation: str,
    equipment_kinds: list[str] | None = None,
    family: str = "custom",
    optional_roles: list[str] | None = None,
    extra_params: list[CookbookParam] | None = None,
    confirm_seconds: float = 300.0,
) -> CookbookRule:
    """Factory for agent-authored rules. ``rule_id`` must start with ``CUSTOM-``."""
    rid = str(rule_id).strip().upper()
    if not rid.startswith("CUSTOM-"):
        raise ValueError(f"Custom rule id must start with CUSTOM-, got {rule_id!r}")
    params = list(extra_params or [])
    if not any(p.key == "confirm_min" for p in params):
        params.append(CONFIRM_PARAM())
    return CookbookRule(
        id=rid,
        title=title,
        family=family,
        equipment_kinds=list(equipment_kinds or ["ahu", "vav", "unknown"]),
        required_roles=list(required_roles),
        equation=equation,
        compute=compute,
        params=params,
        optional_roles=list(optional_roles or []),
        confirm_seconds=float(confirm_seconds),
    )


# ---------------------------------------------------------------------------
# Example 1 — classic pandas threshold (SAT high while fan proven)
# ---------------------------------------------------------------------------


def compute_sat_high_while_fan_on(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Raw fault when discharge air is hotter than ``sat_hi`` and fan is on."""
    del poll  # unused — runner supplies poll for confirm_fault
    if "discharge-air-temp" not in d.columns:
        return _false(d.index)
    sat = pd.to_numeric(d["discharge-air-temp"], errors="coerce")
    thr = _f(p, "sat_hi", 75.0)
    fault = sat.notna() & (sat > thr)
    # Prefer fan_status; fall back to fan_cmd
    for role in ("fan-status", "fan-cmd"):
        if role in d.columns and d[role].notna().any():
            num = pd.to_numeric(d[role], errors="coerce")
            on = num.where(num <= 1.5, num / 100.0).fillna(0) > 0.05
            return fault & on
    return fault


EXAMPLE_SAT_HIGH = make_custom_rule(
    rule_id="CUSTOM-SAT-HIGH",
    title="SAT high while fan on (boilerplate)",
    compute=compute_sat_high_while_fan_on,
    required_roles=["discharge-air-temp"],
    optional_roles=["fan-status", "fan-cmd"],
    equation="Fan on AND SAT > sat_hi (°F). Boilerplate threshold rule for agents.",
    equipment_kinds=["ahu"],
    family="custom",
    extra_params=[
        CookbookParam("sat_hi", "SAT high threshold", "°F", 55.0, 120.0, 1.0, 75.0),
    ],
    confirm_seconds=300.0,
)


# ---------------------------------------------------------------------------
# Example 2 — basic “ML-ish” rolling z-score anomaly (no sklearn required)
# ---------------------------------------------------------------------------


def compute_rolling_zscore_anomaly(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Flag samples where |z| exceeds ``z_thr`` on a rolling window of ``role``.

    This is a teaching stand-in for unsupervised anomaly detection. Agents may
    replace the body with sklearn IsolationForest / a small regressor **if** they
    add that dependency — keep Streamlit+pandas by default.
    """
    del poll
    role = str(p.get("signal_role", "discharge-air-temp") or "discharge-air-temp")
    if role not in d.columns:
        return _false(d.index)
    s = pd.to_numeric(d[role], errors="coerce")
    win = max(3, int(_f(p, "window_samples", 36)))
    z_thr = _f(p, "z_thr", 3.0)
    mu = s.rolling(win, min_periods=max(3, win // 3)).mean()
    sigma = s.rolling(win, min_periods=max(3, win // 3)).std(ddof=0)
    z = (s - mu) / sigma.replace(0, np.nan)
    return z.notna() & (z.abs() > z_thr)


EXAMPLE_ZSCORE = make_custom_rule(
    rule_id="CUSTOM-ZSCORE",
    title="Rolling z-score anomaly (boilerplate ML)",
    compute=compute_rolling_zscore_anomaly,
    required_roles=["discharge-air-temp"],  # override via params["signal_role"] if mapped
    optional_roles=[],
    equation=(
        "Rolling |z-score| of signal_role > z_thr (default window ~3h @ 5‑min). "
        "Boilerplate unsupervised anomaly — swap for sklearn if needed."
    ),
    equipment_kinds=["ahu", "vav", "unknown"],
    family="custom",
    extra_params=[
        CookbookParam("window_samples", "Rolling window (samples)", "count", 6, 288, 1, 36),
        CookbookParam("z_thr", "Abs z-score threshold", "-", 1.5, 6.0, 0.1, 3.0),
    ],
    confirm_seconds=600.0,
)


# Catalog of worked examples — agents copy these into custom_rules.CUSTOM_RULES
EXAMPLE_CUSTOM_RULES: list[CookbookRule] = [EXAMPLE_SAT_HIGH, EXAMPLE_ZSCORE]


def sklearn_isolation_forest_sketch() -> str:
    """Return a code sketch (string) for agents — not imported at runtime."""
    return '''
# Optional upgrade (requires scikit-learn in the environment):
# from sklearn.ensemble import IsolationForest
# def compute_iforest(d, p, poll):
#     role = p.get("signal_role", "discharge-air-temp")
#     x = pd.to_numeric(d[role], errors="coerce").to_frame("x").dropna()
#     if len(x) < 30:
#         return pd.Series(False, index=d.index)
#     clf = IsolationForest(contamination=float(p.get("contam", 0.02)), random_state=0)
#     pred = pd.Series(clf.fit_predict(x), index=x.index)  # -1 = anomaly
#     return pred.reindex(d.index).fillna(1).eq(-1)
'''.strip()
