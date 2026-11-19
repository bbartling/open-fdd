"""Which ML detectors can run on a frame, and why not (#1659).

``open-fdd-ml methods`` prints :data:`METHOD_REQUIREMENTS`. With a device folder it also checks each method
against the folder's roles and active rows. The trained methods are checked with a dry ``fit`` on the frame,
so ``can_run`` is True exactly when ``fit`` succeeds (joint NaN handling, 50 rows in one operating mode, an
empty role, a residual that learns nothing); the reason is then the detector's own error.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from open_fdd.ml.detectors import (
    FEATURE_ROLES,
    GREY_BOX_RESIDUALS,
    METHODS,
    GreyBox,
    ModeGated,
    PCASPE,
    _roles_with_data,
    active_mask,
    canonical_roles,
    copod_available,
    grey_box_families,
)

#: Human-readable role requirements per method (also in ``open-fdd-ml methods`` and the ML docs).
METHOD_REQUIREMENTS: dict[str, dict[str, object]] = {
    "pca": {
        "training": True,
        "needs": "two or more non-constant feature roles and ten active training rows",
        "roles": list(FEATURE_ROLES),
    },
    "grey_box": {
        "training": True,
        "needs": "one residual family (any of its role sets); single-zone families only when there is no MAT",
        "families": {
            name: {"one_of_each": [list(options) for options in needs], "absent": list(absent)}
            for name, (needs, absent) in GREY_BOX_RESIDUALS.items()
        },
    },
    "ocsvm": {
        "training": True,
        "needs": "two or more non-constant feature roles and 50 active training rows in one operating mode",
        "roles": list(FEATURE_ROLES),
    },
    "copod": {
        "training": True,
        "needs": "as ocsvm, plus the optional pyod package",
        "roles": list(FEATURE_ROLES),
    },
    "zscore": {"training": False, "needs": "one non-binary feature role", "roles": list(FEATURE_ROLES)},
    "mad": {"training": False, "needs": "one non-binary feature role", "roles": list(FEATURE_ROLES)},
}
COMMON_NEED = "every method assesses only rows with operating proof on (fan-status, run-proof or fan-cmd)"


def _dry_fit(method: str, frame: pd.DataFrame) -> tuple[list[str], str, list[str]]:
    """``(roles, reason, families)`` from fitting the detector on the frame; ``reason`` is "" when fit succeeds."""
    if method == "pca":
        det = PCASPE()
    elif method == "grey_box":
        det = GreyBox()
    else:
        det = ModeGated(kind=method)
    try:
        det.fit(frame)
    except (ValueError, ImportError, np.linalg.LinAlgError) as exc:
        roles = list(getattr(det, "roles", []) or [])
        return roles, str(exc), []
    if method == "grey_box":
        families = sorted(det.thresholds_)
        picked = grey_box_families(canonical_roles(frame[active_mask(canonical_roles(frame))]))
        roles = sorted({r for name in families for r in picked.get(name, [])})
        return roles, "", families
    return list(det.roles), "", []


def applicability(frame: pd.DataFrame) -> list[dict[str, object]]:
    """One row per method: ``can_run``, the roles it would use, and the reason when it cannot run.

    Training-row counts are checked on the frame itself, i.e. as if it were the training data.
    """
    frame = canonical_roles(frame)
    active = active_mask(frame)
    rows = frame[active]
    features = [r for r in FEATURE_ROLES if r in frame.columns]
    out: list[dict[str, object]] = []
    for method in METHODS:
        info: dict[str, object] = {"method": method, "training": METHOD_REQUIREMENTS[method]["training"]}
        reason = ""
        used: list[str] = []
        if int(active.sum()) == 0:
            reason = "no active rows (no operating proof, or the unit never ran)"
        elif method == "copod" and not copod_available():
            reason = "needs the optional pyod package"
        elif method in {"pca", "ocsvm", "copod", "grey_box"}:
            used, reason, families = _dry_fit(method, frame)
            if method == "grey_box":
                info["families"] = families
                if reason and not grey_box_families(canonical_roles(rows)):
                    missing = []
                    have = set(_roles_with_data(rows))
                    for name, (needs, absent) in GREY_BOX_RESIDUALS.items():
                        blocked = [r for r in absent if r in have]
                        lacking = ["|".join(o) for o in needs if not any(r in have for r in o)]
                        missing.append(
                            f"{name}: " + (f"has {', '.join(blocked)}" if blocked else f"lacks {', '.join(lacking)}")
                        )
                    reason = "no residual family: " + "; ".join(missing)
        else:
            from open_fdd.analytics.anomaly.detectors import is_binary_like

            used = [r for r in features if not is_binary_like(pd.to_numeric(frame[r], errors="coerce"))]
            if not used:
                reason = "needs one non-binary feature role"
        info["can_run"] = not reason
        info["roles"] = used
        info["reason"] = reason
        out.append(info)
    return out


def requirements_text() -> str:
    lines = ["Method requirements (" + COMMON_NEED + "):"]
    for method in METHODS:
        req = METHOD_REQUIREMENTS[method]
        lines.append(f"  {method:9s} {'trains' if req['training'] else 'no training'}; {req['needs']}")
        if method == "grey_box":
            for name, fam in req["families"].items():
                sets = " + ".join("|".join(o) for o in fam["one_of_each"])
                lines.append(f"            {name}: {sets}" + (f" (no {', '.join(fam['absent'])})" if fam["absent"] else ""))
    lines.append("  feature roles: " + ", ".join(FEATURE_ROLES))
    return "\n".join(lines)
