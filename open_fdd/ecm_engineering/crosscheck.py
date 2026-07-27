from __future__ import annotations
from typing import Any

def crosscheck(
    reference: float,
    candidate: float,
    *,
    low_ratio: float = 0.5,
    high_ratio: float = 2.0,
) -> dict[str, Any]:
    if reference == 0:
        return {
            "reference": reference,
            "candidate": candidate,
            "agreement_ratio": None,
            "difference": candidate,
            "verdict": "NO_REFERENCE",
        }
    ratio = candidate / reference
    verdict = (
        "REASONABLE_SCREENING_ALIGNMENT"
        if low_ratio <= ratio <= high_ratio
        else "INVESTIGATE_METHOD_DIFFERENCE"
    )
    return {
        "reference": reference,
        "candidate": candidate,
        "agreement_ratio": ratio,
        "difference": candidate - reference,
        "difference_fraction_of_reference": (candidate - reference) / reference,
        "verdict": verdict,
    }
