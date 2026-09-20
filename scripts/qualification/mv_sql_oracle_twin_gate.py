#!/usr/bin/env python3
"""Wave S4 Soft-OPEN — PyPI M&V twin vs POST /api/analytics/mv.

Default (no EXECUTE): exit 2 BLOCKED honesty (not qualification evidence).
With OPENFDD_SECURITY_EXECUTE=1 (or OPENFDD_MV_TWIN_EXECUTE=1):
  1. Run thin twin oracle (open_fdd/analytics/mv_change_point.py) on shared seed
  2. Optionally POST the same seed to central and compare coverage.fit / savings

Loads the twin module by file path so EXECUTE does not require numpy / full
``open-fdd[oracle]`` install (S3 change-point extras stay separate).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "scripts" / "qualification" / "fixtures" / "mv_change_point_seed.json"
MV_MOD = ROOT / "open_fdd" / "analytics" / "mv_change_point.py"
TOL_ABS = 1e-2


def _execute_enabled() -> bool:
    return os.environ.get("OPENFDD_SECURITY_EXECUTE", "0") == "1" or os.environ.get(
        "OPENFDD_MV_TWIN_EXECUTE", "0"
    ) == "1"


def _write_verdict(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


def _load_mv_module():
    """Load thin twin without importing open_fdd.analytics package (numpy-heavy)."""
    if not MV_MOD.is_file():
        raise FileNotFoundError(f"missing {MV_MOD}")
    spec = importlib.util.spec_from_file_location("openfdd_mv_change_point_twin", MV_MOD)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {MV_MOD}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _oracle_env(series: dict) -> dict:
    return _load_mv_module().handle_series(series)


def _post_api(base: str, token: str | None, series: dict) -> dict:
    url = base.rstrip("/") + "/api/analytics/mv"
    body = json.dumps(
        {"query_version": "mv-change-point-v1", "series": series}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fit_tuple(cov: dict | None) -> tuple[float, float, float] | None:
    if not cov:
        return None
    fit = cov.get("fit") or {}
    if not fit:
        return None
    return (
        float(fit["intercept"]),
        float(fit["slope"]),
        float(fit.get("r2", fit.get("r_squared", 0.0))),
    )


def _near(a: float, b: float, tol: float = TOL_ABS) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--artifact-dir",
        default=os.environ.get("ARTIFACT_DIR", ""),
        help="Directory for verdict JSON (default ARTIFACT_DIR or cwd)",
    )
    ap.add_argument(
        "--base-url",
        default=os.environ.get("OPENFDD_API_BASE")
        or os.environ.get("RAILWAY_BASE")
        or os.environ.get("CENTRAL_BASE")
        or "",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("OPENFDD_ADMIN_TOKEN")
        or os.environ.get("OPENFDD_JWT")
        or "",
    )
    ap.add_argument("--seed", type=Path, default=SEED)
    args = ap.parse_args()
    art = Path(args.artifact_dir or ".")
    art.mkdir(parents=True, exist_ok=True)
    verdict_path = art / "mv_sql_oracle_twin_verdict.json"

    if not _execute_enabled():
        payload = {
            "ok": False,
            "status": "BLOCKED",
            "reason": (
                "OPENFDD_SECURITY_EXECUTE!=1 (and OPENFDD_MV_TWIN_EXECUTE!=1); "
                "dry plan only — not Soft-OPEN FQ evidence"
            ),
            "gate": "36_mv_sql_oracle_twin",
            "seed": str(args.seed),
        }
        _write_verdict(verdict_path, payload)
        return 2

    if not args.seed.is_file():
        payload = {
            "ok": False,
            "status": "ERROR",
            "reason": f"missing seed {args.seed}",
            "gate": "36_mv_sql_oracle_twin",
        }
        _write_verdict(verdict_path, payload)
        return 1

    series = json.loads(args.seed.read_text(encoding="utf-8"))
    series_body = {k: v for k, v in series.items() if k != "notes"}

    try:
        oracle = _oracle_env(series_body)
    except Exception as exc:  # noqa: BLE001 — gate surface
        payload = {
            "ok": False,
            "status": "FAIL",
            "reason": f"oracle import/compute failed: {exc}",
            "gate": "36_mv_sql_oracle_twin",
        }
        _write_verdict(verdict_path, payload)
        return 1

    oracle_cov = oracle.get("coverage") or {}
    oracle_fit = _fit_tuple(oracle_cov)
    oracle_sav = float(oracle_cov.get("savings_reporting_total") or 0.0)
    (art / "mv_oracle_envelope.json").write_text(
        json.dumps(oracle, indent=2) + "\n", encoding="utf-8"
    )

    if oracle_fit is None or not (
        _near(oracle_fit[0], 500.0, 0.5)
        and _near(oracle_fit[1], 2.0, 1e-3)
        and _near(oracle_sav, 300.0, 1.0)
    ):
        payload = {
            "ok": False,
            "status": "FAIL",
            "reason": "oracle seed integrity failed (expected intercept≈500 slope≈2 savings≈300)",
            "oracle_fit": oracle_fit,
            "oracle_savings": oracle_sav,
            "gate": "36_mv_sql_oracle_twin",
        }
        _write_verdict(verdict_path, payload)
        return 1

    api_compared = False
    api_fit = None
    api_sav = None
    if args.base_url:
        try:
            raw = _post_api(args.base_url, args.token or None, series_body)
            (art / "mv_api_response.json").write_text(
                json.dumps(raw, indent=2) + "\n", encoding="utf-8"
            )
            analytics = raw.get("analytics") or raw
            api_cov = analytics.get("coverage") or {}
            api_fit = _fit_tuple(api_cov)
            api_sav = float(api_cov.get("savings_reporting_total") or 0.0)
            api_compared = True
            if api_fit is None:
                payload = {
                    "ok": False,
                    "status": "FAIL",
                    "reason": "API returned no fit in coverage",
                    "gate": "36_mv_sql_oracle_twin",
                }
                _write_verdict(verdict_path, payload)
                return 1
            if not (
                _near(api_fit[0], oracle_fit[0])
                and _near(api_fit[1], oracle_fit[1])
                and _near(api_sav, oracle_sav, 1.0)
            ):
                payload = {
                    "ok": False,
                    "status": "FAIL",
                    "reason": "API vs oracle mismatch on fit/savings",
                    "oracle_fit": oracle_fit,
                    "api_fit": api_fit,
                    "oracle_savings": oracle_sav,
                    "api_savings": api_sav,
                    "gate": "36_mv_sql_oracle_twin",
                }
                _write_verdict(verdict_path, payload)
                return 1
        except urllib.error.HTTPError as exc:
            payload = {
                "ok": False,
                "status": "FAIL",
                "reason": f"API HTTP {exc.code}: {exc.read()[:400]!r}",
                "gate": "36_mv_sql_oracle_twin",
            }
            _write_verdict(verdict_path, payload)
            return 1
        except Exception as exc:  # noqa: BLE001
            payload = {
                "ok": False,
                "status": "FAIL",
                "reason": f"API call failed: {exc}",
                "gate": "36_mv_sql_oracle_twin",
            }
            _write_verdict(verdict_path, payload)
            return 1
    else:
        print(
            "NOTE: no OPENFDD_API_BASE/RAILWAY_BASE/CENTRAL_BASE — oracle seed only",
            file=sys.stderr,
        )

    payload = {
        "ok": True,
        "status": "PASS",
        "gate": "36_mv_sql_oracle_twin",
        "api_compared": api_compared,
        "oracle_fit": {
            "intercept": oracle_fit[0],
            "slope": oracle_fit[1],
            "r2": oracle_fit[2],
        },
        "oracle_savings": oracle_sav,
        "api_fit": (
            {"intercept": api_fit[0], "slope": api_fit[1], "r2": api_fit[2]}
            if api_fit
            else None
        ),
        "api_savings": api_sav,
        "seed": str(args.seed),
    }
    _write_verdict(verdict_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
