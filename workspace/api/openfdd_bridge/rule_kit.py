"""Rule Lab dev kit — export zip (rule.py + sample data) and validate uploads (Arrow-only)."""

from __future__ import annotations

import ast
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather

from open_fdd.arrow_runtime.backend import lint_arrow_rule
from open_fdd.arrow_runtime.column_map_from_model import build_column_map_from_model_points
from open_fdd.arrow_runtime.rules import detect_rule_backend
from open_fdd.playground.arrow_templates import DEFAULT_ARROW_RULE

from .data_loader import load_frame_for_run
from .model_service import ModelService
from .rule_source import read_source
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .timeseries_api import resolve_plot_columns
from .ttl_service import TtlService


class RuleKitError(ValueError):
    """Invalid rule upload or kit export request."""


KIT_VALUE_STATS_HELPER = '''def _kit_value_stats(table, cfg):
    """Dev kit helper — min/max/mean for the rule value column (remove before upload if desired)."""
    import pyarrow.compute as pc
    from open_fdd.arrow_runtime.cookbook import value_column

    try:
        name = value_column(table, cfg)
        vals = pc.cast(table[name], "float64")
        print(
            f"rows={table.num_rows} column={name} "
            f"min={pc.min(vals).as_py():.2f} max={pc.max(vals).as_py():.2f} "
            f"mean={pc.mean(vals).as_py():.2f}"
        )
    except Exception as exc:
        print(f"value stats skipped: {exc}")
'''

COOKBOOK_KIT_DEFAULTS: dict[str, dict[str, Any]] = {
    "oob_mask": {
        "bounds_low": 65,
        "bounds_high": 85,
        "temp_unit": "imperial",
        "rolling_avg_minutes": 1,
    },
    "flatline_1h_mask": {
        "flatline_tolerance": 0.1,
        "flatline_window_samples": 12,
        "temp_unit": "imperial",
    },
    "spread_1h_mask": {
        "max_spread": 4.0,
        "flatline_window_samples": 12,
        "temp_unit": "imperial",
    },
}

CONFIG_KEYS_GUIDE: dict[str, Any] = {
    "oob_mask": {
        "description": "Outside bounds — flags when value is below bounds_low or above bounds_high.",
        "keys": {
            "bounds_low": "Lower limit (°F imperial, °C metric)",
            "bounds_high": "Upper limit",
            "rolling_avg_minutes": "Smoothing window in samples (1 = none)",
            "value_column": "Optional feather column name (default: first data column)",
            "value_kind": "Set to rh for humidity bounds_low_rh / bounds_high_rh",
        },
    },
    "flatline_1h_mask": {
        "description": "Flatline — flags when rolling min-max spread is within flatline_tolerance.",
        "keys": {
            "flatline_tolerance": "Max spread in window to count as stuck sensor",
            "flatline_window_samples": "Rolling window length (~12 ≈ 1 h at 5 min poll)",
            "value_column": "Optional feather column name",
        },
    },
    "spread_1h_mask": {
        "description": "Spread — flags when rolling max-min exceeds max_spread.",
        "keys": {
            "max_spread": "Fault when rolling spread is greater than this",
            "flatline_window_samples": "Rolling window length",
            "value_column": "Optional feather column name",
        },
    },
}


def augment_rule_code_for_kit_export(code: str) -> str:
    """Inject local dev value stats into exported rule.py (not stored on server)."""
    text = str(code or "").strip()
    if not text or "_kit_value_stats" in text:
        return text

    tree = ast.parse(text)
    target_idx: int | None = None
    for idx, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef) and node.name == "apply_faults_arrow":
            target_idx = idx
            if not (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Call)
                and isinstance(node.body[0].value.func, ast.Name)
                and node.body[0].value.func.id == "_kit_value_stats"
            ):
                node.body.insert(0, ast.parse("_kit_value_stats(table, cfg)").body[0])
            break

    helper_fn = ast.parse(KIT_VALUE_STATS_HELPER.strip()).body[0]
    if target_idx is not None:
        tree.body.insert(target_idx, helper_fn)
        return ast.unparse(tree).strip() + "\n"
    return f"{KIT_VALUE_STATS_HELPER.strip()}\n\n{text}\n"


def infer_kit_config(rule_code: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure exported config.json includes cookbook defaults for the bundled algorithm."""
    out = dict(config) if isinstance(config, dict) else {}
    for marker, defaults in COOKBOOK_KIT_DEFAULTS.items():
        if marker in rule_code:
            for key, value in defaults.items():
                out.setdefault(key, value)
            return out
    out.setdefault("max_zone_temp", 75)
    return out


def name_from_filename(filename: str) -> str:
    stem = Path(str(filename or "rule.py")).stem.strip()
    if not stem:
        return "Uploaded rule"
    text = stem.replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in text.split()) or "Uploaded rule"


def validate_uploaded_rule(code: str, *, filename: str = "rule.py") -> dict[str, Any]:
    """Arrow-only upload gate — required entrypoint + lint; rejects legacy/script."""
    text = str(code or "").strip()
    if not text:
        raise RuleKitError("rule.py is empty")
    if not str(filename).lower().endswith(".py"):
        raise RuleKitError("upload must be a .py file")

    backend = detect_rule_backend(text, {"mode": "rule"})
    if backend == "script":
        raise RuleKitError("script mode is not supported — upload apply_faults_arrow rules only")
    if backend == "legacy_row":
        raise RuleKitError(
            "legacy evaluate(row, cfg) rules are retired — use apply_faults_arrow(table, cfg, context=None)"
        )
    if backend != "arrow":
        raise RuleKitError("rule must define apply_faults_arrow(table, cfg, context=None)")

    lint = lint_arrow_rule(text, strict_imports=True)
    if not lint.get("ok"):
        issues = lint.get("issues") or []
        first = next((i for i in issues if i.get("severity") == "error"), issues[0] if issues else None)
        msg = str((first or {}).get("message") or "lint failed")
        line = (first or {}).get("line")
        raise RuleKitError(f"lint error{ f' (line {line})' if line else ''}: {msg}")

    return {"ok": True, "backend": "arrow", "lint": lint}


def _scope_frame(
    df: pd.DataFrame,
    model: dict[str, Any],
    site_id: str,
    *,
    point_keys: list[str] | None,
) -> tuple[pd.DataFrame, list[str]]:
    meta = {"timestamp", "site_id", "building_id", "system_id"}
    keys = [str(k).strip() for k in (point_keys or []) if str(k).strip()]
    if not keys:
        data_cols = [c for c in df.columns if c not in meta]
        return df, data_cols

    cols = resolve_plot_columns(keys, model, site_id)
    if not cols:
        return df.iloc[0:0].copy(), []

    keep = [c for c in df.columns if c in meta or c in cols]
    data_kept = [c for c in keep if c not in meta]
    if not data_kept:
        return df.iloc[0:0].copy(), []
    return df[keep], data_kept


def _apply_lookback(df: pd.DataFrame, hours: float) -> pd.DataFrame:
    if df is None or df.empty or "timestamp" not in df.columns or hours <= 0:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=max(0.1, hours))
    return out[out["timestamp"] >= cutoff]


def _frame_to_kit_table(df: pd.DataFrame, *, lookback_hours: float, limit: int = 5000) -> pa.Table:
    if df is None or df.empty:
        return pa.table({"timestamp": pa.array([], type=pa.timestamp("us", tz="UTC"))})
    sample = _apply_lookback(df, lookback_hours)
    if "timestamp" in sample.columns:
        sample = sample.sort_values("timestamp")
    if limit and len(sample) > limit:
        sample = sample.tail(limit)
    return pa.Table.from_pandas(sample, preserve_index=False)


def _data_py_content(
    *,
    site_id: str,
    lookback_hours: float,
    columns: list[str],
    preview_rows: list[dict],
    row_count: int,
) -> str:
    preview_json = json.dumps(preview_rows[:12], indent=2, default=str)
    cols_json = json.dumps(columns, indent=2)
    return f'''"""Open-FDD Rule Lab sample data — generated from feather historian.

Full lookback window lives in sample.feather ({row_count} rows, {lookback_hours}h).
ROWS below is a tiny preview only — use data.load_table() for rule development.
"""
from __future__ import annotations

from pathlib import Path

SITE_ID = {site_id!r}
LOOKBACK_HOURS = {lookback_hours}
ROW_COUNT = {row_count}
COLUMNS = {cols_json}

# Preview only (first rows) — full historian window is in sample.feather:
ROWS = {preview_json}


def load_table():
    """Load PyArrow table from bundled sample.feather (all rows in the lookback window)."""
    import pyarrow.feather as feather

    path = Path(__file__).resolve().parent / "sample.feather"
    return feather.read_table(path)
'''


RUN_TEST_PY = '''#!/usr/bin/env python3
"""Run the bundled rule against sample.feather (local dev kit)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.compute as pc

import data
import rule


def main() -> int:
    table = data.load_table()
    cfg_path = Path(__file__).resolve().parent / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    print(f"site={data.SITE_ID} lookback_h={data.LOOKBACK_HOURS} rows={table.num_rows}")
    if table.num_rows == 0:
        print("No rows in sample.feather — re-download kit after historian has data.")
        return 1
    print("columns:", list(table.column_names))
    mask = rule.apply_faults_arrow(table, cfg, context={"site_id": data.SITE_ID})
    flagged = int(pc.sum(mask).as_py()) if mask is not None else 0
    print(f"flagged={flagged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _readme_content(*, site_id: str, rule_name: str, lookback_hours: float, row_count: int) -> str:
    return f"""# Open-FDD Rule Lab kit — {rule_name}

## 1. Install (once per machine)

**Linux / macOS**

```bash
pip install "open-fdd>=3.0.1" pyarrow
```

**Windows (PowerShell)**

```powershell
pip install "open-fdd>=3.0.1" pyarrow
```

`rule.py` is a library module — running `python rule.py` directly does nothing.
Use `run_test.py` (below) or the Python snippet.

## 2. Run the bundled test

Unzip the kit, then **cd into that folder** (e.g. `openfdd-rule-kit-bench_oa-t_flatline_1h`) before running:

```bash
cd openfdd-rule-kit-*
python run_test.py
```

PowerShell:

```powershell
cd .\\openfdd-rule-kit-*
python .\\run_test.py
```

Expected output: row count, column names, and `flagged=N`.

## 3. Files

| File | Purpose |
|------|---------|
| `rule.py` | Your Arrow rule — `apply_faults_arrow(table, cfg, context=None)` |
| `data.py` | Metadata + `load_table()` helper |
| `sample.feather` | **Full historian window** ({row_count} rows, ~{lookback_hours}h) from site `{site_id}` |
| `run_test.py` | One-command local test |
| `column_map.json` | BRICK logical keys → feather column names |
| `config.json` | Suggested rule config (edit to match your rule) |
| `kit_meta.json` | Export metadata (site, columns, row count) |

`data.py` `ROWS` is only a **12-row preview**. All real data is in `sample.feather`.

Edit **`config.json`** to tune the algorithm (bounds, tolerances, window size). See **`config_keys.json`** in this zip for key descriptions.

Exported `rule.py` includes a **`_kit_value_stats`** helper that prints min/max/mean when you run `run_test.py`. Remove that helper before upload if you do not want it on the server.

## 4. Config-driven algorithms (PyArrow, no pandas)

Rules read **`config.json`** at test time. Cookbook masks use **PyArrow compute** on columnar arrays — no pandas in the hot path.

**Out of bounds (`oob_mask`)** — pure PyArrow sketch:

```python
import pyarrow.compute as pc

vals = pc.cast(table["oa-t"], "float64")
low, high = float(cfg["bounds_low"]), float(cfg["bounds_high"])
too_low = pc.less(vals, low)
too_high = pc.greater(vals, high)
mask = pc.or_(too_low, too_high)  # boolean array, one flag per row
```

**Flatline** — rolling min/max spread via `arrow_rolling_min` / `arrow_rolling_max`, flag when spread ≤ tolerance.

**Spread** — same rolling window, flag when (max − min) > `max_spread`.

`apply_faults_arrow` must return a **boolean PyArrow array** (same length as `table.num_rows`).

## 5. Interactive Python (optional)

```python
import json
from pathlib import Path
import pyarrow.compute as pc
import data
import rule

table = data.load_table()
cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
mask = rule.apply_faults_arrow(table, cfg, context={{"site_id": data.SITE_ID}})
print("rows", table.num_rows, "flagged", int(pc.sum(mask).as_py()))
```

## 6. Upload to Open-FDD

When satisfied, upload **only** `rule.py` on the **Rule Lab** tab (integrator login).
Helper functions in the same file are fine; `apply_faults_arrow` is the required entrypoint.
"""


def build_rule_kit_zip(
    *,
    site_id: str | None = None,
    rule_id: str | None = None,
    lookback_hours: float = 3,
    limit: int = 5000,
    point_keys: list[str] | None = None,
) -> tuple[bytes, str]:
    """Return (zip_bytes, download_filename)."""
    svc = ModelService()
    ttl = TtlService()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)
    model = svc.load()

    rule_code = DEFAULT_ARROW_RULE
    rule_name = "new_rule"
    config: dict[str, Any] = {}
    column_map = build_column_map_from_model_points(model, sid)

    if rule_id:
        rule = RuleStore().get(rule_id)
        if not rule:
            raise RuleKitError(f"rule not found: {rule_id}")
        rule_name = str(rule.get("name") or rule_id)
        path = str(rule.get("source_path") or "")
        disk = read_source(path) if path else ""
        rule_code = disk.strip() or str(rule.get("code") or "").strip() or DEFAULT_ARROW_RULE
        cfg_raw = rule.get("config")
        if isinstance(cfg_raw, dict) and cfg_raw:
            config = dict(cfg_raw)
        cm = rule.get("column_map")
        if isinstance(cm, dict) and cm:
            column_map = dict(cm)

    keys = list(point_keys or [])
    if not keys and rule_id:
        rule = RuleStore().get(rule_id) or {}
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        keys = [str(x) for x in (bindings.get("point_ids") or []) if str(x).strip()]

    frame, origin = load_frame_for_run(sid, source="bacnet", columns=None)
    if frame is None or (hasattr(frame, "empty") and frame.empty):
        frame, origin = load_frame_for_run(sid, columns=None)
    if frame is None:
        frame = pd.DataFrame()

    config = infer_kit_config(rule_code, config)
    export_rule_code = augment_rule_code_for_kit_export(rule_code)

    scoped, data_cols = _scope_frame(frame, model, sid, point_keys=keys or None)
    table = _frame_to_kit_table(scoped, lookback_hours=lookback_hours, limit=limit)

    buf = io.BytesIO()
    feather.write_feather(table, buf)
    feather_bytes = buf.getvalue()

    preview: list[dict[str, Any]] = []
    if table.num_rows > 0:
        pdf = table.to_pandas()
        if "timestamp" in pdf.columns:
            pdf["timestamp"] = pdf["timestamp"].astype(str)
        preview = pdf.head(12).to_dict(orient="records")

    slug = Path(rule_name).name.replace(" ", "_").lower()[:40] or "rule"
    zip_name = f"openfdd-rule-kit-{slug}.zip"

    row_count = int(table.num_rows)
    readme = _readme_content(
        site_id=sid,
        rule_name=rule_name,
        lookback_hours=lookback_hours,
        row_count=row_count,
    )
    data_py = _data_py_content(
        site_id=sid,
        lookback_hours=lookback_hours,
        columns=data_cols,
        preview_rows=preview,
        row_count=row_count,
    )
    meta = {
        "site_id": sid,
        "lookback_hours": lookback_hours,
        "data_source": origin,
        "row_count": int(table.num_rows),
        "columns": data_cols,
        "rule_id": rule_id or "",
        "rule_name": rule_name,
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("rule.py", export_rule_code)
        zf.writestr("data.py", data_py)
        zf.writestr("sample.feather", feather_bytes)
        zf.writestr("column_map.json", json.dumps(column_map, indent=2))
        zf.writestr("config.json", json.dumps(config, indent=2))
        zf.writestr("config_keys.json", json.dumps(CONFIG_KEYS_GUIDE, indent=2))
        zf.writestr("kit_meta.json", json.dumps(meta, indent=2))
        zf.writestr("run_test.py", RUN_TEST_PY)
        zf.writestr("README.md", readme)
    return out.getvalue(), zip_name


def ingest_uploaded_rule(
    *,
    code: str,
    filename: str,
    rule_id: str | None = None,
    saved_by: str = "operator",
) -> dict[str, Any]:
    """Validate and upsert uploaded rule.py (create or update)."""
    validate_uploaded_rule(code, filename=filename)
    store = RuleStore()
    existing = store.get(rule_id) if rule_id else None
    name = str(existing.get("name") if existing else name_from_filename(filename))
    payload: dict[str, Any] = {
        "id": rule_id or None,
        "name": name,
        "mode": "rule",
        "backend": "arrow",
        "code": code,
        "config": dict(existing.get("config") or {}) if existing else {},
        "column_map": dict(existing.get("column_map") or {}) if existing else {},
        "bindings": existing.get("bindings") if existing else {},
        "severity": str(existing.get("severity") or "warning") if existing else "warning",
        "enabled": bool(existing.get("enabled", True)) if existing else True,
        "source_path": str(existing.get("source_path") or "") if existing else "",
    }
    if not existing:
        payload["name"] = name_from_filename(filename)
    return store.upsert(payload, saved_by=saved_by)
