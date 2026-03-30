#!/usr/bin/env python3
"""
Portable modeling regression / report helper (replaces hardcoded Windows paths).

Writes a markdown report under the bench ``reports/`` directory by default.
Override with env:

  AI_MODELING_REPORT_DIR=/path/to/dir
  # or
  OPENCLAW_BENCH_REPORT_DIR=/path/to/dir

Optional: fetch ``GET /data-model/export`` when ``--api-url`` is set (requires httpx).

Example:
  python openclaw/bench/scripts/ai_modeling_pass.py --api-url http://localhost:8000
  AI_MODELING_REPORT_DIR=/tmp/ofdd-reports python openclaw/bench/scripts/ai_modeling_pass.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_DIR = SCRIPT_DIR.parent
REPO_ROOT = BENCH_DIR.parent.parent


def _default_report_dir() -> Path:
    env = (
        os.environ.get("AI_MODELING_REPORT_DIR")
        or os.environ.get("OPENCLAW_BENCH_REPORT_DIR")
        or ""
    ).strip()
    if env:
        return Path(env).expanduser().resolve()
    return (BENCH_DIR / "reports").resolve()


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"')
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("\\'", "'")
            if key and os.environ.get(key) is None:
                os.environ[key] = value


def _fetch_export(api_url: str, site_id: str | None) -> tuple[int, object]:
    try:
        import httpx
    except ImportError:
        return 0, {"error": "pip install httpx"}
    base = api_url.rstrip("/")
    path = "/data-model/export"
    if site_id:
        path = f"{path}?site_id={site_id}"
    headers = {}
    key = os.environ.get("OFDD_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    r = httpx.get(f"{base}{path}", headers=headers or None, timeout=60.0)
    try:
        body = r.json()
    except Exception:
        body = {"_raw": (r.text or "")[:2000]}
    return r.status_code, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-FDD AI modeling pass report (portable paths)")
    parser.add_argument("--api-url", help="If set, GET /data-model/export and summarize row counts")
    parser.add_argument("--site-id", help="Optional site filter for export")
    args = parser.parse_args()

    _load_env_file(REPO_ROOT / "stack" / ".env")

    report_dir = _default_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    out_path = report_dir / f"ai-modeling-pass-{stamp}.md"

    lines = [
        f"# AI modeling pass report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Report dir: `{report_dir}` (override: `AI_MODELING_REPORT_DIR` or `OPENCLAW_BENCH_REPORT_DIR`)",
        f"- Repo root: `{REPO_ROOT}`",
        "",
    ]

    if args.api_url:
        code, body = _fetch_export(args.api_url, args.site_id)
        lines.append("## Export snapshot")
        lines.append("")
        lines.append(f"- `GET /data-model/export` → HTTP {code}")
        if isinstance(body, list):
            lines.append(f"- Rows: {len(body)}")
            if body and isinstance(body[0], dict):
                sample_keys = sorted(body[0].keys())
                lines.append(f"- Sample keys: {', '.join(sample_keys[:20])}{'…' if len(sample_keys) > 20 else ''}")
        else:
            lines.append(f"- Body (preview): `{json.dumps(body)[:800]}`")
        lines.append("")

    lines.extend(
        [
            "## Operator checklist (before live import)",
            "",
            "- [ ] Export JSON still has real `bacnet_device_id` / `object_identifier` / `external_id` (not invented).",
            "- [ ] `site_id` UUIDs match `GET /sites` (never replace with display name only).",
            "- [ ] `PUT /data-model/import` validated (Pydantic / OpenAPI schema) before apply.",
            "- [ ] After import: spot-check BACnet reads for a few modeled points.",
            "",
        ]
    )

    text = "\n".join(lines)
    out_path.write_text(text, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
