"""Parallel read-only Edge HTTP helpers with per-call timeouts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from portfolio.collector.edge_client import EdgeClient


def run_parallel(
    tasks: dict[str, Callable[[], Any]],
    *,
    max_workers: int = 4,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run named callables; return (results, errors_by_name)."""
    if not tasks:
        return {}, {}
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    workers = min(max_workers, len(tasks))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:
                errors[name] = str(exc)[:300]
    return results, errors


def edge_client_for_site(site_id: str) -> tuple[Any, str, EdgeClient]:
    from portfolio.central.edge_registry import resolve_site_config, resolve_token

    site = resolve_site_config(site_id)
    token = resolve_token(site)
    return site, token, EdgeClient(site.base_url)
