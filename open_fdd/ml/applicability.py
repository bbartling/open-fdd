"""Which ML detectors can run on a frame, and why not (#1659).

``open-fdd-ml methods`` prints :data:`METHOD_REQUIREMENTS`. With a device folder it also checks each method
against the folder's roles and active rows, using the same rules as the detectors' ``fit``.
"""

from __future__ import annotations

import pandas as pd

from open_fdd.ml.detectors import (
    FEATURE_ROLES,
    GREY_BOX_RESIDUALS,
    METHODS,
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


def _non_constant(rows: pd.DataFrame, roles: list[str]) -> list[str]:
    out = []
    for role in roles:
        values = pd.to_numeric(rows[role], errors="coerce").dropna()
        if len(values) and float(values.std(ddof=0)) > 1e-9:
            out.append(role)
    return out


def applicability(frame: pd.DataFrame) -> list[dict[str, object]]:
    """One row per method: ``can_run``, the roles it would use, and the reason when it cannot run.

    Training-row counts are checked on the frame itself, i.e. as if it were the training data.
    """
    frame = canonical_roles(frame)
    active = active_mask(frame)
    rows = frame[active]
    features = [r for r in FEATURE_ROLES if r in frame.columns]
    varying = _non_constant(rows, features) if len(rows) else []
    out: list[dict[str, object]] = []
    for method in METHODS:
        info: dict[str, object] = {"method": method, "training": METHOD_REQUIREMENTS[method]["training"]}
        reason = ""
        used: list[str] = []
        if int(active.sum()) == 0:
            reason = "no active rows (no operating proof, or the unit never ran)"
        elif method in {"pca", "ocsvm", "copod"}:
            used = varying
            if len(varying) < 2:
                reason = f"needs two non-constant feature roles; has {varying or 'none'} (feature roles: {', '.join(FEATURE_ROLES)})"
            elif method == "pca" and len(rows[varying].dropna()) < 10:
                reason = "needs ten active rows with every feature role present"
            elif method in {"ocsvm", "copod"} and len(rows[varying].dropna()) < 50:
                reason = "needs 50 active rows in one operating mode"
            elif method == "copod" and not copod_available():
                reason = "needs the optional pyod package"
        elif method == "grey_box":
            families = grey_box_families(frame.columns)
            used = sorted({r for roles in families.values() for r in roles})
            info["families"] = sorted(families)
            if not families:
                missing = []
                for name, (needs, absent) in GREY_BOX_RESIDUALS.items():
                    blocked = [r for r in absent if r in frame.columns]
                    lacking = ["|".join(o) for o in needs if not any(r in frame.columns for r in o)]
                    missing.append(f"{name}: " + (f"has {', '.join(blocked)}" if blocked else f"lacks {', '.join(lacking)}"))
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
