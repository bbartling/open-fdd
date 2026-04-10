"""Map flattened scrapes to Open-F-DD ``external_id`` columns (FDD engine input shape)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Set


def scrape_dict_to_external_id_row(
    flat_scrape: Mapping[str, Any],
    external_ids: Iterable[str],
    *,
    path_to_external_id: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build one dict keyed by ``external_id`` for a pandas row / RuleRunner input.

    ``flat_scrape`` should be ``dict(flatten_device_publish(...))`` or similar.

    Resolution order for each requested ``external_id``:

    1. Explicit ``path_to_external_id`` mapping ``scrape_path → external_id``.
    2. Otherwise treat ``external_id`` as a **suffix** match: first scrape key **ending with**
       ``"." + external_id`` or **equal** to ``external_id``.
    """
    ex_set: Set[str] = {str(x) for x in external_ids}
    out: Dict[str, Any] = {e: None for e in sorted(ex_set)}

    if path_to_external_id:
        for path, ex in path_to_external_id.items():
            p = str(path)
            if ex in ex_set and p in flat_scrape:
                out[str(ex)] = flat_scrape[p]

    items: list[Tuple[str, Any]] = list(flat_scrape.items())
    for ex in ex_set:
        if out.get(ex) is not None:
            continue
        for path, val in items:
            if path == ex or path.endswith("." + ex):
                out[ex] = val
                break
    return out


def merge_flatten_into_row(
    row: MutableMapping[str, Any],
    flat_scrape: Mapping[str, Any],
    external_ids: Iterable[str],
    *,
    path_to_external_id: Optional[Mapping[str, str]] = None,
) -> MutableMapping[str, Any]:
    """Update ``row`` in place with values from :func:`scrape_dict_to_external_id_row`."""
    patch = scrape_dict_to_external_id_row(
        flat_scrape, external_ids, path_to_external_id=path_to_external_id
    )
    row.update(patch)
    return row
