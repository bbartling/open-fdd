from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from uuid import uuid4
from typing import Iterable
import shutil

import pandas as pd

from open_fdd.desktop.column_utils import dedupe_dataframe_columns
from open_fdd.desktop.storage.paths import feather_root


def _safe_name(value: str) -> str:
    raw = str(value or "").strip()
    out = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in raw)
    out = out or "default"
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{out}_{suffix}"


@dataclass
class FeatherStore:
    root: Path = field(default_factory=feather_root)

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> Path:
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Feather support requires pyarrow. Install desktop extras: pip install open-fdd[desktop]"
            ) from exc
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        nonce = uuid4().hex[:8]
        path = self.root / _safe_name(source) / _safe_name(site_id)
        path.mkdir(parents=True, exist_ok=True)
        out = path / f"{ts}_{nonce}.feather"
        frame.reset_index(drop=True).to_feather(out)
        return out

    def replace_site_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> Path:
        """
        Atomically replace all Feather shards for ``source`` + ``site_id`` with ``frame``.

        Writes to a ``*.feather.tmp`` file in the site directory, verifies it can be read back,
        removes existing ``*.feather`` shards, then renames the temp file to ``*.feather``.
        Avoids data loss if the write fails before the old files are removed.
        """
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Feather support requires pyarrow. Install desktop extras: pip install open-fdd[desktop]"
            ) from exc
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        nonce = uuid4().hex[:8]
        path = self.root / _safe_name(source) / _safe_name(site_id)
        path.mkdir(parents=True, exist_ok=True)
        tmp = path / f"{ts}_{nonce}.feather.tmp"
        final = path / f"{ts}_{nonce}.feather"
        frame.reset_index(drop=True).to_feather(tmp)
        pd.read_feather(tmp)
        for f in path.glob("*.feather"):
            f.unlink(missing_ok=True)
        for f in path.glob("*.feather.tmp"):
            if f.resolve() != tmp.resolve():
                f.unlink(missing_ok=True)
        tmp.rename(final)
        return final

    def iter_site_files(self, *, source: str, site_id: str) -> Iterable[Path]:
        path = self.root / _safe_name(source) / _safe_name(site_id)
        if not path.exists():
            return []
        return sorted(path.glob("*.feather"))

    def read_site_frames(self, *, source: str, site_id: str) -> pd.DataFrame:
        files = list(self.iter_site_files(source=source, site_id=site_id))
        if not files:
            return pd.DataFrame()
        frames = [pd.read_feather(f) for f in files]
        merged = pd.concat(frames, ignore_index=True)
        return dedupe_dataframe_columns(merged)

    def purge(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]:
        files_deleted = 0
        dirs_deleted = 0
        bytes_deleted = 0

        def _delete_file(path: Path) -> None:
            nonlocal files_deleted, bytes_deleted
            if not path.exists() or not path.is_file():
                return
            bytes_deleted += path.stat().st_size
            path.unlink(missing_ok=True)
            files_deleted += 1

        if source and site_id:
            target = self.root / _safe_name(source) / _safe_name(site_id)
            for f in target.glob("*.feather"):
                _delete_file(f)
            if target.exists() and not any(target.iterdir()):
                target.rmdir()
                dirs_deleted += 1
            parent = target.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                dirs_deleted += 1
            return {"files_deleted": files_deleted, "dirs_deleted": dirs_deleted, "bytes_deleted": bytes_deleted}

        if source and not site_id:
            target = self.root / _safe_name(source)
            if target.exists():
                for f in target.rglob("*.feather"):
                    _delete_file(f)
                shutil.rmtree(target, ignore_errors=True)
                dirs_deleted += 1
            return {"files_deleted": files_deleted, "dirs_deleted": dirs_deleted, "bytes_deleted": bytes_deleted}

        if site_id and not source:
            sid = _safe_name(site_id)
            for source_dir in self.root.iterdir() if self.root.exists() else []:
                if not source_dir.is_dir():
                    continue
                target = source_dir / sid
                for f in target.glob("*.feather"):
                    _delete_file(f)
                if target.exists() and not any(target.iterdir()):
                    target.rmdir()
                    dirs_deleted += 1
                if source_dir.exists() and not any(source_dir.iterdir()):
                    source_dir.rmdir()
                    dirs_deleted += 1
            return {"files_deleted": files_deleted, "dirs_deleted": dirs_deleted, "bytes_deleted": bytes_deleted}

        if self.root.exists():
            for f in self.root.rglob("*.feather"):
                _delete_file(f)
            shutil.rmtree(self.root, ignore_errors=True)
            self.root.mkdir(parents=True, exist_ok=True)
            dirs_deleted += 1
        return {"files_deleted": files_deleted, "dirs_deleted": dirs_deleted, "bytes_deleted": bytes_deleted}

    def stats(self) -> dict[str, int]:
        if not self.root.exists():
            return {"file_count": 0, "source_count": 0, "site_count": 0, "bytes_total": 0}
        file_count = 0
        site_dirs: set[str] = set()
        source_dirs: set[str] = set()
        bytes_total = 0
        for source_dir in self.root.iterdir():
            if not source_dir.is_dir():
                continue
            source_dirs.add(source_dir.name)
            for site_dir in source_dir.iterdir():
                if not site_dir.is_dir():
                    continue
                site_dirs.add(f"{source_dir.name}/{site_dir.name}")
                for f in site_dir.glob("*.feather"):
                    file_count += 1
                    bytes_total += f.stat().st_size
        return {
            "file_count": file_count,
            "source_count": len(source_dirs),
            "site_count": len(site_dirs),
            "bytes_total": bytes_total,
        }

