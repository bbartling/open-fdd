"""Arrow runtime threading and batch configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ArrowRuntimeConfig:
    cpu_threads: int
    io_threads: int
    batch_rows: int
    parallel_rules: bool
    parallel_sites: bool
    default_backend: str

    def as_dict(self) -> dict[str, int | bool | str]:
        return {
            "cpu_threads": self.cpu_threads,
            "io_threads": self.io_threads,
            "batch_rows": self.batch_rows,
            "parallel_rules": self.parallel_rules,
            "parallel_sites": self.parallel_sites,
            "default_backend": self.default_backend,
        }


_CONFIGURED = False


def get_arrow_runtime_config() -> ArrowRuntimeConfig:
    default_backend = os.environ.get("OPEN_FDD_FDD_BACKEND", "arrow").strip() or "arrow"
    if default_backend not in {"arrow", "legacy_row"}:
        default_backend = "arrow"
    return ArrowRuntimeConfig(
        cpu_threads=max(1, _env_int("OPEN_FDD_ARROW_THREADS", 0) or os.cpu_count() or 4),
        io_threads=max(1, _env_int("OPEN_FDD_ARROW_IO_THREADS", 0) or min(8, os.cpu_count() or 4)),
        batch_rows=max(1000, _env_int("OPEN_FDD_ARROW_BATCH_ROWS", 50_000)),
        parallel_rules=_env_bool("OPEN_FDD_ARROW_PARALLEL_RULES", True),
        parallel_sites=_env_bool("OPEN_FDD_ARROW_PARALLEL_SITES", True),
        default_backend=default_backend,
    )


def configure_arrow_runtime(*, force: bool = False) -> ArrowRuntimeConfig:
    """Apply PyArrow thread pools from environment (idempotent)."""
    global _CONFIGURED
    cfg = get_arrow_runtime_config()
    if _CONFIGURED and not force:
        return cfg
    try:
        import pyarrow as pa

        pa.set_cpu_count(cfg.cpu_threads)
        if hasattr(pa, "set_io_thread_count"):
            pa.set_io_thread_count(cfg.io_threads)
    except Exception:
        pass
    _CONFIGURED = True
    return cfg
