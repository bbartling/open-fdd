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
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import data_dir

_log = logging.getLogger(__name__)


def _feather_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        return False


_USE_FEATHER = _feather_available()
LATEST_NAME = "latest.feather" if _USE_FEATHER else "latest.pkl"
_SHARD_GLOB = "*.feather" if _USE_FEATHER else "*.pkl"
_SHARD_EXT = ".feather" if _USE_FEATHER else ".pkl"

if not _USE_FEATHER:
    _log.warning("pyarrow not installed — feather store using pandas pickle (%s)", LATEST_NAME)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _write_df(df: pd.DataFrame, path: Path) -> None:
    out = df.reset_index(drop=True)
    if _USE_FEATHER:
        out.to_feather(path)
    else:
        out.to_pickle(path)


def _read_df(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if _USE_FEATHER:
        import pyarrow.feather as feather

        _apply_arrow_thread_env()
        if columns:
            table = feather.read_table(path, columns=_column_list(columns), use_threads=True)
            return table.to_pandas()
        return pd.read_feather(path)
    df = pd.read_pickle(path)
    if columns:
        keep = [c for c in _column_list(columns) if c in df.columns]
        return df[keep] if keep else df
    return df


def _column_list(columns: list[str] | str | None) -> list[str] | None:
    if columns is None:
        return None
    if isinstance(columns, str):
        columns = [columns]
    out: list[str] = []
    seen: set[str] = set()
    for c in columns:
        s = str(c).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    if not out:
        return None
    if TIMESTAMP_COL not in seen:
        return [TIMESTAMP_COL, *out]
    return out


def _apply_arrow_thread_env() -> None:
    if not _USE_FEATHER:
        return
    try:
        from open_fdd.arrow_runtime.config import configure_arrow_runtime

        configure_arrow_runtime()
    except Exception:
        n = _env_int("OPEN_FDD_ARROW_THREADS", 0) or _env_int("OFDD_ARROW_IO_THREADS", 0)
        if n <= 0:
            return
        try:
            import pyarrow as pa

            pa.set_cpu_count(n)
        except Exception:
            pass


def _concat_arrow_tables(tables: list[Any]) -> Any:
    """Merge feather shards; tolerate mixed int/float column types across shards."""
    import pyarrow as pa

    if len(tables) == 1:
        return tables[0]
    try:
        return pa.concat_tables(tables, promote_options="default")
    except (pa.ArrowTypeError, pa.ArrowInvalid) as exc:
        _log.warning("concat_tables default failed (%s); retrying permissive", exc)
    try:
        return pa.concat_tables(tables, promote_options="permissive")
    except Exception as exc:
        _log.warning("concat_tables permissive failed (%s); falling back to pandas", exc)
    frames = [t.to_pandas() for t in tables]
    merged = pd.concat(frames, ignore_index=True)
    return pa.Table.from_pandas(merged, preserve_index=False)


def read_site_arrow(
    store: FeatherStore,
    site_id: str,
    source: str = "bacnet",
    *,
    columns: list[str] | str | None = None,
) -> Any | None:
    """Preferred Arrow-native read — returns ``pyarrow.Table`` without pandas."""
    return store.read_site_table(site_id, source=source, columns=columns)


def feather_compact_workers_from_env() -> int:
    return max(1, _env_int("OFDD_FEATHER_COMPACT_WORKERS", 1))


def feather_compact_on_ingest_from_env() -> bool:
    return os.environ.get("OFDD_FEATHER_COMPACT_ON_INGEST", "").strip().lower() in {"1", "true", "yes"}


def feather_compact_shard_threshold_from_env() -> int:
    return max(2, _env_int("OFDD_FEATHER_COMPACT_SHARD_THRESHOLD", 8))


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
        return sorted(site.glob(_SHARD_GLOB))

    def list_sites(self, source: str | None = None) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if not self.root.is_dir():
            return out
        sources = [self.root / _safe(source)] if source else sorted(p for p in self.root.iterdir() if p.is_dir())
        for src_dir in sources:
            if not src_dir.is_dir():
                continue
            for site in sorted(p for p in src_dir.iterdir() if p.is_dir()):
                if any(site.glob(_SHARD_GLOB)):
                    out.append({"source": src_dir.name, "site_id": site.name})
        return out

    def total_bytes(self) -> int:
        """Total on-disk size of all ``*.feather`` files under the store root."""
        if not self.root.is_dir():
            return 0
        total = 0
        for path in self.root.rglob(_SHARD_GLOB):
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

    def read_site(
        self,
        site_id: str,
        source: str = "bacnet",
        *,
        columns: list[str] | str | None = None,
    ) -> pd.DataFrame | None:
        """Read and merge every shard for a site, newest rows last, de-duplicated."""
        table = self.read_site_table(site_id, source=source, columns=columns)
        if table is None:
            return None
        if _USE_FEATHER:
            return _dedupe_sort(table.to_pandas())
        if isinstance(table, pd.DataFrame):
            return _dedupe_sort(table)
        return _dedupe_sort(table.to_pandas())

    def read_site_table(
        self,
        site_id: str,
        source: str = "bacnet",
        *,
        columns: list[str] | str | None = None,
    ) -> Any | None:
        """Merge shards into one Arrow table (or DataFrame when pyarrow is absent)."""
        files = self.shard_files(source, site_id)
        if not files:
            return None
        col_list = _column_list(columns)
        if _USE_FEATHER:
            import pyarrow as pa
            import pyarrow.feather as feather

            _apply_arrow_thread_env()
            tables: list[Any] = []
            for path in files:
                try:
                    tables.append(feather.read_table(path, columns=col_list, use_threads=True))
                except Exception as exc:  # noqa: BLE001
                    _log.warning("Skipping unreadable feather shard %s: %s", path, exc)
            if not tables:
                return None
            if len(tables) == 1:
                return tables[0]
            return _concat_arrow_tables(tables)

        frames: list[pd.DataFrame] = []
        for path in files:
            try:
                frames.append(_read_df(path, col_list))
            except Exception as exc:  # noqa: BLE001
                _log.warning("Skipping unreadable feather shard %s: %s", path, exc)
        if not frames:
            return None
        return pd.concat(frames, ignore_index=True)

    def write_shard(self, df: pd.DataFrame, *, source: str, site_id: str) -> Path:
        site = self.site_dir(source, site_id)
        site.mkdir(parents=True, exist_ok=True)
        # ms + uuid — two writes in the same millisecond must not overwrite each other.
        name = f"shard-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}{_SHARD_EXT}"
        path = site / name
        _write_df(df, path)
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
        site.mkdir(parents=True, exist_ok=True)
        if _USE_FEATHER:
            import pyarrow as pa

            table = pa.Table.from_pandas(df.reset_index(drop=True), preserve_index=False)
            import pyarrow.feather as feather

            feather.write_feather(table, tmp)
        else:
            _write_df(df, tmp)
        tmp.replace(latest)
        removed = 0
        for path in files:
            if path.name != LATEST_NAME and path.exists():
                path.unlink()
                removed += 1
        return {"shards": removed, "rows": int(len(df))}

    def compact_all(self, *, source: str | None = None) -> dict[str, Any]:
        """Compact every site (optionally parallel across sites)."""
        sites = self.list_sites(source)
        workers = min(feather_compact_workers_from_env(), max(1, len(sites)))

        def _one(entry: dict[str, str]) -> dict[str, int]:
            return self.compact(source=entry["source"], site_id=entry["site_id"])

        if workers <= 1 or len(sites) <= 1:
            results = [_one(e) for e in sites]
        else:
            results = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_one, e) for e in sites]
                for fut in as_completed(futures):
                    results.append(fut.result())
        rows = sum(int(r.get("rows") or 0) for r in results)
        shards = sum(int(r.get("shards") or 0) for r in results)
        return {"sites": len(sites), "rows": rows, "shards_removed": shards, "workers": workers}

    def maybe_compact_after_ingest(self, *, source: str, site_id: str) -> dict[str, int] | None:
        """Compact on ingest only when env requests it or loose shard count exceeds threshold."""
        if feather_compact_on_ingest_from_env():
            return self.compact(source=source, site_id=site_id)
        loose = sum(
            1 for p in self.shard_files(source, site_id) if p.name != LATEST_NAME and p.is_file()
        )
        if loose >= feather_compact_shard_threshold_from_env():
            return self.compact(source=source, site_id=site_id)
        return None

    def _prune_one_site(self, src: str, site_id: str, cutoff: pd.Timestamp) -> dict[str, int]:
        if _USE_FEATHER:
            table = self.read_site_table(site_id, source=src)
            if table is None:
                return {"dropped": 0, "touched": 0}
            if TIMESTAMP_COL not in table.column_names:
                self.compact(source=src, site_id=site_id)
                return {"dropped": 0, "touched": 0}
            try:
                import pyarrow as pa
                import pyarrow.compute as pc

                ts = table[TIMESTAMP_COL]
                if not pa.types.is_timestamp(ts.type):
                    ts = pc.cast(ts, pa.timestamp("ns", tz="UTC"))
                cutoff_scalar = pa.scalar(cutoff.to_pydatetime(), type=ts.type)
                keep = pc.or_(pc.is_null(ts), pc.greater_equal(ts, cutoff_scalar))
                filtered = table.filter(keep)
                dropped = int(table.num_rows - filtered.num_rows)
                if dropped == 0:
                    self.compact(source=src, site_id=site_id)
                    return {"dropped": 0, "touched": 0}
                df = _dedupe_sort(filtered.to_pandas())
                site = self.site_dir(src, site_id)
                latest = site / LATEST_NAME
                tmp = site / f".{LATEST_NAME}.tmp"
                site.mkdir(parents=True, exist_ok=True)
                out = pa.Table.from_pandas(df.reset_index(drop=True), preserve_index=False)
                import pyarrow.feather as feather

                feather.write_feather(out, tmp)
                tmp.replace(latest)
                for path in self.shard_files(src, site_id):
                    if path.name != LATEST_NAME and path.exists():
                        path.unlink()
                return {"dropped": dropped, "touched": 1}
            except Exception as exc:  # noqa: BLE001
                _log.warning("Arrow prune failed for %s/%s: %s — pandas fallback", src, site_id, exc)

        df = self.read_site(site_id, source=src)
        if df is None or TIMESTAMP_COL not in df.columns:
            return {"dropped": 0, "touched": 0}
        ts = pd.to_datetime(df[TIMESTAMP_COL], utc=True, errors="coerce")
        keep_mask = ts.isna() | (ts >= cutoff)
        dropped = int((~keep_mask).sum())
        if dropped == 0:
            self.compact(source=src, site_id=site_id)
            return {"dropped": 0, "touched": 0}
        kept = df[keep_mask].reset_index(drop=True)
        site = self.site_dir(src, site_id)
        latest = site / LATEST_NAME
        tmp = site / f".{LATEST_NAME}.tmp"
        site.mkdir(parents=True, exist_ok=True)
        _write_df(kept, tmp)
        tmp.replace(latest)
        for path in self.shard_files(src, site_id):
            if path.name != LATEST_NAME and path.exists():
                path.unlink()
        return {"dropped": dropped, "touched": 1}

    def prune(self, *, retention_days: int, source: str | None = None) -> dict[str, object]:
        """Drop rows older than ``retention_days`` for every (or one) source.

        Compacts first so each site collapses to a single retained shard.
        """
        if retention_days <= 0:
            return {"sites": 0, "rows_dropped": 0, "skipped": "retention_days<=0"}
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=retention_days)
        sites = self.list_sites(source)
        workers = min(feather_compact_workers_from_env(), max(1, len(sites)))
        total_dropped = 0
        touched = 0

        def _one(entry: dict[str, str]) -> dict[str, int]:
            return self._prune_one_site(entry["source"], entry["site_id"], cutoff)

        if workers <= 1 or len(sites) <= 1:
            results = [_one(e) for e in sites]
        else:
            results = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_one, e) for e in sites]
                for fut in as_completed(futures):
                    results.append(fut.result())
        for r in results:
            total_dropped += int(r.get("dropped") or 0)
            touched += int(r.get("touched") or 0)
        return {
            "sites": touched,
            "rows_dropped": total_dropped,
            "retention_days": retention_days,
            "workers": workers,
        }

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

        df = _read_df(latest)
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
        _write_df(kept, tmp)
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
        result = store.compact_all(source=args.source)
        _log.info("compact_all: %s", result)
    if not args.prune and not args.compact and not args.enforce_max:
        _log.info(
            "sites=%s total_bytes=%d max_gib=%s retention_days=%d",
            store.list_sites(args.source),
            store.total_bytes(),
            args.max_gib,
            args.retention_days,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
