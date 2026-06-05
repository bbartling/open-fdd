"""Small Arrow array helpers shared across the runtime."""

from __future__ import annotations

import pyarrow as pa


def as_array(value: pa.Array | pa.ChunkedArray) -> pa.Array:
    if isinstance(value, pa.ChunkedArray):
        return value.combine_chunks()
    return value
