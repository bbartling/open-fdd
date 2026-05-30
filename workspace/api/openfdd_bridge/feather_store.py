"""Local pyarrow/feather timeseries store for per-site, per-source shards.

Layout (under ``data_dir()``)::

    feather_store/<source>/<site_id>/latest.feather
    feather_store/<source>/<site_id>/shard-<epoch_ms>.feather

Drivers append shards; :func:`compact` merges them into ``latest.feather`` and
:func:`prune` drops rows older than a retention window. The store is pandas
native (``read_feather`` / ``to_feather``) so it stays edge-friendly with no
database server.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .paths import data_dir

_log = logging.getLogger(__name__)

LATEST_NAME = "latest.feather"
TIMESTAMP_COL = "timestamp"


@dataclass
class FeatherStore:
    root: Path = field(default_factory=lambda: data_dir() / "feather_store")

    def site_dir(self, source: str, site_id: str) -> Path:
        return self.root / _safe(source) / _safe(site_id)

    def shard_files(self, source: str, site_id: str) -> list[Path]:
        site = self.site_dir(source, site_id)
        if not site.is_dir():
            return []
        return sorted(site.glob("*.feather"))

    def list_sites(self, source: str | None = None) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if not self.root.is_dir():
            return out
        sources = [self.root / _safe(source)] if source else sorted(p for p in self.root.iterdir() if p.is_dir())
        for src_dir in sources:
            if not src_dir.is_dir():
                continue
            for site in sorted(p for p in src_dir.iterdir() if p.is_dir()):
                if any(site.glob("*.feather")):
                    out.append({"source": src_dir.name, "site_id": site.name})
        return out

    def read_site(self, site_id: str, source: str = "bacnet") -> pd.DataFrame | None:
        """Read and merge every shard for a site, newest rows last, de-duplicated."""
        files = self.shard_files(source, site_id)
        if not files:
            return None
        frames: list[pd.DataFrame] = []
        for path in files:
            try:
                frames.append(pd.read_feather(path))
            except Exception as exc:  # noqa: BLE001 - skip a corrupt shard, keep the rest
                _log.warning("Skipping unreadable feather shard %s: %s", path, exc)
        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True)
        return _dedupe_sort(df)

    def write_shard(self, df: pd.DataFrame, *, source: str, site_id: str) -> Path:
        site = self.site_dir(source, site_id)
        site.mkdir(parents=True, exist_ok=True)
        name = f"shard-{int(time.time() * 1000)}.feather"
        path = site / name
        df.reset_index(drop=True).to_feather(path)
        return path

    def compact(self, *, source: str, site_id: str) -> dict[str, int]:
        """Merge all shards into ``latest.feather`` and remove the loose shards."""
        files = self.shard_files(source, site_id)
        if not files:
            return {"shards": 0, "rows": 0}
        df = self.read_site(site_id, source=source)
        if df is None:
            return {"shards": 0, "rows": 0}
        site = self.site_dir(source, site_id)
        latest = site / LATEST_NAME
        tmp = site / f".{LATEST_NAME}.tmp"
        df.reset_index(drop=True).to_feather(tmp)
        tmp.replace(latest)
        removed = 0
        for path in files:
            if path.name != LATEST_NAME and path.exists():
                path.unlink()
                removed += 1
        return {"shards": removed, "rows": int(len(df))}

    def prune(self, *, retention_days: int, source: str | None = None) -> dict[str, object]:
        """Drop rows older than ``retention_days`` for every (or one) source.

        Compacts first so each site collapses to a single retained shard.
        """
        if retention_days <= 0:
            return {"sites": 0, "rows_dropped": 0, "skipped": "retention_days<=0"}
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=retention_days)
        sites = self.list_sites(source)
        total_dropped = 0
        touched = 0
        for entry in sites:
            src = entry["source"]
            site_id = entry["site_id"]
            df = self.read_site(site_id, source=src)
            if df is None or TIMESTAMP_COL not in df.columns:
                continue
            ts = pd.to_datetime(df[TIMESTAMP_COL], utc=True, errors="coerce")
            keep_mask = ts.isna() | (ts >= cutoff)
            dropped = int((~keep_mask).sum())
            if dropped == 0:
                # Still compact so shard sprawl is bounded.
                self.compact(source=src, site_id=site_id)
                continue
            kept = df[keep_mask].reset_index(drop=True)
            site = self.site_dir(src, site_id)
            latest = site / LATEST_NAME
            tmp = site / f".{LATEST_NAME}.tmp"
            site.mkdir(parents=True, exist_ok=True)
            kept.reset_index(drop=True).to_feather(tmp)
            tmp.replace(latest)
            for path in self.shard_files(src, site_id):
                if path.name != LATEST_NAME and path.exists():
                    path.unlink()
            total_dropped += dropped
            touched += 1
        return {"sites": touched, "rows_dropped": total_dropped, "retention_days": retention_days}


def _safe(part: str) -> str:
    cleaned = "".join(c for c in str(part) if c.isalnum() or c in {"-", "_", "."}).strip(".")
    return cleaned or "default"


def _dedupe_sort(df: pd.DataFrame) -> pd.DataFrame:
    if TIMESTAMP_COL in df.columns:
        df = df.copy()
        df[TIMESTAMP_COL] = pd.to_datetime(df[TIMESTAMP_COL], utc=True, errors="coerce")
        df = df.sort_values(TIMESTAMP_COL).drop_duplicates(subset=[TIMESTAMP_COL], keep="last")
    return df.reset_index(drop=True)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Open-FDD feather store maintenance")
    parser.add_argument("--prune", action="store_true", help="drop rows older than --retention-days")
    parser.add_argument("--compact", action="store_true", help="merge shards into latest.feather")
    parser.add_argument("--retention-days", type=int, default=int(_env_int("OFDD_FEATHER_RETENTION_DAYS", 90)))
    parser.add_argument("--source", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = FeatherStore()
    if args.prune:
        result = store.prune(retention_days=args.retention_days, source=args.source)
        _log.info("prune: %s", result)
    if args.compact and not args.prune:
        for entry in store.list_sites(args.source):
            store.compact(source=entry["source"], site_id=entry["site_id"])
        _log.info("compacted %d site(s)", len(store.list_sites(args.source)))
    if not args.prune and not args.compact:
        _log.info("sites: %s", store.list_sites(args.source))
    return 0


def _env_int(name: str, default: int) -> int:
    import os

    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(_main())
