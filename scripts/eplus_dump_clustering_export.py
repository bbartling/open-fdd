#!/usr/bin/env python3
"""Build pandas-ready clustering datasets from an OpenFDD building tree or dump zip.

User-facing name: **E+ dump and clustering** (replaces legacy WattLab dump parity path).

Reads historian ``history_wide.csv`` trees (same layout as package import / synthetic-59)
and emits sklearn-friendly tables under ``reports/eplus-dump/artifacts/<building_id>/clustering/``:

  clustering_features.parquet / .csv   — one row per equipment, wide role stats
  clustering_timeseries_long.parquet   — long format (timestamp, equipment_id, role, value)
  fdd_fault_vector.csv                 — optional fault-hour vector from dump or CSV
  README_clustering.md                 — copy-paste KMeans example
  MANIFEST.json

Example::

  python3 scripts/eplus_dump_clustering_export.py \\
    --building-root reports/wattlab-parity/fixtures/synthetic_59/.../OPENFDD_SYNTHETIC_59_RULE_WEEK_V1

  python3 scripts/eplus_dump_clustering_export.py --dump-zip /tmp/openfdd_dump.zip
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WATT = ROOT / "tools/wattlab_export"
if str(WATT) not in sys.path:
    sys.path.insert(0, str(WATT))

from app.data_loader import discover_equipment, load_equipment_csv  # noqa: E402

from eplus_paths import clustering_artifacts_dir, parity_root  # noqa: E402


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip()).strip("_") or "col"


def _read_columns_map(columns_path: Path | None) -> dict[str, str]:
    if not columns_path or not columns_path.is_file():
        return {}
    df = pd.read_csv(columns_path)
    col_key = "col" if "col" in df.columns else df.columns[0]
    role_key = next((c for c in ("point_role", "role", "description") if c in df.columns), None)
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        col = str(row[col_key]).strip()
        if not col or col.lower() in ("col", "column"):
            continue
        role = str(row[role_key]).strip() if role_key else col
        out[col] = role
    return out


def _infer_family(equipment_id: str, folder: Path, building_root: Path) -> str:
    try:
        rel = folder.relative_to(building_root)
        parts = [p for p in rel.parts if p.lower() not in ("weather",)]
        if len(parts) > 1:
            return parts[0].upper()
    except ValueError:
        pass
    u = equipment_id.upper()
    for prefix in ("VAV", "AHU", "CHW", "HW", "HP", "BOILER", "WEATHER"):
        if u.startswith(prefix):
            return prefix
    return "OTHER"


def _numeric_stats(series: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(series, errors="coerce")
    n = int(s.notna().sum())
    if n == 0:
        return {
            "n": 0.0,
            "mean": float("nan"),
            "std": float("nan"),
            "min": float("nan"),
            "p05": float("nan"),
            "p50": float("nan"),
            "p95": float("nan"),
            "max": float("nan"),
            "missing_pct": 100.0,
        }
    return {
        "n": float(n),
        "mean": float(s.mean()),
        "std": float(s.std(ddof=0) if n > 1 else 0.0),
        "min": float(s.min()),
        "p05": float(s.quantile(0.05)),
        "p50": float(s.median()),
        "p95": float(s.quantile(0.95)),
        "max": float(s.max()),
        "missing_pct": float(100.0 * (1.0 - n / max(len(s), 1))),
    }


def build_feature_rows(building_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_rows: list[dict[str, Any]] = []
    long_chunks: list[pd.DataFrame] = []

    for eq in discover_equipment(building_root):
        eq_id = eq["equipment_id"]
        cols_path = eq.get("columns_path")
        role_map = _read_columns_map(cols_path)
        df = load_equipment_csv(eq["history_path"], cols_path)
        family = _infer_family(eq_id, eq["folder"], building_root)

        row: dict[str, Any] = {
            "equipment_id": eq_id,
            "family": family,
            "n_timesteps": len(df),
        }
        if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1:
            deltas = df.index.to_series().diff().dropna().dt.total_seconds()
            row["poll_seconds_median"] = float(deltas.median()) if not deltas.empty else float("nan")
        else:
            row["poll_seconds_median"] = float("nan")

        for col in df.columns:
            if col in ("timestamp_utc", "timestamp", "time"):
                continue
            role = role_map.get(col, col)
            role_slug = _slug(role)
            stats = _numeric_stats(df[col])
            for stat_name, val in stats.items():
                row[f"{role_slug}__{stat_name}"] = val

        feature_rows.append(row)

        # Long timeseries (numeric columns only)
        melt_df = df.reset_index()
        ts_col = melt_df.columns[0]
        melt_df = melt_df.rename(columns={ts_col: "timestamp"})
        id_vars = ["timestamp"]
        val_cols = [c for c in melt_df.columns if c not in id_vars]
        if val_cols:
            chunk = melt_df.melt(id_vars=id_vars, value_vars=val_cols, var_name="col", value_name="value")
            chunk["role"] = chunk["col"].map(lambda c: role_map.get(str(c), str(c)))
            chunk["equipment_id"] = eq_id
            chunk["family"] = family
            chunk = chunk.drop(columns=["col"])
            long_chunks.append(chunk)

    features = pd.DataFrame(feature_rows)
    timeseries = pd.concat(long_chunks, ignore_index=True) if long_chunks else pd.DataFrame(
        columns=["timestamp", "role", "value", "equipment_id", "family"]
    )
    return features, timeseries


def load_fdd_fault_vector(
    building_root: Path,
    fdd_csv: Path | None,
    dump_dir: Path | None,
) -> pd.DataFrame | None:
    candidates: list[Path] = []
    if fdd_csv and fdd_csv.is_file():
        candidates.append(fdd_csv)
    if dump_dir:
        for name in ("fdd_findings.csv", "fdd_summary.csv"):
            p = dump_dir / name
            if p.is_file():
                candidates.append(p)
    for name in ("fdd_findings.csv", "fdd_summary.csv"):
        p = building_root / name
        if p.is_file():
            candidates.append(p)
    if not candidates:
        return None
    raw = pd.read_csv(candidates[0])
    rid = "rule_id" if "rule_id" in raw.columns else raw.columns[0]
    eid = "equipment_id" if "equipment_id" in raw.columns else raw.columns[1]
    status_col = next((c for c in ("status", "result_status") if c in raw.columns), None)
    hours_col = next((c for c in ("fault_hours", "confirmed_fault_hours") if c in raw.columns), None)
    rows = []
    for _, r in raw.iterrows():
        rows.append(
            {
                "rule_id": str(r[rid]),
                "equipment_id": str(r[eid]),
                "status": str(r[status_col]) if status_col else "",
                "fault_hours": float(r[hours_col]) if hours_col and pd.notna(r[hours_col]) else 0.0,
                "feature_key": f"{r[rid]}::{r[eid]}",
            }
        )
    return pd.DataFrame(rows)


def _extract_zip_dump(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    # Dump zips often wrap a single top folder
    kids = [p for p in dest.iterdir() if p.is_dir()]
    if len(kids) == 1 and discover_equipment(kids[0]):
        return kids[0]
    if discover_equipment(dest):
        return dest
    for kid in kids:
        if discover_equipment(kid):
            return kid
    return dest


def write_readme(out_dir: Path, building_id: str, n_equip: int, n_features: int) -> None:
    text = f"""# E+ dump clustering — `{building_id}`

Generated by `scripts/eplus_dump_clustering_export.py`.

## Files

| File | Shape / role |
|------|----------------|
| `clustering_features.csv` | {n_equip} equipment × {n_features} wide stats — **use for KMeans / PCA** |
| `clustering_timeseries_long.parquet` | Long historian melt — time-series clustering |
| `fdd_fault_vector.csv` | Rule-level fault hours (when dump included FDD tables) |

## Quick start (pandas + sklearn)

```python
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

df = pd.read_csv("clustering_features.csv").set_index("equipment_id")
meta = df[["family"]]
X = df.drop(columns=["family"], errors="ignore").select_dtypes("number").fillna(0)
X = StandardScaler().fit_transform(X)

km = KMeans(n_clusters=4, random_state=0, n_init="auto")
labels = km.fit_predict(X)
out = meta.assign(cluster=labels)
print(out.sort_values("cluster"))
```

## Notes

- Role columns come from each equipment folder's `columns.csv` (`point_role`).
- Missing historian roles become NaN in feature columns; impute before clustering.
- Legacy WattLab dump API routes remain (`/api/jobs/.../wattlab/dumps`); this export is offline/pandas-side.
"""
    (out_dir / "README_clustering.md").write_text(text, encoding="utf-8")


def export_clustering(
    building_root: Path,
    *,
    building_id: str | None = None,
    out_dir: Path | None = None,
    fdd_csv: Path | None = None,
    max_long_rows: int | None = None,
) -> dict[str, Any]:
    building_root = building_root.resolve()
    if not discover_equipment(building_root):
        raise SystemExit(f"No history_wide.csv under {building_root}")

    bid = building_id or building_root.name
    out = out_dir or clustering_artifacts_dir(bid)
    out.mkdir(parents=True, exist_ok=True)

    features, timeseries = build_feature_rows(building_root)
    if max_long_rows and len(timeseries) > max_long_rows:
        timeseries = timeseries.sample(n=max_long_rows, random_state=0).sort_values("timestamp")

    feat_csv = out / "clustering_features.csv"
    feat_pq = out / "clustering_features.parquet"
    long_pq = out / "clustering_timeseries_long.parquet"

    features.to_csv(feat_csv, index=False)
    features.to_parquet(feat_pq, index=False)
    timeseries.to_parquet(long_pq, index=False)

    fdd = load_fdd_fault_vector(building_root, fdd_csv, building_root)
    fdd_path = None
    if fdd is not None and not fdd.empty:
        fdd_path = out / "fdd_fault_vector.csv"
        fdd.to_csv(fdd_path, index=False)

    n_feat_cols = len([c for c in features.columns if c not in ("equipment_id", "family")])
    write_readme(out, bid, len(features), n_feat_cols)

    manifest = {
        "schema_version": "eplus_clustering_v1",
        "building_id": bid,
        "building_root": str(building_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_root": str(parity_root()),
        "files": {
            "clustering_features_csv": str(feat_csv),
            "clustering_features_parquet": str(feat_pq),
            "clustering_timeseries_long_parquet": str(long_pq),
            "fdd_fault_vector_csv": str(fdd_path) if fdd_path else None,
            "readme": str(out / "README_clustering.md"),
        },
        "counts": {
            "equipment": len(features),
            "feature_columns": n_feat_cols,
            "timeseries_rows": len(timeseries),
            "fdd_rows": len(fdd) if fdd is not None else 0,
        },
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--building-root", type=Path, help="Building folder with equipment/history_wide.csv")
    src.add_argument("--dump-zip", type=Path, help="OpenFDD / WattLab dump zip to extract first")
    ap.add_argument("--building-id", help="Override output building id (default: folder name)")
    ap.add_argument("--out-dir", type=Path, help="Override output directory")
    ap.add_argument("--fdd-csv", type=Path, help="Optional fdd_findings.csv to attach")
    ap.add_argument(
        "--max-long-rows",
        type=int,
        default=500_000,
        help="Cap long-format rows (default 500k; 0 = no cap)",
    )
    args = ap.parse_args()

    if args.dump_zip:
        extract_root = parity_root() / ".cache" / "dump_extract" / (args.building_id or args.dump_zip.stem)
        building_root = _extract_zip_dump(args.dump_zip.resolve(), extract_root)
    else:
        building_root = args.building_root.resolve()

    cap = None if args.max_long_rows == 0 else args.max_long_rows
    manifest = export_clustering(
        building_root,
        building_id=args.building_id,
        out_dir=args.out_dir,
        fdd_csv=args.fdd_csv,
        max_long_rows=cap,
    )
    print(json.dumps(manifest, indent=2))
    print(f"OK → {manifest['files']['clustering_features_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
