from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]{2,}")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]

