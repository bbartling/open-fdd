"""Rule Lab dev kit — export zip (rule.py + sample data) and validate uploads (Arrow-only)."""

from __future__ import annotations

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


def _frame_to_kit_table(df: pd.DataFrame, *, limit: int = 500) -> pa.Table:
    if df is None or df.empty:
        return pa.table({"timestamp": pa.array([], type=pa.timestamp("us", tz="UTC"))})
    sample = df.copy()
    if "timestamp" in sample.columns:
        sample = sample.sort_values("timestamp")
    if limit and len(sample) > limit:
        sample = sample.tail(limit)
    return pa.Table.from_pandas(sample, preserve_index=False)


def _data_py_content(*, site_id: str, lookback_hours: float, columns: list[str], preview_rows: list[dict]) -> str:
    preview_json = json.dumps(preview_rows[:12], indent=2, default=str)
    cols_json = json.dumps(columns, indent=2)
    return f'''"""Open-FDD Rule Lab sample data — generated from feather historian.

Edit rule.py locally. Use data.load_table() for the full sample.feather snapshot.
"""
from __future__ import annotations

from pathlib import Path

SITE_ID = {site_id!r}
LOOKBACK_HOURS = {lookback_hours}
COLUMNS = {cols_json}

# First rows preview (full window is in sample.feather):
ROWS = {preview_json}


def load_table():
    """Load PyArrow table from bundled sample.feather."""
    import pyarrow.feather as feather

    path = Path(__file__).resolve().parent / "sample.feather"
    return feather.read_table(path)
'''


def _readme_content(*, site_id: str, rule_name: str) -> str:
    return f"""# Open-FDD Rule Lab kit — {rule_name}

## Setup

```bash
pip install "open-fdd>=3.0.1" pyarrow
```

## Files

| File | Purpose |
|------|---------|
| `rule.py` | Arrow rule — must define `apply_faults_arrow(table, cfg, context=None)` |
| `data.py` | Sample metadata + `load_table()` helper |
| `sample.feather` | Historian snapshot from site `{site_id}` |
| `column_map.json` | BRICK logical keys → feather column names |
| `config.json` | Suggested rule config for quick test |

## Local quick test

```python
from pathlib import Path
import json
import pyarrow.compute as pc

import data
import rule

table = data.load_table()
cfg = json.loads(Path("config.json").read_text())
mask = rule.apply_faults_arrow(table, cfg, context={{"site_id": data.SITE_ID}})
print("rows", table.num_rows, "flagged", int(pc.sum(mask).as_py()))
```

## Upload

When ready, upload **only** `rule.py` on the Rule Lab tab (integrator login).
Extra helper functions in the file are fine; `apply_faults_arrow` is the entrypoint.
"""


def build_rule_kit_zip(
    *,
    site_id: str | None = None,
    rule_id: str | None = None,
    lookback_hours: float = 24,
    limit: int = 500,
    point_keys: list[str] | None = None,
) -> tuple[bytes, str]:
    """Return (zip_bytes, download_filename)."""
    svc = ModelService()
    ttl = TtlService()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)
    model = svc.load()

    rule_code = DEFAULT_ARROW_RULE
    rule_name = "new_rule"
    config: dict[str, Any] = {"max_zone_temp": 75}
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

    scoped, data_cols = _scope_frame(frame, model, sid, point_keys=keys or None)
    table = _frame_to_kit_table(scoped, limit=limit)

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

    readme = _readme_content(site_id=sid, rule_name=rule_name)
    data_py = _data_py_content(
        site_id=sid,
        lookback_hours=lookback_hours,
        columns=data_cols,
        preview_rows=preview,
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
        zf.writestr("rule.py", rule_code)
        zf.writestr("data.py", data_py)
        zf.writestr("sample.feather", feather_bytes)
        zf.writestr("column_map.json", json.dumps(column_map, indent=2))
        zf.writestr("config.json", json.dumps(config, indent=2))
        zf.writestr("kit_meta.json", json.dumps(meta, indent=2))
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
