"""The ONE pager the repo's Python scripts use for NF list routes (point/query, sites, ...). Standard library only.

NF 3.10.x ``POST /api/v1/point/query`` returns ``totalCount`` but NO ``nextPageToken``: it pages with ``pageOffset``
(#1550). A loop that only follows a next-page token reads the first page (500 records) and stops without an error.
``page_all`` never trusts a single signal (same algorithm as nf-app/hooks/lib/paging.js, static/nf.js and
open_fdd/nf/client.py):

1. a ``nextPageToken`` is followed when the response has one (a repeated token is an error, not a loop);
2. otherwise ``pageOffset`` advances by the records received until ``totalCount`` is reached, or an empty page comes
   back; with no ``totalCount`` a short page (fewer than ``pageSize``) ends it too;
3. a page that adds nothing new (the server ignored ``pageOffset``) is an error;
4. fewer records than ``totalCount`` after an empty page is an error (short read);
5. a hard cap (``max_records`` / ``max_pages``) ends in a loud ``PagingError``, never a partial list.

Used by scripts/nf/hooks/nf_app_sync.py and scripts/nf/tools/nf_common.py (both put this folder on sys.path).
"""

from __future__ import annotations

import json
from typing import Any, Callable

DEFAULT_PAGE_SIZE = 500
DEFAULT_MAX_RECORDS = 200_000
DEFAULT_MAX_PAGES = 1000


class PagingError(SystemExit):
    """A paged read that could not be completed (cap, loop, short read). A SystemExit so a script prints the message
    and stops; callers that degrade (`except SystemExit`) still print it."""


def _identity(rec: Any) -> str:
    if isinstance(rec, dict):
        ident = rec.get("uuid") or rec.get("id")
        if ident:
            return str(ident)
    return json.dumps(rec, sort_keys=True, default=str)


def _total(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def page_all(fetch: Callable[[dict], dict], key: str = "points", *, page_size: int = DEFAULT_PAGE_SIZE,
             max_records: int = DEFAULT_MAX_RECORDS, max_pages: int = DEFAULT_MAX_PAGES,
             what: str = "NF list") -> list[dict]:
    """Every record of a paged NF list route. ``fetch(params)`` does one request (``params`` has ``pageSize`` and,
    after the first page, ``pageOffset`` or ``pageToken``) and returns the response body; ``key`` is its array field."""
    out: list[dict] = []
    seen: set[str] = set()
    tokens: set[str] = set()
    token = ""
    offset = 0
    total: int | None = None
    pages = 0
    while True:
        if pages >= max_pages or offset >= max_records:
            raise PagingError(f"{what}: paging cap reached after {offset} records in {pages} pages "
                              f"(totalCount {'unknown' if total is None else total}); refusing to continue with a "
                              "partial result. Narrow the query")
        params: dict[str, Any] = {"pageSize": page_size}
        if token:
            params["pageToken"] = token
        elif offset > 0:
            params["pageOffset"] = offset
        page = fetch(params) or {}
        pages += 1
        recs = page.get(key) or []
        t = _total(page.get("totalCount"))
        if t is not None:
            total = t
        added = 0
        for r in recs:
            ident = _identity(r)
            if ident in seen:
                continue
            seen.add(ident)
            out.append(r)
            added += 1
        if recs and not added:
            raise PagingError(f"{what}: page {pages} repeated records already read (the server ignored "
                              f"{'pageToken' if token else f'pageOffset {offset}'}); refusing to loop")
        offset += len(recs)
        nxt = page.get("nextPageToken") or ""
        if nxt:
            if nxt in tokens:
                raise PagingError(f"{what}: nextPageToken repeated; refusing to loop")
            tokens.add(nxt)
            token = nxt
            continue
        token = ""
        if not recs:
            break
        if total is not None:
            if offset >= total:
                break
        elif len(recs) < page_size:
            break
    if total is not None and offset < total:
        raise PagingError(f"{what}: read {offset} of totalCount {total} records, then the server returned an empty "
                          "page; refusing to continue with a partial result")
    return out
