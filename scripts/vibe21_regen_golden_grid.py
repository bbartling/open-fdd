#!/usr/bin/env python3
"""Regenerate GOLDEN_PREDICTS.jsonl knob grid from oracle joblib (offline only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

STRATEGIES = (
    "baseline",
    "precool_shift",
    "deadband_10f",
    "chiller_off",
    "loadshed_p5f",
    "hvac_off",
    "precool_chiller_off",
)
STRAT_KNOBS = {
    "baseline": dict(precool_f=0.0, relax_clg_f=0.0, phase="baseline"),
    "precool_shift": dict(precool_f=2.0, relax_clg_f=5.0, phase="precool"),
    "deadband_10f": dict(
        precool_f=0.0, relax_clg_f=5.0, deadband_target_f=10.0, phase="relax"
    ),
    "chiller_off": dict(precool_f=0.0, relax_clg_f=0.0, chw_avail=0.0, phase="shed"),
    "loadshed_p5f": dict(precool_f=0.0, relax_clg_f=5.0, phase="shed"),
    "hvac_off": dict(
        precool_f=0.0, relax_clg_f=0.0, fan_avail=0.0, chw_avail=0.0, phase="shed"
    ),
    "precool_chiller_off": dict(
        precool_f=2.0, relax_clg_f=0.0, chw_avail=0.0, phase="precool"
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--oracle",
        type=Path,
        default=Path(
            "/home/ben/py-bacnet-stacks-playground/vibe_code_apps_21"
        ),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("docs/migration/vibe21/GOLDEN_PREDICTS.jsonl"),
    )
    args = ap.parse_args()
    sys.path.insert(0, str(args.oracle / "flask_app"))
    sys.path.insert(0, str(args.oracle / "ml"))
    import joblib
    from predict import predict_kw

    model_path = args.oracle / "flask_app/models/demand_hourly_v2.joblib"
    bundle = joblib.load(model_path)
    model = bundle["model"] if isinstance(bundle, dict) else bundle
    feature_cols = bundle.get("feature_cols") if isinstance(bundle, dict) else None
    target_cols = bundle.get("target_cols") if isinstance(bundle, dict) else None
    sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    oats = [0.0, 10.0, 20.0, 28.0, 32.0, 36.0, 40.0]
    rhs = [30.0, 55.0, 90.0]
    hours = [1, 8, 12, 15, 18, 22]
    base = dict(facility_kw_lag1=210.0, facility_kw_lag2=205.0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with args.out.open("w") as f:
        for sid in STRATEGIES:
            for oat in oats:
                for rh in rhs:
                    for hour in hours:
                        body = {
                            "strategy_id": sid,
                            "oat_c": oat,
                            "rh_pct": rh,
                            "hour_ending": hour,
                            "oat_lag1": oat - 1.0,
                            **base,
                            **STRAT_KNOBS[sid],
                        }
                        pred = predict_kw(
                            model, body, feature_cols, target_cols=target_cols
                        )
                        resp = (
                            {k: float(v) for k, v in pred["twin_io"].items()}
                            if "twin_io" in pred
                            else {
                                k: float(v)
                                for k, v in pred.items()
                                if isinstance(v, (int, float))
                            }
                        )
                        f.write(
                            json.dumps(
                                {
                                    "request": body,
                                    "response": resp,
                                    "meta": pred.get("meta")
                                    or {
                                        "strategy_id": sid,
                                        "hour_ending": hour,
                                        "mode": "grid",
                                    },
                                    "artifact_sha256": sha,
                                }
                            )
                            + "\n"
                        )
                        n += 1
    print(f"wrote {n} rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
