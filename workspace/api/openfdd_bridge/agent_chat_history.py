"""Trim agent chat history for Ollama — bounded tokens without dropping the latest turn."""

from __future__ import annotations

import os
from typing import Any, Literal

Role = Literal["user", "assistant"]

_MAX_MESSAGE_CHARS = 4000
_MAX_USER_CHARS = 8000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def history_max_chars() -> int:
    return max(500, _env_int("OFDD_AGENT_CHAT_HISTORY_MAX_CHARS", 8000))


def history_max_turns() -> int:
    return max(2, _env_int("OFDD_AGENT_CHAT_MAX_TURNS", 10))


def per_message_max_chars() -> int:
    return max(200, _env_int("OFDD_AGENT_CHAT_MESSAGE_MAX_CHARS", 2000))


def normalize_history(raw: list[Any] | None) -> list[dict[str, str]]:
    """Accept {role, content} from the browser; ignore pending/invalid rows."""
    if not raw:
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if not content or content == "…":
            continue
        out.append({"role": role, "content": _clip(content, per_message_max_chars())})
    return out


def trim_history(
    turns: list[dict[str, str]],
    *,
    max_chars: int | None = None,
    max_turns: int | None = None,
) -> list[dict[str, str]]:
    """Keep the newest turns that fit under char + turn limits."""
    if not turns:
        return []
    char_cap = history_max_chars() if max_chars is None else max(1, max_chars)
    turn_cap = history_max_turns() if max_turns is None else max(1, max_turns)
    kept: list[dict[str, str]] = []
    used = 0
    for row in reversed(turns):
        if len(kept) >= turn_cap:
            break
        piece = row["content"]
        if used + len(piece) > char_cap and kept:
            break
        if used + len(piece) > char_cap:
            piece = _clip(piece, max(200, char_cap - used))
        kept.append({"role": row["role"], "content": piece})
        used += len(piece)
    kept.reverse()
    return kept


def build_ollama_messages(
    *,
    message: str,
    history: list[Any] | None,
    system: str,
) -> list[dict[str, str]]:
    """System + trimmed prior turns + current user message."""
    prior = trim_history(normalize_history(history))
    user_text = _clip(message.strip(), _MAX_USER_CHARS)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.extend(prior)
    messages.append({"role": "user", "content": user_text})
    return messages


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."
