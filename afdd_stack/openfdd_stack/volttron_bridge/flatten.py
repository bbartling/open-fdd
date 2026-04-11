"""Flatten nested VOLTTRON / BACnet scrape payloads into leaf paths and values."""

from __future__ import annotations

from typing import Any, Iterator, Tuple, Union

Leaf = Union[int, float, str, bool, type(None)]


def flatten_device_publish(
    payload: Any,
    *,
    prefix: str = "",
    present_value_key: str = "presentValue",
) -> Iterator[Tuple[str, Leaf]]:
    """
    Walk a nested dict (typical platform-driver ``all`` publish) and yield ``(path, value)``.

    - If a dict value contains ``presentValue``, emits one row: ``f"{prefix}{key}"`` → that scalar.
    - Otherwise recurses into dicts with dotted path segments.
    - Lists are indexed as ``[0]``, ``[1]``, … for stable paths (rare in scrapes).
    - Other scalars emit as-is when ``prefix`` is non-empty or key is top-level scalar.
    """
    if isinstance(payload, dict):
        for key, val in payload.items():
            safe_key = str(key).strip()
            if not safe_key:
                continue
            path = f"{prefix}.{safe_key}" if prefix else safe_key
            if isinstance(val, dict) and present_value_key in val:
                pv = val[present_value_key]
                if _is_leaf(pv):
                    yield path, pv  # type: ignore[assignment]
                continue
            if isinstance(val, dict):
                yield from flatten_device_publish(
                    val, prefix=path, present_value_key=present_value_key
                )
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    sub = f"{path}[{i}]"
                    if _is_leaf(item):
                        yield sub, item  # type: ignore[assignment]
                    elif isinstance(item, dict):
                        yield from flatten_device_publish(
                            item, prefix=sub, present_value_key=present_value_key
                        )
            elif _is_leaf(val):
                yield path, val  # type: ignore[assignment]
    elif _is_leaf(payload) and prefix:
        yield prefix, payload  # type: ignore[assignment]


def _is_leaf(v: Any) -> bool:
    return isinstance(v, (int, float, str, bool)) or v is None
