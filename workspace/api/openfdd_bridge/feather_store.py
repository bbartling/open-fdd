"""Local pyarrow/feather timeseries store for per-site, per-source shards.

Layout (under ``data_dir()``)::

    feather_store/<source>/<site_id>/latest.feather
    feather_store/<source>/<site_id>/shard-<epoch_ms>.feather

Drivers append shards; :func:`compact` merges them into ``latest.feather`` and
:func:`prune` drops rows older than a retention window. :func:`enforce_max_bytes`
deletes whole loose shards first (oldest epoch first), then trims ``latest.feather``
in time chunks when a GiB cap is configured via ``OFDD_FEATHER_MAX_GIB``.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import data_dir

_log = logging.getLogger(__name__)

LATEST_NAME = "latest.feather"
TIMESTAMP_COL = "timestamp"
GIB = 1024**3
_SHARD_EPOCH_RE = re.compile(r"^shard-(\d+)-")


@dataclass(frozen=True)
class StorageChunk:
    """Deletable storage unit — whole loose shard or a trimmable latest file."""

    path: Path
    source: str
    site_id: str
    kind: str  # loose_shard | latest
    sort_key: int
    size_bytes: int


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

    def total_bytes(self) -> int:
        """Total on-disk size of all ``*.feather`` files under the store root."""
        if not self.root.is_dir():
            return 0
        total = 0
        for path in self.root.rglob("*.feather"):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def list_loose_shards(self, *, source: str | None = None) -> list[StorageChunk]:
        """Loose shard files sorted oldest-first (by embedded epoch ms, then mtime)."""
        chunks: list[StorageChunk] = []
        for entry in self.list_sites(source):
            src = entry["source"]
            site_id = entry["site_id"]
            for path in self.shard_files(src, site_id):
                if path.name == LATEST_NAME:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                epoch = _shard_epoch_ms(path.name)
                sort_key = epoch if epoch is not None else int(path.stat().st_mtime * 1000)
                chunks.append(
                    StorageChunk(
                        path=path,
                        source=src,
                        site_id=site_id,
                        kind="loose_shard",
                        sort_key=sort_key,
                        size_bytes=size,
                    )
                )
        chunks.sort(key=lambda c: (c.sort_key, str(c.path)))
        return chunks

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
        # ms + uuid — two writes in the same millisecond must not overwrite each other.
        name = f"shard-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.feather"
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

    def trim_latest_oldest_chunk(
        self,
        *,
        source: str,
        site_id: str,
        chunk_hours: int = 24,
    ) -> dict[str, int]:
        """Drop the oldest time window from ``latest.feather`` (or oldest 10% rows as fallback)."""
        latest = self.site_dir(source, site_id) / LATEST_NAME
        if not latest.is_file():
            return {"rows_dropped": 0, "bytes_freed": 0}
        try:
            before_size = latest.stat().st_size
        except OSError:
            return {"rows_dropped": 0, "bytes_freed": 0}

        df = pd.read_feather(latest)
        if len(df) <= 1:
            return {"rows_dropped": 0, "bytes_freed": 0}

        dropped = 0
        kept = df
        if TIMESTAMP_COL in df.columns:
            ts = pd.to_datetime(df[TIMESTAMP_COL], utc=True, errors="coerce")
            min_ts = ts.min()
            if pd.notna(min_ts) and chunk_hours > 0:
                cutoff = min_ts + pd.Timedelta(hours=chunk_hours)
                keep_mask = ts.isna() | (ts >= cutoff)
                kept = df[keep_mask]
                dropped = len(df) - len(kept)

        if kept.empty and len(df) > 1:
            # Remaining span is shorter than chunk_hours — drop a fractional chunk instead.
            drop_n = max(1, len(df) // 10)
            kept = df.iloc[drop_n:].reset_index(drop=True)
            dropped = drop_n
        elif dropped <= 0 and len(df) > 1:
            drop_n = max(1, len(df) // 10)
            kept = df.iloc[drop_n:].reset_index(drop=True)
            dropped = drop_n
        elif dropped > 0:
            kept = kept.reset_index(drop=True)

        if kept.empty:
            return {"rows_dropped": 0, "bytes_freed": 0}

        tmp = latest.with_name(f".{LATEST_NAME}.tmp")
        kept.to_feather(tmp)
        tmp.replace(latest)
        after_size = latest.stat().st_size
        return {"rows_dropped": dropped, "bytes_freed": max(0, before_size - after_size)}

    def enforce_max_bytes(
        self,
        max_bytes: int,
        *,
        trim_chunk_hours: int = 24,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Delete oldest loose shards, then trim ``latest.feather`` until under ``max_bytes``.

        Phase 1 removes whole shard files (cheap, no pandas read). Phase 2 drops
        the oldest ``trim_chunk_hours`` window from the largest ``latest.feather``.
        """
        if max_bytes <= 0:
            return {
                "skipped": "max_bytes<=0",
                "before_bytes": self.total_bytes(),
                "after_bytes": self.total_bytes(),
                "bytes_freed": 0,
            }

        before = self.total_bytes()
        if before <= max_bytes:
            return {
                "before_bytes": before,
                "after_bytes": before,
                "bytes_freed": 0,
                "max_bytes": max_bytes,
                "shards_deleted": 0,
                "rows_trimmed": 0,
                "trim_passes": 0,
            }

        shards_deleted = 0
        rows_trimmed = 0
        trim_passes = 0
        bytes_freed = 0

        while self.total_bytes() > max_bytes:
            loose = self.list_loose_shards(source=source)
            if not loose:
                break
            chunk = loose[0]
            try:
                chunk.path.unlink(missing_ok=True)
            except OSError as exc:
                _log.warning("Failed to delete feather shard %s: %s", chunk.path, exc)
                break
            shards_deleted += 1
            bytes_freed += chunk.size_bytes

        while self.total_bytes() > max_bytes:
            target = self._largest_latest_file(source=source)
            if target is None:
                break
            result = self.trim_latest_oldest_chunk(
                source=target["source"],
                site_id=target["site_id"],
                chunk_hours=trim_chunk_hours,
            )
            if result["rows_dropped"] <= 0 and result["bytes_freed"] <= 0:
                break
            trim_passes += 1
            rows_trimmed += result["rows_dropped"]
            bytes_freed += result["bytes_freed"]

        after = self.total_bytes()
        return {
            "before_bytes": before,
            "after_bytes": after,
            "bytes_freed": max(0, before - after),
            "max_bytes": max_bytes,
            "shards_deleted": shards_deleted,
            "rows_trimmed": rows_trimmed,
            "trim_passes": trim_passes,
            "trim_chunk_hours": trim_chunk_hours,
        }

    def _largest_latest_file(self, *, source: str | None = None) -> dict[str, str] | None:
        best_size = -1
        best: dict[str, str] | None = None
        for entry in self.list_sites(source):
            latest = self.site_dir(entry["source"], entry["site_id"]) / LATEST_NAME
            if not latest.is_file():
                continue
            try:
                size = latest.stat().st_size
            except OSError:
                continue
            if size > best_size:
                best_size = size
                best = {"source": entry["source"], "site_id": entry["site_id"]}
        return best


def feather_retention_days_from_env() -> int:
    return _env_int("OFDD_FEATHER_RETENTION_DAYS", 90)


def feather_max_gib_from_env() -> float:
    return _env_float("OFDD_FEATHER_MAX_GIB", 0.0)


def feather_trim_chunk_hours_from_env() -> int:
    return max(1, _env_int("OFDD_FEATHER_TRIM_CHUNK_HOURS", 24))


def maintain_storage(
    *,
    retention_days: int | None = None,
    max_gib: float | None = None,
    trim_chunk_hours: int | None = None,
    source: str | None = None,
    store: FeatherStore | None = None,
) -> dict[str, Any]:
    """Run day-based prune then GiB cap enforcement (both optional via env/args)."""
    fs = store or FeatherStore()
    out: dict[str, Any] = {"before_bytes": fs.total_bytes()}

    days = feather_retention_days_from_env() if retention_days is None else retention_days
    if days > 0:
        out["prune"] = fs.prune(retention_days=days, source=source)

    cap_gib = feather_max_gib_from_env() if max_gib is None else max_gib
    if cap_gib > 0:
        chunk_h = feather_trim_chunk_hours_from_env() if trim_chunk_hours is None else max(1, trim_chunk_hours)
        out["enforce_max"] = fs.enforce_max_bytes(
            int(cap_gib * GIB),
            trim_chunk_hours=chunk_h,
            source=source,
        )

    out["after_bytes"] = fs.total_bytes()
    return out


def maintain_storage_if_needed(store: FeatherStore | None = None) -> dict[str, Any] | None:
    """Fast path after ingest: only enforce GiB cap when the store is over limit."""
    cap_gib = feather_max_gib_from_env()
    if cap_gib <= 0:
        return None
    fs = store or FeatherStore()
    max_bytes = int(cap_gib * GIB)
    before = fs.total_bytes()
    if before <= max_bytes:
        return None
    result = fs.enforce_max_bytes(
        max_bytes,
        trim_chunk_hours=feather_trim_chunk_hours_from_env(),
    )
    result["trigger"] = "over_limit"
    return result


def _shard_epoch_ms(name: str) -> int | None:
    match = _SHARD_EPOCH_RE.match(name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


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
    parser.add_argument("--enforce-max", action="store_true", help="delete oldest data until under --max-gib")
    parser.add_argument(
        "--maintain",
        action="store_true",
        help="run prune (if retention-days>0) then enforce-max (if max-gib>0)",
    )
    parser.add_argument("--compact", action="store_true", help="merge shards into latest.feather")
    parser.add_argument("--retention-days", type=int, default=feather_retention_days_from_env())
    parser.add_argument(
        "--max-gib",
        type=float,
        default=feather_max_gib_from_env(),
        help="max feather store size in GiB (0=disabled; env OFDD_FEATHER_MAX_GIB)",
    )
    parser.add_argument(
        "--trim-chunk-hours",
        type=int,
        default=feather_trim_chunk_hours_from_env(),
        help="oldest time window dropped per trim pass on latest.feather",
    )
    parser.add_argument("--source", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = FeatherStore()

    if args.maintain:
        result = maintain_storage(
            retention_days=args.retention_days,
            max_gib=args.max_gib,
            trim_chunk_hours=args.trim_chunk_hours,
            source=args.source,
            store=store,
        )
        _log.info("maintain: %s", result)
        return 0

    if args.prune:
        result = store.prune(retention_days=args.retention_days, source=args.source)
        _log.info("prune: %s", result)
    if args.enforce_max:
        if args.max_gib <= 0:
            _log.info("enforce-max skipped (max-gib<=0)")
        else:
            result = store.enforce_max_bytes(
                int(args.max_gib * GIB),
                trim_chunk_hours=max(1, args.trim_chunk_hours),
                source=args.source,
            )
            _log.info("enforce-max: %s", result)
    if args.compact and not args.prune and not args.enforce_max:
        for entry in store.list_sites(args.source):
            store.compact(source=entry["source"], site_id=entry["site_id"])
        _log.info("compacted %d site(s)", len(store.list_sites(args.source)))
    if not args.prune and not args.compact and not args.enforce_max:
        _log.info(
            "sites=%s total_bytes=%d max_gib=%s retention_days=%d",
            store.list_sites(args.source),
            store.total_bytes(),
            args.max_gib,
            args.retention_days,
        )
    return 0


def _env_int(name: str, default: int) -> int:
    import os

    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    import os

    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(_main())
