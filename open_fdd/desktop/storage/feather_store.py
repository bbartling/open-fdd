from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from open_fdd.desktop.storage.paths import feather_root


def _safe_name(value: str) -> str:
    out = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value.strip())
    return out or "default"


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
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.root / _safe_name(source) / _safe_name(site_id)
        path.mkdir(parents=True, exist_ok=True)
        out = path / f"{ts}.feather"
        frame.reset_index(drop=True).to_feather(out)
        return out

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
        return pd.concat(frames, ignore_index=True)

